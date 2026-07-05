"""
WickSense Video Analyzer — wicksense-video-analyzer
====================================================
PURPOSE: Video/transcript analysis ONLY.

This service does NOT run:
  - Market data polling or scanning
  - TwelveData fetches
  - Readiness scoring
  - Paper trading logic
  - Trade lifecycle management
  - Signal scanning or generation
  - /scan-markets
  - /tradeplan

Exposed routes (ONLY):
  GET  /                              — Service identity check
  GET  /api/video-health              — Video microservice health check
  POST /api/extract-youtube-transcript — Transcript extraction via RapidAPI / fallback
  POST /api/youtube-ingest            — Full YouTube media ingestion pipeline
  POST /api/chat-completion           — Server-side Claude/OpenAI proxy (Knowledge Analyzer)

Environment variables required:
  ANTHROPIC_API_KEY         — Claude API key
  OPENAI_API_KEY            — OpenAI API key (optional, for Whisper API fallback)
  SUPABASE_URL              — Supabase project URL
  SUPABASE_SERVICE_ROLE_KEY — Supabase service role key
  RAPIDAPI_KEY              — RapidAPI key for YouTube Transcript API
  RAPIDAPI_HOST             — RapidAPI host (youtube-transcript3.p.rapidapi.com)
  PORT                      — Render sets this automatically
"""

import os
import sys
import json
import time
import shutil
import logging
import traceback
import subprocess
import base64
import re
import html as html_module
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS

from chat_completion import handle_chat_completion_request

try:
    import requests as http_requests
    HTTP_REQUESTS_AVAILABLE = True
except ImportError:
    HTTP_REQUESTS_AVAILABLE = False

# ── Build identity ─────────────────────────────────────────────────────────────
BUILD_DATE    = "2026-05-31T19:00:00Z"
BUILD_VERSION = "1.0.0"
SERVICE_NAME  = "wicksense-video-analyzer"

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("wicksense.video-analyzer")

# ── Service identity banner ────────────────────────────────────────────────────
log.info("=" * 70)
log.info("[SERVICE] %s — VIDEO ANALYZER MICROSERVICE", SERVICE_NAME)
log.info("[SERVICE] Version: %s  Build: %s", BUILD_VERSION, BUILD_DATE)
log.info("[SERVICE] Routes: GET / | GET /api/video-health | POST /api/extract-youtube-transcript | POST /api/youtube-ingest | POST /api/chat-completion")
log.info("[SERVICE] NO market scanning. NO TwelveData. NO paper trading. NO signals. NO trade lifecycle.")
log.info("=" * 70)
log.info("VIDEO_ANALYZER_V1_0_ACTIVE")

# ── HARD GUARD: Neutralize any market/trading env vars ────────────────────────
_MARKET_ENV_VARS = [
    "TWELVE_DATA_API_KEY",
    "TWELVEDATA_API_KEY",
    "VITE_TWELVEDATA_API_KEY",
    "MARKET_SYMBOLS",
    "SCAN_MARKETS",
    "MARKET_POLL_INTERVAL",
    "MARKET_READINESS_URL",
    "TRADING_BACKEND_URL",
]
_neutralized = []
for _var in _MARKET_ENV_VARS:
    if os.environ.get(_var):
        os.environ.pop(_var, None)
        _neutralized.append(_var)
if _neutralized:
    log.warning("[GUARD] Neutralized market/TwelveData env vars: %s", _neutralized)
else:
    log.info("[GUARD] No market/TwelveData env vars detected — container is clean")

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app, origins=[
    "https://wicksense7625.builtwithrocket.new",
    "https://wicksensetrading.com",
    "http://localhost:4028",
    "http://127.0.0.1:4028",
    "http://localhost:5173",
])

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY         = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL           = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
OPENAI_API_KEY            = os.environ.get("OPENAI_API_KEY", "")
SUPABASE_URL              = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
RAPIDAPI_KEY              = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST             = os.environ.get("RAPIDAPI_HOST", "youtube-transcript3.p.rapidapi.com")
MAX_FRAMES                = int(os.environ.get("MAX_FRAMES", "8"))
FRAME_INTERVAL_S          = int(os.environ.get("FRAME_INTERVAL_S", "30"))
WHISPER_MODEL             = os.environ.get("WHISPER_MODEL", "base")
TMP_DIR                   = os.environ.get("TMP_DIR", "/tmp")

