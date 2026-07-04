"""Flask routes for ARIA Executive v2."""

from __future__ import annotations

from flask import jsonify, request

from aria.chat import run_aria_chat
from aria.events import get_recent_events, ingest_event
from aria.integrations import INTEGRATION_STATUS
from aria.prompt import build_aria_system_prompt, build_context_summary_for_voice, build_full_context_for_voice
from aria.dispatcher import dispatch_action, get_registry_catalog, list_tools
from aria.reasoning.execute import execute_with_reasoning


def register_aria_routes(app):
    @app.route("/aria/chat", methods=["POST", "OPTIONS"])
    def aria_chat():
        if request.method == "OPTIONS":
            return "", 204

        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        history = body.get("history") or []
        context = body.get("context") or {}
        permissions = body.get("permissions") or {
            "execute_trades": False,
            "external_actions": False,
            "send_notifications": False,
        }

        try:
            result = run_aria_chat(
                message,
                history,
                context,
                permissions,
                max_tokens=int(body.get("max_tokens") or 600),
                temperature=float(body.get("temperature") or 0.7),
            )
            return jsonify(result), 200
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503
        except Exception as exc:
            return jsonify({"error": f"ARIA chat failed: {exc}"}), 500

    @app.route("/aria/tools", methods=["GET", "OPTIONS"])
    def aria_tools_list():
        if request.method == "OPTIONS":
            return "", 204
        return jsonify({"tools": list_tools()}), 200

    @app.route("/aria/registry", methods=["GET", "OPTIONS"])
    def aria_registry():
        """Full action catalog for dynamic discovery at startup."""
        if request.method == "OPTIONS":
            return "", 204
        return jsonify(get_registry_catalog()), 200

    @app.route("/aria/actions/execute", methods=["POST", "OPTIONS"])
    def aria_actions_execute():
        """Universal action dispatcher endpoint (alias of /aria/tools/execute)."""
        if request.method == "OPTIONS":
            return "", 204
        body = request.get_json(silent=True) or {}
        action_name = (body.get("action") or body.get("tool") or body.get("name") or "").strip()
        if not action_name:
            return jsonify({"error": "action name is required"}), 400
        arguments = body.get("arguments") or body.get("input") or {}
        context = body.get("context") or {}
        permissions = body.get("permissions") or {
            "execute_trades": False,
            "external_actions": False,
            "send_notifications": False,
        }
        try:
            result = execute_with_reasoning(
                action_name,
                arguments,
                context,
                permissions,
                user_message=body.get("user_message"),
                history=body.get("history"),
            )
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({"error": f"Action execution failed: {exc}"}), 500

    @app.route("/aria/reasoning/execute", methods=["POST", "OPTIONS"])
    def aria_reasoning_execute():
        """Explicit reasoning-layer action execution (same as /aria/actions/execute)."""
        if request.method == "OPTIONS":
            return "", 204
        body = request.get_json(silent=True) or {}
        action_name = (body.get("action") or body.get("tool") or body.get("name") or "").strip()
        if not action_name:
            return jsonify({"error": "action name is required"}), 400
        arguments = body.get("arguments") or body.get("input") or {}
        context = body.get("context") or {}
        permissions = body.get("permissions") or {
            "execute_trades": False,
            "external_actions": False,
            "send_notifications": False,
        }
        try:
            result = execute_with_reasoning(
                action_name,
                arguments,
                context,
                permissions,
                user_message=body.get("user_message"),
                history=body.get("history"),
            )
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({"error": f"Reasoning execution failed: {exc}"}), 500

    @app.route("/aria/tools/execute", methods=["POST", "OPTIONS"])
    def aria_tools_execute():
        if request.method == "OPTIONS":
            return "", 204

        body = request.get_json(silent=True) or {}
        tool_name = (body.get("tool") or body.get("name") or "").strip()
        if not tool_name:
            return jsonify({"error": "tool name is required"}), 400

        arguments = body.get("arguments") or body.get("input") or {}
        context = body.get("context") or {}
        permissions = body.get("permissions") or {
            "execute_trades": False,
            "external_actions": False,
            "send_notifications": False,
        }

        try:
            result = execute_with_reasoning(
                tool_name,
                arguments,
                context,
                permissions,
                user_message=body.get("user_message"),
                history=body.get("history"),
            )
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({"error": f"Tool execution failed: {exc}"}), 500

    @app.route("/aria/context/prompt", methods=["POST", "OPTIONS"])
    def aria_context_prompt():
        """Build unified system prompt + voice summary from client context snapshot."""
        if request.method == "OPTIONS":
            return "", 204

        body = request.get_json(silent=True) or {}
        context = body.get("context") or {}

        return jsonify(
            {
                "system_prompt": build_aria_system_prompt(context),
                "voice_summary": build_context_summary_for_voice(context),
                "voice_context": build_full_context_for_voice(context),
            }
        ), 200

    @app.route("/aria/events/ingest", methods=["POST", "OPTIONS"])
    def aria_events_ingest():
        if request.method == "OPTIONS":
            return "", 204
        body = request.get_json(silent=True) or {}
        event_type = (body.get("type") or body.get("event_type") or "").strip()
        if not event_type:
            return jsonify({"error": "type is required"}), 400
        event = ingest_event(
            event_type,
            body.get("payload") or body.get("data") or {},
            source=body.get("source") or "frontend",
            user_id=body.get("user_id"),
        )
        return jsonify({"event": event, "deduplicated": event is None}), 200

    @app.route("/aria/events/recent", methods=["GET", "OPTIONS"])
    def aria_events_recent():
        if request.method == "OPTIONS":
            return "", 204
        since = request.args.get("since", type=float)
        limit = request.args.get("limit", default=20, type=int)
        user_id = request.args.get("user_id")
        events = get_recent_events(since=since, limit=limit, user_id=user_id)
        return jsonify({"events": events}), 200

    @app.route("/aria/integrations", methods=["GET", "OPTIONS"])
    def aria_integrations_catalog():
        if request.method == "OPTIONS":
            return "", 204
        return jsonify({"integrations": INTEGRATION_STATUS}), 200
