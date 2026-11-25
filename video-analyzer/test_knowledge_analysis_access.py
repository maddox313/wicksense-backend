"""Authorization tests for the isolated Trading Knowledge Analyzer route."""
import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import supabase_auth
from supabase_auth import guard_analyzer_request, lookup_subscription_http

ELITE_USER = "11111111-1111-1111-1111-111111111111"
OTHER_USER = "22222222-2222-2222-2222-222222222222"
APP_SOURCE = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")


def allow_user(user_id):
    def lookup(_header):
        return user_id, None
    return lookup


def subscription(plan, status):
    def lookup(_header, queried_user_id):
        lookup.queried = queried_user_id
        return {"plan": plan, "status": status}, None
    lookup.queried = None
    return lookup


def route_calls(name):
    tree = ast.parse(APP_SOURCE)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    return [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


class KnowledgeAnalysisAccessTests(unittest.TestCase):
    def test_eligible_elite_subscriber(self):
        plans = subscription("elite", "active")
        user_id, denied = guard_analyzer_request(
            "Bearer elite-token",
            {"plan": "free", "status": "canceled", "messages": [{"role": "user", "content": "lesson"}]},
            lookup_user=allow_user(ELITE_USER),
            lookup_subscription=plans,
        )
        self.assertEqual(user_id, ELITE_USER)
        self.assertIsNone(denied)
        self.assertEqual(plans.queried, ELITE_USER)

    def test_eligible_elite_trial(self):
        for plan, status in (("elite", "trialing"), ("trial_elite", "active"), ("trial_elite", "trialing")):
            user_id, denied = guard_analyzer_request(
                "Bearer trial-token",
                {"plan": "elite", "status": "active"},
                lookup_user=allow_user(ELITE_USER),
                lookup_subscription=subscription(plan, status),
            )
            self.assertEqual(user_id, ELITE_USER, (plan, status))
            self.assertIsNone(denied, (plan, status))

    def test_missing_and_invalid_tokens_do_not_read_a_plan(self):
        def reject_lookup(_header, _user_id):
            raise AssertionError("plan lookup must not run")

        user_id, denied = guard_analyzer_request("", {"plan": "elite"}, lookup_subscription=reject_lookup)
        self.assertIsNone(user_id)
        payload, status = denied
        self.assertEqual(status, 401)
        self.assertEqual(payload["reason"], "missing_bearer_token")

        def invalid_user(_header):
            return None, "invalid_or_expired_token"

        user_id, denied = guard_analyzer_request(
            "Bearer not-a-user",
            {"user_id": OTHER_USER, "plan": "elite"},
            lookup_user=invalid_user,
            lookup_subscription=reject_lookup,
        )
        self.assertIsNone(user_id)
        payload, status = denied
        self.assertEqual(status, 401)
        self.assertEqual(payload["reason"], "invalid_or_expired_token")

    def test_free_tier_and_foreign_user_are_rejected(self):
        user_id, denied = guard_analyzer_request(
            "Bearer free-token",
            {"plan": "elite", "status": "active", "user_id": ELITE_USER},
            lookup_user=allow_user(ELITE_USER),
            lookup_subscription=subscription("free", "active"),
        )
        self.assertIsNone(user_id)
        payload, status = denied
        self.assertEqual(status, 403)
        self.assertEqual(payload["reason"], "plan_ineligible")

        plans = subscription("elite", "active")
        user_id, denied = guard_analyzer_request(
            "Bearer elite-token",
            {"user_id": OTHER_USER},
            lookup_user=allow_user(ELITE_USER),
            lookup_subscription=plans,
        )
        self.assertEqual(denied[1], 403)
        self.assertEqual(denied[0]["reason"], "identity_mismatch")
        self.assertIsNone(plans.queried)

    def test_plan_lookup_uses_anon_key_and_jwt_user_only(self):
        response = MagicMock(status_code=200)
        response.json.return_value = [{"plan": "elite", "status": "active"}]
        with patch.object(supabase_auth, "SUPABASE_URL", "https://jtxkiiajuafpsafnzzon.supabase.co"), \
             patch.object(supabase_auth, "SUPABASE_ANON_KEY", "anon-marker"), \
             patch.object(supabase_auth, "SUPABASE_SERVICE_ROLE_KEY", "service-role-marker"), \
             patch.object(supabase_auth.requests, "get", return_value=response) as get:
            row, reason = lookup_subscription_http("Bearer user-jwt", ELITE_USER)
        self.assertIsNone(reason)
        self.assertEqual(row["plan"], "elite")
        args, kwargs = get.call_args
        self.assertIn("/rest/v1/user_subscriptions", args[0])
        self.assertEqual(kwargs["params"]["id"], "eq.%s" % ELITE_USER)
        self.assertEqual(kwargs["headers"]["apikey"], "anon-marker")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer user-jwt")
        self.assertNotIn("service-role-marker", str(kwargs))

    def test_failed_plan_lookup_does_not_count_as_eligibility(self):
        user_id, denied = guard_analyzer_request(
            "Bearer elite-token",
            {"plan": "elite", "status": "active"},
            lookup_user=allow_user(ELITE_USER),
            lookup_subscription=lambda _header, _user_id: (None, "subscription_lookup_failed"),
        )
        self.assertIsNone(user_id)
        payload, status = denied
        self.assertEqual(status, 503)
        self.assertEqual(payload["reason"], "subscription_lookup_failed")

    def test_routes_isolate_analyzer_gate_from_shared_chat(self):
        knowledge = route_calls("knowledge_analysis")
        chat = route_calls("chat_completion")
        youtube = route_calls("youtube_ingest")
        transcript = route_calls("extract_youtube_transcript")

        def first_line(calls, name):
            return min(node.lineno for node in calls if node.func.id == name)

        self.assertLess(
            first_line(knowledge, "guard_analyzer_request"),
            first_line(knowledge, "handle_chat_completion_request"),
        )
        self.assertFalse(any(node.func.id == "guard_analyzer_request" for node in chat))
        self.assertIn("handle_chat_completion_request", [node.func.id for node in chat])
        self.assertLess(
            first_line(youtube, "guard_analyzer_request"),
            first_line(youtube, "fetch_transcript_via_rapidapi"),
        )
        self.assertLess(
            first_line(transcript, "guard_analyzer_request"),
            first_line(transcript, "fetch_transcript_via_rapidapi"),
        )
        self.assertNotIn("knowledge_base", APP_SOURCE)


if __name__ == "__main__":
    unittest.main()