log.info("[SERVICE] Config — model=%s, whisper=%s, max_frames=%d", ANTHROPIC_MODEL, WHISPER_MODEL, MAX_FRAMES)
log.info("[SERVICE] RapidAPI host=%s, key_present=%s", RAPIDAPI_HOST, bool(RAPIDAPI_KEY))
log.info("[SERVICE] Supabase URL present=%s, service_role_key present=%s", bool(SUPABASE_URL), bool(SUPABASE_SERVICE_ROLE_KEY))
log.info("[SERVICE] Market scanning: DISABLED | TwelveData: DISABLED | Paper trading: DISABLED | Trade lifecycle: DISABLED")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Container / Dependency Verification
# ═══════════════════════════════════════════════════════════════════════════════

def check_binary(name):
    try:
        result = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=10)
        version = (result.stdout or result.stderr or "").strip().splitlines()[0]
        log.info("[BINARY-CHECK] ✓ %s — %s", name, version)
        return {"available": True, "version": version}
    except FileNotFoundError:
        log.error("[BINARY-CHECK] ✗ %s — NOT FOUND in PATH", name)
        return {"available": False, "version": None, "error": "%s not found in PATH" % name}
    except Exception as exc:
        log.error("[BINARY-CHECK] ✗ %s — %s", name, exc)
        return {"available": False, "version": None, "error": str(exc)}


def check_tmp_writable():
    test_path = os.path.join(TMP_DIR, "wicksense_write_test_%d.tmp" % int(time.time()))
    try:
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        log.info("[TMP-CHECK] ✓ %s is writable", TMP_DIR)
        return {"writable": True, "path": TMP_DIR}
    except Exception as exc:
        log.error("[TMP-CHECK] ✗ %s not writable: %s", TMP_DIR, exc)
        return {"writable": False, "path": TMP_DIR, "error": str(exc)}


def check_whisper_import():
    try:
        import whisper  # noqa: F401
        log.info("[WHISPER-CHECK] ✓ openai-whisper importable")
        return {"available": True}
    except ImportError as exc:
        log.error("[WHISPER-CHECK] ✗ openai-whisper not installed: %s", exc)
        return {"available": False, "error": str(exc)}


def check_anthropic_import():
    try:
        import anthropic  # noqa: F401
        log.info("[ANTHROPIC-CHECK] ✓ anthropic SDK importable")
        return {"available": True}
    except ImportError as exc:
        log.error("[ANTHROPIC-CHECK] ✗ anthropic SDK not installed: %s", exc)
        return {"available": False, "error": str(exc)}


def run_container_checks():
    log.info("[CONTAINER-CHECKS] Running startup diagnostics...")
    checks = {
        "yt_dlp":    check_binary("yt-dlp"),
        "ffmpeg":    check_binary("ffmpeg"),
        "ffprobe":   check_binary("ffprobe"),
        "tmp":       check_tmp_writable(),
        "whisper":   check_whisper_import(),
        "anthropic": check_anthropic_import(),
    }
    all_ok = all([
        checks["yt_dlp"]["available"],
        checks["ffmpeg"]["available"],
        checks["tmp"]["writable"],
        checks["whisper"]["available"],
    ])
    log.info("[CONTAINER-CHECKS] All checks passed: %s", all_ok)
    return {"all_ok": all_ok, "checks": checks}


CONTAINER_STATUS = run_container_checks()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Subprocess Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def run_subprocess(cmd, label, timeout=300):
    log.info("[SUBPROCESS:%s] Starting: %s", label, " ".join(cmd))
    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        elapsed = round(time.time() - start, 2)
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                log.debug("[SUBPROCESS:%s][STDOUT] %s", label, line)
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                log.debug("[SUBPROCESS:%s][STDERR] %s", label, line)
        log.info("[SUBPROCESS:%s] Finished — returncode=%d, elapsed=%.2fs", label, result.returncode, elapsed)
        return {"success": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "elapsed_s": elapsed}
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        log.error("[SUBPROCESS:%s] TIMEOUT after %ds", label, timeout)
        return {"success": False, "returncode": -1, "stdout": "", "stderr": "Process timed out after %ds" % timeout, "elapsed_s": elapsed}
    except Exception as exc:
        elapsed = round(time.time() - start, 2)
        log.error("[SUBPROCESS:%s] EXCEPTION: %s", label, exc)
        return {"success": False, "returncode": -1, "stdout": "", "stderr": str(exc), "elapsed_s": elapsed}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — yt-dlp Audio Download
# ═══════════════════════════════════════════════════════════════════════════════

