"""Published YouTube captions. This does not download the video."""

import logging
import re

log = logging.getLogger("wicksense.video-analyzer.captions")

ENGLISH = ["en", "en-US", "en-GB"]


def _snippet_text(entry):
    if isinstance(entry, dict):
        text = entry.get("text") or ""
    else:
        text = getattr(entry, "text", "") or ""
    return re.sub(r"\s+", " ", str(text)).strip()


def fetch_published_youtube_captions(video_id, request_id, api_factory=None):
    """
    Read a caption track the video already publishes.
    Returns ({text, source}, None) or (None, error).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import CouldNotRetrieveTranscript, NoTranscriptFound
    except ImportError as exc:
        log.warning("[YT-CAPTION:%s] youtube-transcript-api is not installed: %s", request_id, exc)
        return None, "youtube-transcript-api is not installed"

    factory = api_factory or YouTubeTranscriptApi
    api = factory()
    try:
        listing = api.list(video_id)
    except CouldNotRetrieveTranscript as exc:
        log.info("[YT-CAPTION:%s] Caption list failed: %s", request_id, exc)
        return None, str(exc)
    except Exception as exc:
        log.info("[YT-CAPTION:%s] Caption list failed: %s", request_id, exc)
        return None, str(exc)

    selected = None
    source = "youtube-transcript-api"
    for finder, label in (
        ("find_manually_created_transcript", "youtube-transcript-api/manual"),
        ("find_generated_transcript", "youtube-transcript-api/auto"),
        ("find_transcript", "youtube-transcript-api"),
    ):
        try:
            selected = getattr(listing, finder)(ENGLISH)
            source = label
            break
        except NoTranscriptFound:
            continue

    if selected is None:
        tracks = list(listing)
        if not tracks:
            return None, "No published captions for this video"
        selected = tracks[0]
        source = "youtube-transcript-api/auto" if getattr(selected, "is_generated", False) else "youtube-transcript-api/manual"

    try:
        fetched = selected.fetch()
    except CouldNotRetrieveTranscript as exc:
        log.info("[YT-CAPTION:%s] Caption fetch failed: %s", request_id, exc)
        return None, str(exc)

    raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    transcript = " ".join(text for text in (_snippet_text(entry) for entry in raw) if text).strip()
    if len(transcript) < 20:
        return None, "Published captions were too short"
    log.info("[YT-CAPTION:%s] Published captions source=%s chars=%d", request_id, source, len(transcript))
    return {"text": transcript, "source": source}, None
