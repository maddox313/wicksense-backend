"""
WickSense server-side chat completion (replaces AWS Lambda).
Supports Anthropic + OpenAI via backend env keys — never exposed to the browser.
"""

import logging
import traceback

log = logging.getLogger("wicksense.chat-completion")


def _openai_style_response(content, model, finish_reason="stop"):
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content or ""},
                "finish_reason": finish_reason,
            }
        ],
        "model": model,
        "object": "chat.completion",
    }


def _split_system_messages(messages):
    """Extract system prompts and return Anthropic-compatible message list."""
    system_parts = []
    out = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content.strip())
            continue
        if role in ("user", "assistant"):
            out.append({"role": role, "content": content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def run_anthropic_completion(api_key, default_model, model, messages, parameters):
    import anthropic

    if not api_key:
        return {"error": "ANTHROPIC API key is not configured", "details": "Set ANTHROPIC_API_KEY on the backend service"}, 503

    system, msgs = _split_system_messages(messages)
    if not msgs:
        return {"error": "Invalid request: Messages array is required", "details": "No user/assistant messages"}, 400

    chosen_model = model or default_model
    kwargs = {
        "model": chosen_model,
        "max_tokens": int(parameters.get("max_tokens", 4096)),
        "messages": msgs,
    }
    if system:
        kwargs["system"] = system
    if parameters.get("temperature") is not None:
        kwargs["temperature"] = float(parameters["temperature"])

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(**kwargs)

    parts = []
    for block in response.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    content = "".join(parts)

    return _openai_style_response(content, response.model, response.stop_reason or "stop"), 200


def run_openai_completion(api_key, model, messages, parameters):
    import requests

    if not api_key:
        return {"error": "OPENAI API key is not configured", "details": "Set OPENAI_API_KEY on the backend service"}, 503

    if not messages:
        return {"error": "Invalid request: Messages array is required", "details": "No messages"}, 400

    payload = {
        "model": model or "gpt-4o-audio-preview",
        "messages": messages,
        "max_tokens": int(parameters.get("max_tokens", 4096)),
    }
    if parameters.get("temperature") is not None:
        payload["temperature"] = float(parameters["temperature"])

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )

    if not resp.ok:
        detail = resp.text[:500]
        log.error("[CHAT-COMPLETION] OpenAI HTTP %s: %s", resp.status_code, detail)
        return {
            "error": f"OPENAI API error: {resp.status_code}",
            "details": detail,
        }, resp.status_code

    return resp.json(), 200


def handle_chat_completion_request(body, anthropic_api_key, anthropic_model, openai_api_key):
    """
    Lambda-compatible chat completion handler.
    Request: { provider, model, messages, stream, parameters }
    """
    try:
        provider = (body.get("provider") or "").upper()
        model = body.get("model")
        messages = body.get("messages")
        parameters = body.get("parameters") or {}
        stream = body.get("stream") is True or body.get("stream") == "true"

        if stream:
            return {
                "error": "Streaming not supported on backend proxy",
                "details": "Use stream:false; client will receive full JSON response",
            }, 400

        if not messages or not isinstance(messages, list):
            return {
                "error": "Invalid request: Messages array is required",
                "details": "The request must include a non-empty messages array",
            }, 400

        if provider == "ANTHROPIC":
            return run_anthropic_completion(
                anthropic_api_key, anthropic_model, model, messages, parameters
            )
        if provider in ("OPEN_AI", "OPENAI"):
            return run_openai_completion(openai_api_key, model, messages, parameters)

        return {
            "error": f"Unsupported provider: {provider or 'unknown'}",
            "details": "Supported providers: ANTHROPIC, OPEN_AI",
        }, 400

    except Exception as exc:
        log.error("[CHAT-COMPLETION] Unhandled error: %s\n%s", exc, traceback.format_exc())
        return {"error": "Chat completion failed", "details": str(exc)}, 500
