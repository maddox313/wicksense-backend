"""
Shared CORS configuration for wicksense-backend (Render trading service).

Import in the main Flask app.py:

    from wicksense_backend.register_extensions import register_wicksense_extensions
    register_wicksense_extensions(app)
"""

import os
from flask import request, make_response
from flask_cors import CORS

DEFAULT_ORIGINS = [
    "https://wicksensetrading.com",
    "https://www.wicksensetrading.com",
    "https://wicksense-day-trader-pro.onrender.com",
    "https://wicksense7625.builtwithrocket.new",
    "http://localhost:4028",
    "http://127.0.0.1:4028",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

ALLOWED_HEADERS = [
    "Content-Type",
    "Authorization",
    "X-Requested-With",
    "Accept",
    "Origin",
]

ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def get_allowed_origins():
    origins = list(DEFAULT_ORIGINS)
    extra = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if extra.strip():
        for part in extra.split(","):
            part = part.strip()
            if part and part not in origins:
                origins.append(part)
    return origins


def apply_cors(app):
    """Apply flask-cors to the trading Flask app."""
    CORS(
        app,
        origins=get_allowed_origins(),
        supports_credentials=True,
        allow_headers=ALLOWED_HEADERS,
        methods=ALLOWED_METHODS,
        expose_headers=["Content-Type"],
    )


def _origin_allowed(origin):
    if not origin:
        return False
    allowed = get_allowed_origins()
    if origin in allowed:
        return True
    if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
        return True
    return False


def _apply_cors_headers(response, origin):
    if _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = ", ".join(ALLOWED_METHODS)
    response.headers["Access-Control-Allow-Headers"] = ", ".join(ALLOWED_HEADERS)
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


def register_global_options_handler(app):
    """
    Ensure OPTIONS preflight returns 204 for ALL routes (including /alpaca/*).
    Browsers reject preflight when the server returns 404, even with ACAO headers.
    """

    @app.before_request
    def handle_global_preflight():
        if request.method != "OPTIONS":
            return None
        origin = request.headers.get("Origin")
        response = make_response("", 204)
        return _apply_cors_headers(response, origin)
