"""Published YouTube captions are returned without downloading the video."""
import unittest
from unittest.mock import MagicMock, patch


class FakeSnippet:
    def __init__(self, text):
        self.text = text


class FakeFetched:
    def __init__(self, texts):
        self._texts = texts

    def to_raw_data(self):
        return [{"text": text} for text in self._texts]


class FakeTranscript:
    def __init__(self, texts, generated=True):
        self.is_generated = generated
        self._texts = texts

    def fetch(self):
        return FakeFetched(self._texts)


class FakeListing:
    def __init__(self, transcript):
        self.transcript = transcript

    def find_manually_created_transcript(self, _languages):
        from youtube_transcript_api._errors import NoTranscriptFound
        raise NoTranscriptFound("video", [], {})

    def find_generated_transcript(self, _languages):
        return self.transcript

    def find_transcript(self, _languages):
        return self.transcript

    def __iter__(self):
        yield self.transcript


class FakeApi:
    def list(self, video_id):
        assert video_id == "DKohGRr18ZA"
        return FakeListing(FakeTranscript([
            "Buy gold when the lower wick rejects support.",
            "The candle must close bullish.",
        ]))


class YouTubeCaptionTests(unittest.TestCase):
    def test_published_english_captions_are_joined(self):
        from youtube_captions import fetch_published_youtube_captions

        result, error = fetch_published_youtube_captions("DKohGRr18ZA", "test", api_factory=FakeApi)
        self.assertIsNone(error)
        self.assertEqual(result["source"], "youtube-transcript-api/auto")
        self.assertIn("lower wick rejects support", result["text"])

    def test_extract_route_returns_captions_without_a_download(self):
        import app as video_app

        published = {"text": "Buy gold when the lower wick rejects support and closes bullish.", "source": "youtube-transcript-api/auto"}
        with patch.object(video_app, "guard_analyzer_request", return_value=("subscriber", None)), \
             patch.object(video_app, "fetch_transcript_via_rapidapi", return_value=(None, "RAPIDAPI_KEY not set")), \
             patch.object(video_app, "fetch_published_youtube_captions", return_value=(published, None)), \
             patch.object(video_app, "download_audio_ytdlp") as download, \
             patch.object(video_app, "transcribe_with_gpt") as transcribe:
            response = video_app.app.test_client().post(
                "/api/extract-youtube-transcript",
                json={"youtube_url": "https://www.youtube.com/watch?v=DKohGRr18ZA"},
                headers={"Authorization": "Bearer elite"},
            )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "youtube-transcript-api/auto")
        self.assertIn("lower wick", body["transcript_text"])
        download.assert_not_called()
        transcribe.assert_not_called()

    def test_missing_session_does_not_fetch_captions(self):
        import app as video_app

        with patch.object(video_app, "fetch_published_youtube_captions") as captions:
            response = video_app.app.test_client().post(
                "/api/extract-youtube-transcript",
                json={"youtube_url": "https://www.youtube.com/watch?v=DKohGRr18ZA"},
            )
        self.assertEqual(response.status_code, 401)
        captions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
