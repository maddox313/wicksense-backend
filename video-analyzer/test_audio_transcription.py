"""gpt-transcribe uses the audio endpoint and cannot run without an Elite session."""
import ast
import io
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

APP_SOURCE = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
ARIA_ROUTES = (Path(__file__).resolve().parents[1] / "aria" / "routes.py").read_text(encoding="utf-8")


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


class AudioTranscriptionTests(unittest.TestCase):
    def test_model_and_endpoint_are_gpt_transcribe(self):
        from audio_transcription import TRANSCRIBE_MODEL, TRANSCRIBE_URL, transcribe_with_gpt

        response = MagicMock(ok=True)
        response.json.return_value = {"text": "buy gold on the wick"}
        post = MagicMock(return_value=response)
        result, status = transcribe_with_gpt("test-key", wav_bytes(), "note.wav", requests_post=post)

        self.assertEqual(status, 200)
        self.assertEqual(result["transcript_text"], "buy gold on the wick")
        self.assertEqual(result["model"], "gpt-transcribe")
        url = post.call_args.args[0]
        self.assertEqual(url, TRANSCRIBE_URL)
        self.assertNotIn("chat/completions", url)
        self.assertEqual(post.call_args.kwargs["data"]["model"], TRANSCRIBE_MODEL)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_video_is_reduced_to_extracted_audio_before_upload(self):
        from audio_transcription import prepare_media_for_transcription

        def extract(source, dest):
            self.assertTrue(source.endswith(".mp4"))
            with open(dest, "wb") as handle:
                handle.write(b"extracted-audio")
            return True

        prepared, error = prepare_media_for_transcription(b"not-a-real-mp4", "lesson.mp4", extract_audio=extract)
        self.assertIsNone(error)
        self.assertEqual(prepared["bytes"], b"extracted-audio")
        self.assertEqual(prepared["filename"], "audio.mp3")

    def test_small_audio_file_is_sent_without_ffmpeg(self):
        from audio_transcription import prepare_media_for_transcription

        audio = wav_bytes()

        def extract(_source, _dest):
            raise AssertionError("ffmpeg should not run for a small wav")

        prepared, error = prepare_media_for_transcription(audio, "note.wav", extract_audio=extract)
        self.assertIsNone(error)
        self.assertEqual(prepared["bytes"], audio)

    def test_unauthorized_upload_does_not_call_openai(self):
        import app as video_app

        with patch.object(video_app, "transcribe_with_gpt") as transcribe:
            response = video_app.app.test_client().post(
                "/api/audio-transcription",
                data={"file": (io.BytesIO(wav_bytes()), "note.wav")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["reason"], "missing_bearer_token")
        transcribe.assert_not_called()

    def test_authorized_upload_transcribes_after_the_elite_gate(self):
        import app as video_app

        with patch.object(video_app, "guard_analyzer_request", return_value=("subscriber", None)), \
             patch.object(video_app, "prepare_media_for_transcription", return_value=({"bytes": b"audio", "filename": "audio.mp3"}, None)), \
             patch.object(video_app, "transcribe_with_gpt", return_value=({"ok": True, "transcript_text": "wick rejection", "model": "gpt-transcribe"}, 200)) as transcribe:
            response = video_app.app.test_client().post(
                "/api/audio-transcription",
                data={"file": (io.BytesIO(b"video-bytes"), "lesson.mp4")},
                headers={"Authorization": "Bearer elite"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transcript_text"], "wick rejection")
        transcribe.assert_called_once()
        self.assertNotIn("gpt-4o-audio-preview", APP_SOURCE)

    def test_signed_in_shared_chat_does_not_consult_the_elite_plan(self):
        from supabase_auth import guard_subscriber_session

        def allow_user(_header):
            return "subscriber-id", None

        user_id, denied = guard_subscriber_session("Bearer session", {}, lookup_user=allow_user)
        self.assertEqual(user_id, "subscriber-id")
        self.assertIsNone(denied)

    def test_aria_chat_still_requires_its_own_session_before_the_model(self):
        tree = ast.parse(ARIA_ROUTES)
        register = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_aria_routes")
        aria_chat = next(node for node in ast.walk(register) if isinstance(node, ast.FunctionDef) and node.name == "aria_chat")

        def line_of(name):
            return min(
                node.lineno
                for node in ast.walk(aria_chat)
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name
            )

        self.assertLess(line_of("_private_auth"), line_of("run_aria_chat"))
        auth_source = (Path(__file__).resolve().parents[1] / "aria" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("def require_authenticated_user", auth_source)
        self.assertLess(auth_source.index("def require_authenticated_user"), auth_source.index("def reject_identity_spoof"))


if __name__ == "__main__":
    unittest.main()
