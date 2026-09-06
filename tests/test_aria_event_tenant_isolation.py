"""Local tests: ARIA in-memory event bus tenant isolation.

No deploy. No network auth required for unit bus tests.
Route tests mock JWT verification only.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure backend root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aria.events import (  # noqa: E402
    EventIngestRejected,
    SCOPE_GLOBAL,
    SCOPE_USER,
    get_recent_events,
    ingest_event,
    reset_event_bus_for_tests,
)
from aria.monitor import (  # noqa: E402
    hook_api_failure,
    hook_backend_notification,
    hook_broker_status,
)


USER_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class EventBusTenantIsolationTests(unittest.TestCase):
    def setUp(self):
        reset_event_bus_for_tests()

    def tearDown(self):
        reset_event_bus_for_tests()

    def test_user_a_event_visible_to_a(self):
        ev = ingest_event("new_signal", {"market": "NASDAQ", "signal": "BUY"}, user_id=USER_A, scope=SCOPE_USER)
        self.assertIsNotNone(ev)
        recent = get_recent_events(user_id=USER_A)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["user_id"], USER_A)

    def test_user_a_event_invisible_to_b(self):
        ingest_event("trade_opened", {"symbol": "QQQ", "side": "BUY", "strategy": "s114"}, user_id=USER_A, scope=SCOPE_USER)
        recent_b = get_recent_events(user_id=USER_B)
        self.assertEqual(recent_b, [])

    def test_user_b_event_invisible_to_a(self):
        ingest_event("trade_closed", {"symbol": "SPY", "pnl": "-1"}, user_id=USER_B, scope=SCOPE_USER)
        recent_a = get_recent_events(user_id=USER_A)
        self.assertEqual(recent_a, [])

    def test_null_tenant_event_rejected(self):
        with self.assertRaises(EventIngestRejected) as ctx:
            ingest_event("new_signal", {"market": "GOLD"}, user_id=None, scope=SCOPE_USER)
        self.assertEqual(ctx.exception.reason, "tenant_event_null_user_rejected")
        self.assertEqual(get_recent_events(user_id=USER_A), [])

    def test_empty_user_tenant_event_rejected(self):
        with self.assertRaises(EventIngestRejected):
            ingest_event("alert_triggered", {"title": "x"}, user_id="  ", scope=SCOPE_USER)

    def test_global_safe_event_visible_to_a_and_b(self):
        ev = ingest_event(
            "market_news_updated",
            {"market": "NASDAQ", "headline": "Fed speaks"},
            scope=SCOPE_GLOBAL,
        )
        self.assertIsNotNone(ev)
        self.assertIsNone(ev["user_id"])
        self.assertEqual(ev["scope"], SCOPE_GLOBAL)
        a = get_recent_events(user_id=USER_A)
        b = get_recent_events(user_id=USER_B)
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertEqual(a[0]["type"], "market_news_updated")

    def test_private_payload_marked_global_rejected(self):
        with self.assertRaises(EventIngestRejected) as ctx:
            ingest_event(
                "api_failure",
                {"service": "flask", "message": "down", "pnl": 12.5},
                scope=SCOPE_GLOBAL,
            )
        self.assertTrue(ctx.exception.reason.startswith("private_payload_on_global_event"))
        self.assertEqual(get_recent_events(user_id=USER_A), [])

    def test_broker_global_rejected(self):
        with self.assertRaises(EventIngestRejected):
            ingest_event(
                "api_failure",
                {"service": "flask", "message": "x", "broker": "alpaca"},
                scope=SCOPE_GLOBAL,
            )

    def test_non_allowlisted_global_type_rejected(self):
        with self.assertRaises(EventIngestRejected) as ctx:
            ingest_event("new_signal", {"market": "NASDAQ"}, scope=SCOPE_GLOBAL, user_id=USER_A)
        self.assertEqual(ctx.exception.reason, "global_event_type_not_allowlisted")

    def test_unknown_scope_rejected(self):
        with self.assertRaises(EventIngestRejected) as ctx:
            ingest_event("api_failure", {"service": "x", "message": "y"}, scope="team")
        self.assertEqual(ctx.exception.reason, "unknown_event_scope")

    def test_read_without_user_fails_closed(self):
        with self.assertRaises(EventIngestRejected):
            get_recent_events(user_id=None)

    def test_concurrent_ab_no_cross_tenant_leak(self):
        errors: list[str] = []

        def writer(uid: str, n: int):
            try:
                for i in range(n):
                    ingest_event(
                        "risk_warning",
                        {"message": f"{uid}-{i}"},
                        user_id=uid,
                        scope=SCOPE_USER,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [
            threading.Thread(target=writer, args=(USER_A, 40)),
            threading.Thread(target=writer, args=(USER_B, 40)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        a = get_recent_events(user_id=USER_A, limit=100)
        b = get_recent_events(user_id=USER_B, limit=100)
        self.assertTrue(all(e["user_id"] == USER_A for e in a))
        self.assertTrue(all(e["user_id"] == USER_B for e in b))
        self.assertFalse(any(e["user_id"] == USER_B for e in a))
        self.assertFalse(any(e["user_id"] == USER_A for e in b))

    def test_monitor_notification_without_user_is_invalid_unscoped(self):
        hook_backend_notification({"type": "alert_triggered", "title": "no user"})
        self.assertEqual(get_recent_events(user_id=USER_A), [])

    def test_monitor_notification_with_user_scoped(self):
        hook_backend_notification({
            "type": "alert_triggered",
            "title": "ok",
            "user_id": USER_A,
        })
        recent = get_recent_events(user_id=USER_A)
        self.assertEqual(len(recent), 1)
        self.assertEqual(get_recent_events(user_id=USER_B), [])

    def test_monitor_api_failure_global_safe(self):
        hook_api_failure("candle_feed", "timeout")
        self.assertEqual(len(get_recent_events(user_id=USER_A)), 1)
        self.assertEqual(len(get_recent_events(user_id=USER_B)), 1)

    def test_monitor_broker_requires_user(self):
        hook_broker_status(True, broker="alpaca")  # missing user → rejected
        self.assertEqual(get_recent_events(user_id=USER_A), [])
        hook_broker_status(True, broker="alpaca", user_id=USER_A)
        self.assertEqual(len(get_recent_events(user_id=USER_A)), 1)
        self.assertEqual(get_recent_events(user_id=USER_B), [])


class AriaEventsRouteIsolationTests(unittest.TestCase):
    def setUp(self):
        reset_event_bus_for_tests()
        from flask import Flask
        from aria.routes import register_aria_routes

        self.flask = Flask("aria_event_isolation_test")
        register_aria_routes(self.flask)
        self.client = self.flask.test_client()

    def tearDown(self):
        reset_event_bus_for_tests()

    def _auth_as(self, user_id: str):
        return patch(
            "aria.auth.get_user_id_from_request",
            return_value=(user_id, None),
        )

    def _auth_fail(self, reason: str = "invalid_or_expired_token"):
        return patch(
            "aria.auth.get_user_id_from_request",
            return_value=(None, reason),
        )

    def test_recent_missing_jwt_rejected(self):
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_fail("missing_bearer_token"):
            res = self.client.get("/aria/events/recent")
        self.assertEqual(res.status_code, 401)

    def test_recent_invalid_jwt_rejected(self):
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_fail("invalid_or_expired_token"):
            res = self.client.get(
                "/aria/events/recent",
                headers={"Authorization": "Bearer invalid.token"},
            )
        self.assertEqual(res.status_code, 401)

    def test_recent_body_query_mismatch_fail_closed(self):
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_as(USER_A):
            res = self.client.get(
                f"/aria/events/recent?user_id={USER_B}",
                headers={"Authorization": "Bearer fake-a"},
            )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json().get("reason"), "identity_mismatch")

    def test_recent_exact_tenant_isolation(self):
        ingest_event("new_signal", {"market": "NASDAQ", "signal": "BUY"}, user_id=USER_A, scope=SCOPE_USER)
        ingest_event("new_signal", {"market": "GOLD", "signal": "SELL"}, user_id=USER_B, scope=SCOPE_USER)
        ingest_event(
            "high_impact_event",
            {"headline": "CPI", "market": "NASDAQ"},
            scope=SCOPE_GLOBAL,
        )
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_as(USER_A):
            res = self.client.get(
                "/aria/events/recent",
                headers={"Authorization": "Bearer fake-a"},
            )
        self.assertEqual(res.status_code, 200)
        events = res.get_json()["events"]
        owners = {e.get("user_id") for e in events}
        self.assertIn(USER_A, owners)
        self.assertNotIn(USER_B, owners)
        self.assertTrue(any(e.get("scope") == SCOPE_GLOBAL for e in events))

    def test_ingest_uses_jwt_not_body_user(self):
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_as(USER_A):
            res = self.client.post(
                "/aria/events/ingest",
                json={
                    "type": "alert_triggered",
                    "payload": {"title": "hi"},
                    "user_id": USER_A,
                    "scope": "user",
                },
                headers={"Authorization": "Bearer fake-a"},
            )
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["event"]["user_id"], USER_A)

    def test_ingest_mismatch_fail_closed(self):
        with patch("aria.auth.supabase_auth_configured", return_value=True), self._auth_as(USER_A):
            res = self.client.post(
                "/aria/events/ingest",
                json={
                    "type": "alert_triggered",
                    "payload": {"title": "spoof"},
                    "user_id": USER_B,
                },
                headers={"Authorization": "Bearer fake-a"},
            )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(get_recent_events(user_id=USER_B), [])
        self.assertEqual(get_recent_events(user_id=USER_A), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