def download_audio_ytdlp(youtube_url, output_path, diag):
    log.info("[YT-DLP] Starting audio download: %s -> %s", youtube_url, output_path)
    diag["ytdlp_attempted"] = True

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--no-playlist",
        "--no-warnings",
        "--no-check-certificate",
        "--user-agent", "Mozilla/5.0 (compatible; WickSense/1.0)",
        "--output", output_path,
        youtube_url,
    ]

    result = run_subprocess(cmd, "YT-DLP", timeout=240)
    diag["ytdlp_returncode"]  = result["returncode"]
    diag["ytdlp_elapsed_s"]   = result["elapsed_s"]
    diag["ytdlp_stderr_tail"] = result["stderr"][-2000:] if result["stderr"] else ""
    diag["ytdlp_stdout_tail"] = result["stdout"][-1000:] if result["stdout"] else ""

    if not result["success"]:
        error_msg = result["stderr"] or "yt-dlp exited with code %d" % result["returncode"]
        log.error("[YT-DLP] FAILED: %s", error_msg)
        diag["ytdlp_success"] = False
        diag["ytdlp_error"]   = error_msg
        return False

    actual_path = output_path
    if not os.path.exists(actual_path):
        base = output_path.rsplit(".", 1)[0]
        for ext in [".mp3", ".m4a", ".webm", ".opus"]:
            candidate = base + ext
            if os.path.exists(candidate):
                actual_path = candidate
                break

    if not os.path.exists(actual_path):
        log.error("[YT-DLP] Audio file not found after download: %s", output_path)
        diag["ytdlp_success"] = False
        diag["ytdlp_error"]   = "Audio file not created at %s" % output_path
        return False

    file_size_bytes = os.path.getsize(actual_path)
    file_size_mb    = round(file_size_bytes / (1024 * 1024), 3)
    log.info("[YT-DLP] ✓ Audio downloaded: %s (%.3f MB)", actual_path, file_size_mb)
    diag["ytdlp_success"]    = True
    diag["ytdlp_error"]      = None
    diag["audio_file_path"]  = actual_path
    diag["audio_size_bytes"] = file_size_bytes
    diag["audio_size_mb"]    = file_size_mb
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — ffmpeg Frame Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_frames_ffmpeg(audio_path, video_url, frames_dir, diag):
    log.info("[FFMPEG] Starting frame extraction from: %s", video_url)
    diag["ffmpeg_attempted"] = True

    os.makedirs(frames_dir, exist_ok=True)
    frame_pattern = os.path.join(frames_dir, "frame_%04d.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_url,
        "-vf", "fps=1/%d,scale=1024:-1" % FRAME_INTERVAL_S,
        "-frames:v", str(MAX_FRAMES),
        "-q:v", "3",
        frame_pattern,
    ]

    result = run_subprocess(cmd, "FFMPEG", timeout=180)
    diag["ffmpeg_returncode"]  = result["returncode"]
    diag["ffmpeg_elapsed_s"]   = result["elapsed_s"]
    diag["ffmpeg_stderr_tail"] = result["stderr"][-2000:] if result["stderr"] else ""

    if not result["success"]:
        log.warning("[FFMPEG] Frame extraction failed (returncode=%d)", result["returncode"])
        diag["ffmpeg_error"] = result["stderr"][-500:] if result["stderr"] else "ffmpeg exited %d" % result["returncode"]

    frame_files = sorted(Path(frames_dir).glob("frame_*.jpg"))
    log.info("[FFMPEG] Frames found on disk: %d", len(frame_files))
    diag["ffmpeg_frames_on_disk"] = len(frame_files)

    frames_b64 = []
    for fp in frame_files[:MAX_FRAMES]:
        try:
            with open(fp, "rb") as f:
                data = f.read()
            b64 = base64.b64encode(data).decode("utf-8")
            frames_b64.append("data:image/jpeg;base64,%s" % b64)
        except Exception as exc:
            log.warning("[FFMPEG] Could not encode frame %s: %s", fp, exc)

    log.info("[FFMPEG] ✓ Frames encoded for Claude: %d", len(frames_b64))
    diag["frames_extracted"] = len(frames_b64)
    diag["ffmpeg_success"]   = len(frames_b64) > 0
    return frames_b64


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Whisper Transcription
# ═══════════════════════════════════════════════════════════════════════════════

