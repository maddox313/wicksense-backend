"""Anthropic request parameters. Does not call the Anthropic API."""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from chat_completion import run_anthropic_completion


class AnthropicCompletionParameterTests(unittest.TestCase):
    def test_temperature_is_omitted_from_messages_create(self):
        captured = {}

        class FakeMessages:
            def create(self, **kwargs):
                if "temperature" in kwargs:
                    raise TypeError(
                        "Messages.create() got an unexpected keyword argument 'temperature'"
                    )
                captured.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(text="analysis")],
                    model=kwargs["model"],
                    stop_reason="end_turn",
                )

        class FakeAnthropic:
            def __init__(self, api_key):
                self.api_key = api_key
                self.messages = FakeMessages()

        fake_module = types.ModuleType("anthropic")
        fake_module.Anthropic = FakeAnthropic
        with patch.dict(sys.modules, {"anthropic": fake_module}):
            result, status = run_anthropic_completion(
                "test-key",
                "claude-3-5-sonnet-20241022",
                "claude-sonnet-4-6",
                [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": "Opening range breakout lesson."},
                ],
                {"max_tokens": 4096, "temperature": 0.3},
            )

        self.assertEqual(status, 200)
        self.assertEqual(captured["model"], "claude-sonnet-4-6")
        self.assertEqual(captured["max_tokens"], 4096)
        self.assertEqual(captured["system"], "Return JSON only.")
        self.assertNotIn("temperature", captured)
        self.assertEqual(result["choices"][0]["message"]["content"], "analysis")


if __name__ == "__main__":
    unittest.main()
