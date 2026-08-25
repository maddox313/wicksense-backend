"""Phase 2A: JWT helpers + per-user file stores for legacy Flask shared state."""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import jsonify, request

from wicksense_backend.alpaca_helpers import get_user_id_from_request, supabase_auth_configured

USER_DATA_ROOT = Path(os.environ.get("WICKSENSE_USER_DATA_DIR") or "user_data")


def require_user():
    auth = request.headers.get("Authorization", "") or ""
    if not supabase_auth_configured():
        return None, (jsonify({"error": "Unauthorized", "reason": "supabase_auth_not_configured"}), 503)
    user_id, reason = get_user_id_from_request(auth)
    if not user_id:
        return None, (jsonify({"error": "Unauthorized", "reason": reason or "unauthorized"}), 401)
    return user_id, auth


def user_dir(user_id: str) -> Path:
    d = USER_DATA_ROOT / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_user_json(user_id: str, filename: str, default):
    path = user_dir(user_id) / filename
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user_json(user_id: str, filename: str, data) -> None:
    path = user_dir(user_id) / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