def transcribe_with_whisper(audio_path, diag):
    log.info("[WHISPER] Starting transcription: %s (model=%s)", audio_path, WHISPER_MODEL)
    diag["whisper_attempted"] = True
    diag["whisper_model"]     = WHISPER_MODEL

    try:
        import whisper

        start = time.time()
        log.info("[WHISPER] Loading model '%s'...", WHISPER_MODEL)
        model = whisper.load_model(WHISPER_MODEL)
        log.info("[WHISPER] Model loaded in %.2fs", round(time.time() - start, 2))

        t_start    = time.time()
        result     = model.transcribe(audio_path, fp16=False, language="en")
        t_elapsed  = round(time.time() - t_start, 2)
        transcript = result.get("text", "").strip()
        char_count = len(transcript)

        log.info("[WHISPER] ✓ Transcription complete — chars=%d, elapsed=%.2fs", char_count, t_elapsed)
        diag["whisper_success"]    = True
        diag["whisper_char_count"] = char_count
        diag["whisper_elapsed_s"]  = t_elapsed
        diag["whisper_error"]      = None
        return transcript

    except ImportError:
        log.error("[WHISPER] openai-whisper not installed")
        diag["whisper_success"]    = False
        diag["whisper_char_count"] = 0
        diag["whisper_error"]      = "openai-whisper not installed"
        return ""
    except Exception as exc:
        log.error("[WHISPER] Transcription failed: %s\n%s", exc, traceback.format_exc())
        diag["whisper_success"]    = False
        diag["whisper_char_count"] = 0
        diag["whisper_error"]      = str(exc)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Claude Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_with_claude(transcript, frames, video_meta, diag):
    has_transcript = len(transcript.strip()) > 0
    has_frames     = len(frames) > 0

    log.info("[CLAUDE] Preparing payload — transcript_chars=%d, frames=%d, model=%s", len(transcript), len(frames), ANTHROPIC_MODEL)
    diag["claude_has_transcript"]        = has_transcript
    diag["claude_has_frames"]            = has_frames
    diag["claude_transcript_chars_sent"] = len(transcript)
    diag["claude_frames_sent"]           = len(frames)

    if not has_transcript and not has_frames:
        log.warning("[CLAUDE] No transcript and no frames — skipping Claude call")
        diag["claude_attempted"] = False
        diag["claude_error"]     = "No content to analyze"
        return ""

    if not ANTHROPIC_API_KEY:
        log.error("[CLAUDE] ANTHROPIC_API_KEY not set")
        diag["claude_attempted"] = False
        diag["claude_error"]     = "ANTHROPIC_API_KEY not set"
        return ""

    diag["claude_attempted"] = True

    try:
        import anthropic

        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        content = []

        if has_transcript:
            content.append({
                "type": "text",
                "text": (
                    "You are a professional trading analyst. Analyze the following trading video content.\n\n" "VIDEO TITLE: %s\nCHANNEL: %s\n\nTRANSCRIPT:\n%s\n\n" "Identify: trading strategies discussed, entry/exit rules, risk management, " "market conditions, technical indicators, and any specific setups mentioned." ) % (video_meta.get("title", "Unknown"), video_meta.get("channel", "Unknown"), transcript[:15000])
            })

        if has_frames:
            content.append({"type": "text", "text": "\nThe following %d video frames show charts and visuals. Analyze chart patterns, indicators, and setups visible:" % len(frames)})
            for i, frame_b64 in enumerate(frames[:8]):
                if "," in frame_b64:
                    media_type_part, data_part = frame_b64.split(",", 1)
                    media_type = "image/png" if "png" in media_type_part else "image/jpeg"
                else:
                    data_part  = frame_b64
                    media_type = "image/jpeg"
                content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_part}})

        if not has_transcript and has_frames:
            content.append({"type": "text", "text": "Based on the video frames above, describe the trading strategies, chart patterns, and setups visible. Extract actionable trading rules."})

        log.info("[CLAUDE] Sending request (model=%s, content_blocks=%d)...", ANTHROPIC_MODEL, len(content))
        start = time.time()

        response = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=4096, messages=[{"role": "user", "content": content}])
        elapsed  = round(time.time() - start, 2)
        analysis = response.content[0].text if response.content else ""
        log.info("[CLAUDE] ✓ Analysis complete — response_chars=%d, elapsed=%.2fs", len(analysis), elapsed)
        diag["claude_success"]        = True
        diag["claude_elapsed_s"]      = elapsed
        diag["claude_response_chars"] = len(analysis)
        diag["claude_stop_reason"]    = response.stop_reason
        diag["claude_error"]          = None
        return analysis

    except Exception as exc:
        log.error("[CLAUDE] API call failed: %s\n%s", exc, traceback.format_exc())
        diag["claude_success"] = False
        diag["claude_error"]   = str(exc)
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Temp File Management
# ═══════════════════════════════════════════════════════════════════════════════

def create_temp_workspace(video_id):
    workspace = os.path.join(TMP_DIR, "wicksense_%s_%d" % (video_id, int(time.time())))
    os.makedirs(workspace, exist_ok=True)
    log.info("[TMP] Created workspace: %s", workspace)
    return workspace


