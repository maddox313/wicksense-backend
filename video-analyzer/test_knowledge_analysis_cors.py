"""CORS coverage for the staging Analyzer frontend. Does not call Claude."""
import ast
import unittest
from pathlib import Path

from flask import Flask
from flask_cors import CORS

APP_SOURCE = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
STAGING_ORIGIN = "https://wicksense-day-trader-pro-staging.onrender.com"


def cors_keywords():
    tree = ast.parse(APP_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CORS":
            return {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}
    raise AssertionError("CORS configuration missing")


def route_names(function_name):
    tree = ast.parse(APP_SOURCE)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


class KnowledgeAnalysisCorsTests(unittest.TestCase):
    def test_staging_frontend_preflight_allows_authorization(self):
        config = cors_keywords()
        self.assertIn(STAGING_ORIGIN, config["origins"])
        self.assertIn("Authorization", config["allow_headers"])
        self.assertIn("POST", config["methods"])
        self.assertIn("OPTIONS", config["methods"])

        app = Flask(__name__)
        CORS(app, **config)

        @app.route("/api/knowledge-analysis", methods=["POST"])
        def knowledge_analysis():
            return {"ok": True}

        @app.route("/api/chat-completion", methods=["POST"])
        def chat_completion():
            return {"ok": True}

        client = app.test_client()
        headers = {
            "Origin": STAGING_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        knowledge = client.options("/api/knowledge-analysis", headers=headers)
        chat = client.options("/api/chat-completion", headers=headers)
        blocked = client.options(
            "/api/knowledge-analysis",
            headers={**headers, "Origin": "https://example.invalid"},
        )

        self.assertEqual(knowledge.headers.get("Access-Control-Allow-Origin"), STAGING_ORIGIN)
        self.assertIn("authorization", knowledge.headers.get("Access-Control-Allow-Headers", "").lower())
        self.assertEqual(chat.headers.get("Access-Control-Allow-Origin"), STAGING_ORIGIN)
        self.assertIsNone(blocked.headers.get("Access-Control-Allow-Origin"))

    def test_shared_chat_route_remains_ungated(self):
        self.assertIn("guard_analyzer_request", route_names("knowledge_analysis"))
        self.assertNotIn("guard_analyzer_request", route_names("chat_completion"))
        self.assertIn("handle_chat_completion_request", route_names("chat_completion"))


if __name__ == "__main__":
    unittest.main()
