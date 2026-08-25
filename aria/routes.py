"""Flask routes for ARIA Executive v2 — JWT-bound tenant isolation."""

from __future__ import annotations

from flask import jsonify, request

from aria.auth import (
    reject_identity_spoof,
    require_authenticated_user,
    resolve_aria_permissions,
    sanitize_aria_context,
)
from aria.chat import run_aria_chat
from aria.events import get_recent_events, ingest_event
from aria.integrations import INTEGRATION_STATUS
from aria.prompt import (
    build_aria_system_prompt,
    build_context_summary_for_voice,
    build_full_context_for_voice,
)
from aria.dispatcher import get_registry_catalog, list_tools
from aria.reasoning.execute import execute_with_reasoning


def _private_auth(body: dict | None = None):
    """Return (user_id, auth_header) or Flask error tuple."""
    result = require_authenticated_user()
    if isinstance(result[1], tuple):
        # (None, (response, status))
        return result
    user_id, auth_header = result
    spoof = reject_identity_spoof(user_id, body)
    if spoof:
        return None, spoof
    return user_id, auth_header


def register_aria_routes(app):
    @app.route("/aria/chat", methods=["POST", "OPTIONS"])
    def aria_chat():
        if request.method == "OPTIONS":
            return "", 204

        body = request.get_json(silent=True) or {}
        auth = _private_auth(body)
        if auth[0] is None:
            return auth[1]
        user_id, auth_header = auth

        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        history = body.get("history") or []
        context = sanitize_aria_context(body.get("context") or {}, user_id)
        # Permissions from server profile — ignore client claims for execution
        permissions = resolve_aria_permissions(
            auth_header, user_id, body.get("permissions")
        )

        try:
            result = run_aria_chat(
                message,
                history,
                context,
                permissions,
                max_tokens=int(body.get("max_tokens") or 600),
                temperature=float(body.get("temperature") or 0.7),
                user_id=user_id,
                auth_header=auth_header,
            )
            result["authenticated_user_id"] = user_id
            return jsonify(result), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503
        except Exception as exc:
            return jsonify({"error": f"ARIA chat failed: {exc}"}), 500

    @app.route("/aria/tools", methods=["GET", "OPTIONS"])
    def aria_tools_list():
        if request.method == "OPTIONS":
            return "", 204
        auth = _private_auth()
        if auth[0] is None:
            return auth[1]
        return jsonify({"tools": list_tools()}), 200

    @app.route("/aria/registry", methods=["GET", "OPTIONS"])
    def aria_registry():
        if request.method == "OPTIONS":
            return "", 204
        auth = _private_auth()
        if auth[0] is None:
            return auth[1]
        return jsonify(get_registry_catalog()), 200

    def _execute_action_endpoint():
        body = request.get_json(silent=True) or {}
        auth = _private_auth(body)
        if auth[0] is None:
            return auth[1]
        user_id, auth_header = auth

        action_name = (
            body.get("action") or body.get("tool") or body.get("name") or ""
        ).strip()
        if not action_name:
            return jsonify({"error": "action name is required"}), 400

        arguments = body.get("arguments") or body.get("input") or {}
        context = sanitize_aria_context(body.get("context") or {}, user_id)
        permissions = resolve_aria_permissions(
            auth_header, user_id, body.get("permissions")
        )
        try:
            result = execute_with_reasoning(
                action_name,
                arguments,
                context,
                permissions,
                user_message=body.get("user_message"),
                history=body.get("history"),
                user_id=user_id,
                auth_header=auth_header,
            )
            result["authenticated_user_id"] = user_id
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({"error": f"Action execution failed: {exc}"}), 500

    @app.route("/aria/actions/execute", methods=["POST", "OPTIONS"])
    def aria_actions_execute():
        if request.method == "OPTIONS":
            return "", 204
        return _execute_action_endpoint()

    @app.route("/aria/reasoning/execute", methods=["POST", "OPTIONS"])
    def aria_reasoning_execute():
        if request.method == "OPTIONS":
            return "", 204
        return _execute_action_endpoint()

    @app.route("/aria/tools/execute", methods=["POST", "OPTIONS"])
    def aria_tools_execute():
        if request.method == "OPTIONS":
            return "", 204
        return _execute_action_endpoint()

    @app.route("/aria/context/prompt", methods=["POST", "OPTIONS"])
    def aria_context_prompt():
        if request.method == "OPTIONS":
            return "", 204
        body = request.get_json(silent=True) or {}
        auth = _private_auth(body)
        if auth[0] is None:
            return auth[1]
        user_id, _auth_header = auth
        context = sanitize_aria_context(body.get("context") or {}, user_id)
        return jsonify(
            {
                "system_prompt": build_aria_system_prompt(context),
                "voice_summary": build_context_summary_for_voice(context),
                "voice_context": build_full_context_for_voice(context),
                "authenticated_user_id": user_id,
            }
        ), 200

    @app.route("/aria/events/ingest", methods=["POST", "OPTIONS"])
    def aria_events_ingest():
        if request.method == "OPTIONS":
            return "", 204
        body = request.get_json(silent=True) or {}
        auth = _private_auth(body)
        if auth[0] is None:
            return auth[1]
        user_id, _auth_header = auth
        event_type = (body.get("type") or body.get("event_type") or "").strip()
        if not event_type:
            return jsonify({"error": "type is required"}), 400
        event = ingest_event(
            event_type,
            body.get("payload") or body.get("data") or {},
            source=body.get("source") or "frontend",
            user_id=user_id,
        )
        return jsonify({"event": event, "deduplicated": event is None}), 200

    @app.route("/aria/events/recent", methods=["GET", "OPTIONS"])
    def aria_events_recent():
        if request.method == "OPTIONS":
            return "", 204
        auth = _private_auth()
        if auth[0] is None:
            return auth[1]
        user_id, _auth_header = auth
        claimed = request.args.get("user_id")
        if claimed and str(claimed) != str(user_id):
            return jsonify({
                "error": "Forbidden",
                "reason": "identity_mismatch",
            }), 403
        since = request.args.get("since", type=float)
        limit = request.args.get("limit", default=20, type=int)
        events = get_recent_events(since=since, limit=limit, user_id=user_id)
        return jsonify({"events": events}), 200

    @app.route("/aria/integrations", methods=["GET", "OPTIONS"])
    def aria_integrations_catalog():
        if request.method == "OPTIONS":
            return "", 204
        auth = _private_auth()
        if auth[0] is None:
            return auth[1]
        return jsonify({"integrations": INTEGRATION_STATUS}), 200