def cleanup_temp_workspace(workspace):
    try:
        shutil.rmtree(workspace, ignore_errors=True)
        log.info("[TMP] Cleaned up workspace: %s", workspace)
    except Exception as exc:
        log.warning("[TMP] Cleanup failed for %s: %s", workspace, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — YouTube Metadata
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_video_metadata(youtube_url, diag):
    log.info("[META] Fetching video metadata: %s", youtube_url)
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", "--no-warnings", youtube_url]
    result = run_subprocess(cmd, "YT-DLP-META", timeout=30)

    if result["success"] and result["stdout"].strip():
        try:
            meta = json.loads(result["stdout"].strip().splitlines()[0])
            video_meta = {
                "title":       meta.get("title", ""),
                "channel":     meta.get("uploader", meta.get("channel", "")),
                "duration":    meta.get("duration", 0),
                "description": (meta.get("description", "") or "")[:2000],
                "view_count":  meta.get("view_count", 0),
                "upload_date": meta.get("upload_date", ""),
                "video_id":    meta.get("id", ""),
            }
            log.info("[META] ✓ Metadata fetched: '%s' by %s (%ds)", video_meta["title"], video_meta["channel"], video_meta["duration"])
            diag["meta_fetched"] = True
            return video_meta
        except Exception as exc:
            log.warning("[META] JSON parse failed: %s", exc)

    log.warning("[META] Could not fetch metadata")
    diag["meta_fetched"] = False
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — RapidAPI Transcript Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_transcript_via_rapidapi(youtube_url, video_id, request_id):
    """Fetch transcript using RapidAPI YouTube Transcript API."""
    if not RAPIDAPI_KEY:
        log.warning("[RAPIDAPI:%s] RAPIDAPI_KEY not set — skipping RapidAPI", request_id)
        return None, "RAPIDAPI_KEY not set"

    if not HTTP_REQUESTS_AVAILABLE:
        return None, "requests library not available" log.info("[RAPIDAPI:%s] Fetching transcript for video_id=%s via RapidAPI", request_id, video_id)

    try:
        url = "https://%s/transcript" % RAPIDAPI_HOST
        headers = {
            "X-RapidAPI-Key":  RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST,
        }
        params = {"videoId": video_id, "lang": "en"}

        resp = http_requests.get(url, headers=headers, params=params, timeout=30)
        log.info("[RAPIDAPI:%s] Response: HTTP %d", request_id, resp.status_code)

        if resp.status_code != 200:
            error_msg = "RapidAPI returned HTTP %d: %s" % (resp.status_code, resp.text[:500])
            log.warning("[RAPIDAPI:%s] %s", request_id, error_msg)
            return None, error_msg

        data = resp.json()

        # Handle array of transcript segments
        if isinstance(data, list):
            transcript_text = " ".join(
                seg.get("text", "") for seg in data if seg.get("text")
            ).strip()
        elif isinstance(data, dict):
            transcript_text = data.get("transcript", data.get("text", ""))
            if isinstance(transcript_text, list):
                transcript_text = " ".join(
                    seg.get("text", "") if isinstance(seg, dict) else str(seg)
                    for seg in transcript_text
                ).strip()
        else:
            transcript_text = str(data)

        if transcript_text and len(transcript_text) > 50:
            log.info("[RAPIDAPI:%s] ✓ Transcript fetched — %d chars", request_id, len(transcript_text))
            return transcript_text, None
        else:
            log.warning("[RAPIDAPI:%s] Empty or short transcript (%d chars)", request_id, len(transcript_text) if transcript_text else 0)
            return None, "Empty transcript from RapidAPI"

    except Exception as exc:
        log.error("[RAPIDAPI:%s] Exception: %s", request_id, exc)
        return None, str(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10 — Route: POST /api/extract-youtube-transcript
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/extract-youtube-transcript", methods=["POST"])
def extract_youtube_transcript():
    """Extract transcript from a YouTube video via RapidAPI with Whisper fallback."""
    request_id = "txreq_%d" % int(time.time() * 1000)
    log.info("=" * 70)
    log.info("[YT-TRANSCRIPT:%s] POST /api/extract-youtube-transcript received", request_id)

    body        = request.get_json(silent=True) or {}
    youtube_url = (body.get("youtube_url") or body.get("url") or "").strip()

    log.info("[YT-TRANSCRIPT:%s] youtube_url = %s", request_id, youtube_url)

    if not youtube_url:
        return jsonify({"ok": False, "error": "youtube_url is required"}), 400

    if not any(x in youtube_url for x in ["youtube.com", "youtu.be"]):
        return jsonify({"ok": False, "error": "Not a valid YouTube URL"}), 400

    video_id_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{10,12})", youtube_url)
    video_id       = video_id_match.group(1) if video_id_match else "unknown" log.info("[YT-TRANSCRIPT:%s] video_id=%s", request_id, video_id)

    api_error = None

    # ── Method 1: RapidAPI ────────────────────────────────────────────────────
    log.info("[YT-TRANSCRIPT:%s] ── Method 1: RapidAPI ──", request_id)
    transcript_text, api_error = fetch_transcript_via_rapidapi(youtube_url, video_id, request_id)

    if transcript_text:
        log.info("=" * 70)
        return jsonify({"ok": True, "transcript_text": transcript_text, "source": "rapidapi"}), 200

    # ── Method 2: Whisper fallback ────────────────────────────────────────────
    yt_dlp_available  = CONTAINER_STATUS.get("checks", {}).get("yt_dlp", {}).get("available", False)
    whisper_available = CONTAINER_STATUS.get("checks", {}).get("whisper", {}).get("available", False)

    if yt_dlp_available and whisper_available:
        log.info("[YT-TRANSCRIPT:%s] ── Method 2: Whisper fallback ──", request_id)
        workspace = None
        try:
            workspace  = create_temp_workspace(video_id)
            audio_path = os.path.join(workspace, "audio_%s.mp3" % video_id)
            diag       = {}

            ytdlp_ok = download_audio_ytdlp(youtube_url, audio_path, diag)

            if ytdlp_ok and diag.get("audio_file_path"):
                transcript_text = transcribe_with_whisper(diag["audio_file_path"], diag)
                if transcript_text and len(transcript_text) > 50:
                    log.info("[YT-TRANSCRIPT:%s] ✓ Whisper fallback succeeded — %d chars", request_id, len(transcript_text))
                    log.info("=" * 70)
                    return jsonify({"ok": True, "transcript_text": transcript_text, "source": "whisper"}), 200
                else:
                    log.warning("[YT-TRANSCRIPT:%s] Whisper produced empty/short transcript", request_id)
            else:
                log.warning("[YT-TRANSCRIPT:%s] yt-dlp audio download failed", request_id)

        except Exception as whisper_exc:
            log.error("[YT-TRANSCRIPT:%s] Whisper fallback threw: %s", request_id, whisper_exc)
        finally:
            if workspace:
                cleanup_temp_workspace(workspace)
    else:
        log.warning("[YT-TRANSCRIPT:%s] Whisper fallback unavailable — yt_dlp=%s whisper=%s", request_id, yt_dlp_available, whisper_available)

    log.error("[YT-TRANSCRIPT:%s] All transcript extraction methods failed. Last error: %s", request_id, api_error)
    log.info("=" * 70)
    return jsonify({"ok": False, "error": "No captions available"}), 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 11 — Route: POST /api/youtube-ingest
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/youtube-ingest", methods=["POST"])
def youtube_ingest():
    """Full YouTube media ingestion pipeline."""
    request_id = "req_%d" % int(time.time() * 1000)
    log.info("=" * 70)
    log.info("[INGEST:%s] POST /api/youtube-ingest received", request_id)

    body        = request.get_json(silent=True) or {}
    youtube_url = (body.get("youtube_url") or "").strip()

    if not youtube_url:
        return jsonify({"success": False, "error": "youtube_url is required"}), 400

    if not any(x in youtube_url for x in ["youtube.com", "youtu.be"]):
        return jsonify({"success": False, "error": "Not a valid YouTube URL: %s" % youtube_url}), 400

    diag = {
        "request_id":                   request_id,
        "timestamp":                    datetime.utcnow().isoformat() + "Z",
        "youtube_url":                  youtube_url,
        "container_checks":             CONTAINER_STATUS,
        "ytdlp_attempted":              False,
        "ytdlp_success":                False,
        "ytdlp_error":                  None,
        "ytdlp_returncode":             None,
        "ytdlp_elapsed_s":              None,
        "ytdlp_stderr_tail":            "",
        "ytdlp_stdout_tail":            "",
        "audio_file_path":              None,
        "audio_size_bytes":             0,
        "audio_size_mb":                0.0,
        "ffmpeg_attempted":             False,
        "ffmpeg_success":               False,
        "ffmpeg_error":                 None,
        "ffmpeg_returncode":            None,
        "ffmpeg_elapsed_s":             None,
        "ffmpeg_stderr_tail":           "",
        "ffmpeg_frames_on_disk":        0,
        "frames_extracted":             0,
        "whisper_attempted":            False,
        "whisper_success":              False,
        "whisper_char_count":           0,
        "whisper_error":                None,
        "whisper_elapsed_s":            None,
        "whisper_model":                WHISPER_MODEL,
        "claude_attempted":             False,
        "claude_success":               False,
        "claude_has_transcript":        False,
        "claude_has_frames":            False,
        "claude_transcript_chars_sent": 0,
        "claude_frames_sent":           0,
        "claude_response_chars":        0,
        "claude_error":                 None,
        "claude_elapsed_s":             None,
        "meta_fetched":                 False,
    }

    stages = {
        "url_validated":       "done",
        "captions_attempted":  "pending",
        "audio_extracted":     "pending",
        "whisper_transcribed": "pending",
        "frames_extracted":    "pending",
        "claude_analysis":     "pending",
        "strategy_built":      "pending",
    }

    errors    = []
    workspace = None

    try:
        video_id_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{10,12})", youtube_url)
        video_id       = video_id_match.group(1) if video_id_match else "unknown"

        workspace  = create_temp_workspace(video_id)
        video_meta = fetch_video_metadata(youtube_url, diag)

        # ── Try RapidAPI captions first ───────────────────────────────────────
        stages["captions_attempted"] = "active"
        transcript        = ""
        transcript_source = "none"

        rapidapi_transcript, _ = fetch_transcript_via_rapidapi(youtube_url, video_id, request_id)
        if rapidapi_transcript:
            transcript        = rapidapi_transcript
            transcript_source = "rapidapi"
            stages["captions_attempted"]  = "done"
            stages["whisper_transcribed"] = "skipped"
            diag["whisper_char_count"]    = len(transcript)
            log.info("[INGEST:%s] ✓ RapidAPI captions: %d chars", request_id, len(transcript))
        else:
            stages["captions_attempted"] = "error"

            # ── yt-dlp audio download ─────────────────────────────────────────
            stages["audio_extracted"] = "active"
            audio_path = os.path.join(workspace, "audio_%s.mp3" % video_id)
            ytdlp_ok   = download_audio_ytdlp(youtube_url, audio_path, diag)

            if ytdlp_ok:
                stages["audio_extracted"] = "done"
            else:
                stages["audio_extracted"] = "error"
                errors.append("yt-dlp failed: %s" % diag.get("ytdlp_error", "unknown"))

            # ── Whisper transcription ─────────────────────────────────────────
            if ytdlp_ok and diag.get("audio_file_path"):
                stages["whisper_transcribed"] = "active"
                transcript = transcribe_with_whisper(diag["audio_file_path"], diag)
                if diag["whisper_success"] and diag["whisper_char_count"] > 0:
                    stages["whisper_transcribed"] = "done"
                    transcript_source = "whisper"
                else:
                    stages["whisper_transcribed"] = "error"
                    errors.append("Whisper failed: %s" % diag.get("whisper_error", "empty transcript"))
            else:
                stages["whisper_transcribed"] = "skipped"

        # ── ffmpeg frame extraction ───────────────────────────────────────────
        stages["frames_extracted"] = "active"
        frames_dir = os.path.join(workspace, "frames")
        frames     = extract_frames_ffmpeg(audio_path=diag.get("audio_file_path", ""), video_url=youtube_url, frames_dir=frames_dir, diag=diag)

        if len(frames) > 0:
            stages["frames_extracted"] = "done"
        else:
            stages["frames_extracted"] = "error"
            errors.append("ffmpeg frame extraction failed: %s" % diag.get("ffmpeg_error", "no frames"))

        transcript_char_count  = len(transcript)
        extracted_frames_count = len(frames)

        if transcript_char_count == 0 and extracted_frames_count == 0:
            log.error("[INGEST:%s] BLOCKED — no real media content", request_id)
            cleanup_temp_workspace(workspace)
            return jsonify({
                "success": False, "source": "url-context-fallback", "blocked": True,
                "block_reason": "yt-dlp and ffmpeg both failed. yt-dlp error: %s. ffmpeg error: %s." % (diag.get("ytdlp_error", "unknown"), diag.get("ffmpeg_error", "unknown")),
                "transcript": "", "transcript_source": "none", "transcript_char_count": 0,
                "visual_analysis": "", "frames": [], "frame_source": "none", "frame_count": 0,
                "video_meta": video_meta, "stages": stages, "errors": errors, "diagnostics": diag,
            }), 200

        # ── Claude analysis ───────────────────────────────────────────────────
        stages["claude_analysis"] = "active"
        visual_analysis = analyze_with_claude(transcript, frames, video_meta, diag)

        if diag["claude_success"]:
            stages["claude_analysis"] = "done"
        else:
            stages["claude_analysis"] = "error"
            errors.append("Claude failed: %s" % diag.get("claude_error", "unknown"))

        stages["strategy_built"] = "done"
        source = "native-pipeline" if (transcript_char_count > 500 or extracted_frames_count > 0) else "url-context-fallback"

        log.info("[INGEST:%s] ✓ Pipeline complete — source=%s, transcript=%d chars, frames=%d, analysis=%d chars", request_id, source, transcript_char_count, extracted_frames_count, len(visual_analysis))
        log.info("=" * 70)

        return jsonify({
            "success": True, "source": source,
            "transcript": transcript, "transcript_source": transcript_source, "transcript_char_count": transcript_char_count,
            "visual_analysis": visual_analysis, "frames": frames, "frame_source": "ffmpeg" if len(frames) > 0 else "none", "frame_count": len(frames),
            "video_meta": video_meta, "stages": stages, "errors": errors, "diagnostics": diag,
            "blocked": False, "block_reason": None,
        }), 200

    except Exception as exc:
        log.error("[INGEST:%s] Unhandled exception: %s\n%s", request_id, exc, traceback.format_exc())
        if workspace:
            cleanup_temp_workspace(workspace)
        return jsonify({
            "success": False, "source": "url-context-fallback", "blocked": True,
            "block_reason": "Internal server error: %s" % str(exc),
            "error": str(exc), "diagnostics": diag, "stages": stages, "errors": errors + [str(exc)],
        }), 500

    finally:
        if workspace and os.path.exists(workspace):
            cleanup_temp_workspace(workspace)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 12 — Route: POST /api/chat-completion (Knowledge Analyzer / Claude)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/chat-completion", methods=["POST"])
