"""Elite-gated MP4 and audio transcription through OpenAI's audio endpoint."""

import os
import subprocess
import tempfile

import requests

TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
TRANSCRIBE_MODEL = "gpt-transcribe"
MAX_DIRECT_BYTES = 24 * 1024 * 1024
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
AUDIO_EXTENSIONS = {"flac", "mp3", "mpeg", "mpga", "m4a", "ogg", "wav"}
OPENAI_MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | {"mp4", "webm"}


def _extension(filename):
    name = (filename or "").rsplit(".", 1)
    if len(name) < 2:
        return ""
    return name[1].lower()


def extract_audio_ffmpeg(source_path, dest_path):
    """Extract a small mono audio track from a video or audio file."""
    command = [
        "ffmpeg", "-y", "-i", source_path,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        dest_path,
    ]
    completed = subprocess.run(command, capture_output=True, timeout=180)
    return completed.returncode == 0 and os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0


def prepare_media_for_transcription(file_bytes, filename, extract_audio=None):
    """
    Return (payload, error). Video is reduced to an audio file before upload.
    A file OpenAI already accepts is sent unchanged when it is within the direct limit
    and audio extraction is unavailable.
    """
    extract_audio = extract_audio or extract_audio_ffmpeg
    if not file_bytes:
        return None, "file is empty"
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return None, "file is too large to transcribe"
    extension = _extension(filename) or "wav"
    if extension in AUDIO_EXTENSIONS and len(file_bytes) <= MAX_DIRECT_BYTES:
        return {"bytes": file_bytes, "filename": "audio.%s" % extension}, None

    with tempfile.TemporaryDirectory(prefix="ws-transcribe-") as workspace:
        source = os.path.join(workspace, "source.%s" % (extension or "bin"))
        dest = os.path.join(workspace, "audio.mp3")
        with open(source, "wb") as handle:
            handle.write(file_bytes)
        extracted = False
        try:
            extracted = extract_audio(source, dest)
        except (OSError, subprocess.SubprocessError):
            extracted = False
        if extracted:
            with open(dest, "rb") as handle:
                audio = handle.read()
            if audio and len(audio) <= MAX_DIRECT_BYTES:
                return {"bytes": audio, "filename": "audio.mp3"}, None

    if extension in OPENAI_MEDIA_EXTENSIONS and len(file_bytes) <= MAX_DIRECT_BYTES:
        return {"bytes": file_bytes, "filename": "upload.%s" % extension}, None
    return None, "audio could not be extracted from this video"


def transcribe_with_gpt(api_key, file_bytes, filename, requests_post=None):
    """POST the audio file to /v1/audio/transcriptions. Never uses chat completions."""
    if not api_key:
        return {"ok": False, "error": "OPENAI API key is not configured"}, 503
    if not file_bytes:
        return {"ok": False, "error": "file is empty"}, 400

    post = requests_post or requests.post
    response = post(
        TRANSCRIBE_URL,
        headers={"Authorization": "Bearer %s" % api_key},
        files={"file": (filename or "audio.mp3", file_bytes)},
        data={"model": TRANSCRIBE_MODEL, "response_format": "json"},
        timeout=180,
    )
    if not response.ok:
        return {
            "ok": False,
            "error": "OPENAI transcription error: %s" % response.status_code,
            "details": (response.text or "")[:500],
        }, response.status_code

    body = response.json() or {}
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Transcription returned no text"}, 422
    return {
        "ok": True,
        "transcript_text": text,
        "model": TRANSCRIBE_MODEL,
        "source": "gpt-transcribe",
    }, 200