def chat_completion():
    """Server-side Anthropic/OpenAI proxy — replaces legacy AWS Lambda chat completion."""
    request_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    log.info("[CHAT-COMPLETION:%s] POST /api/chat-completion", request_id)

    body = request.get_json(silent=True) or {}
    result, status = handle_chat_completion_request(
        body,
        anthropic_api_key=ANTHROPIC_API_KEY,
        anthropic_model=ANTHROPIC_MODEL,
        openai_api_key=OPENAI_API_KEY,
    )
    return jsonify(result), status


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — Route: GET /api/video-health
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/video-health", methods=["GET"])
def video_health():
    """Lightweight health check for the video analyzer microservice."""
    log.info("[VIDEO-HEALTH] GET /api/video-health")

    yt_dlp_check  = check_binary("yt-dlp")
    ffmpeg_check  = check_binary("ffmpeg")
    anthropic_key = bool(ANTHROPIC_API_KEY)
    rapidapi_key  = bool(RAPIDAPI_KEY)

    all_ok = yt_dlp_check["available"] and ffmpeg_check["available"]

    status = {
        "ok":                    all_ok,
        "service":               SERVICE_NAME,
        "version":               BUILD_VERSION,
        "build_date":            BUILD_DATE,
        "market_scanning":       False,
        "twelvedata_enabled":    False,
        "paper_trading":         False,
        "trade_lifecycle":       False,
        "signal_scanning":       False,
        "yt_dlp_available":      yt_dlp_check["available"],
        "ffmpeg_available":      ffmpeg_check["available"],
        "anthropic_key_present": anthropic_key,
        "rapidapi_key_present":  rapidapi_key,
        "supabase_url_present":  bool(SUPABASE_URL),
        "timestamp":             datetime.utcnow().isoformat() + "Z",
    }

    log.info("[VIDEO-HEALTH] ok=%s, version=%s", all_ok, BUILD_VERSION)
    return jsonify(status), 200 if all_ok else 503


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 13 — Route: GET /
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def root():
    """Service identity — confirms this is the video analyzer microservice."""
    routes = [str(r.rule) for r in app.url_map.iter_rules()]
    return jsonify({
        "service":           SERVICE_NAME,
        "service_type":      "video-analyzer",
        "version":           BUILD_VERSION,
        "build_date":        BUILD_DATE,
        "registered_routes": routes,
        "disabled": [
            "market_scanning",
            "twelvedata_fetch",
            "paper_trading",
            "trade_lifecycle",
            "signal_scanning",
            "readiness_scoring",
            "scan_markets",
            "tradeplan",
        ],
        "enabled": [
            "GET /",
            "GET /api/video-health",
            "POST /api/extract-youtube-transcript",
            "POST /api/youtube-ingest",
            "POST /api/chat-completion",
        ],
    }), 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 14 — Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info("[STARTUP] %s starting on port %d", SERVICE_NAME, port)
    app.run(host="0.0.0.0", port=port, debug=False)
