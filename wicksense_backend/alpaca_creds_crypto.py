"""LR-P1-02 — Alpaca credential AES-256-GCM envelope (Flask / Python).

Envelope plaintext: UTF-8 JSON {"api_key":"...","secret_key":"..."}
AAD: wicksense:alpaca_credentials:v1:{user_id}:{mode}

Never log plaintext, ciphertext, nonce, keys, or Authorization headers.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Mapping, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENC_VERSION = 1
NONCE_BYTES = 12
KEY_BYTES = 32
AAD_PREFIX = "wicksense:alpaca_credentials:v1"


class AlpacaCredsCryptoError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_aad(user_id: str, mode: str) -> bytes:
    if not user_id or not mode:
        raise AlpacaCredsCryptoError("invalid_aad", "user_id and mode required for AAD")
    return f"{AAD_PREFIX}:{user_id}:{mode}".encode("utf-8")


def serialize_envelope(api_key: str, secret_key: str) -> bytes:
    if not api_key or not secret_key:
        raise AlpacaCredsCryptoError("invalid_plaintext", "api_key and secret_key required")
    # Fixed key order; compact separators — must match Edge/JS JSON.stringify.
    return json.dumps(
        {"api_key": api_key, "secret_key": secret_key},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def parse_envelope(raw: bytes) -> dict:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise AlpacaCredsCryptoError("malformed_ciphertext", "Envelope JSON parse failed") from err
    if not isinstance(parsed, dict):
        raise AlpacaCredsCryptoError("malformed_ciphertext", "Envelope not an object")
    api_key = parsed.get("api_key") if isinstance(parsed.get("api_key"), str) else ""
    secret_key = parsed.get("secret_key") if isinstance(parsed.get("secret_key"), str) else ""
    if not api_key or not secret_key:
        raise AlpacaCredsCryptoError("malformed_ciphertext", "Envelope missing keys")
    return {"api_key": api_key, "secret_key": secret_key}


def _key_env_name(key_id: str) -> str:
    return f"ALPACA_CREDS_KEY_{str(key_id).upper()}_B64"


def resolve_active_key_id(environ: Optional[Mapping[str, str]] = None) -> str:
    env = environ if environ is not None else os.environ
    key_id = (env.get("ALPACA_CREDS_ACTIVE_KEY_ID") or "").strip()
    if not key_id:
        raise AlpacaCredsCryptoError("missing_key", "ALPACA_CREDS_ACTIVE_KEY_ID not set")
    return key_id


def load_key_bytes(key_id: str, environ: Optional[Mapping[str, str]] = None) -> bytes:
    env = environ if environ is not None else os.environ
    env_name = _key_env_name(key_id)
    raw = (env.get(env_name) or "").strip()
    if not raw:
        raise AlpacaCredsCryptoError("unknown_key_id", f"Missing key material for key_id={key_id}")
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as err:
        raise AlpacaCredsCryptoError("invalid_key", f"Invalid Base64 for {env_name}") from err
    if len(key) != KEY_BYTES:
        raise AlpacaCredsCryptoError(
            "invalid_key_length",
            f"Key for {key_id} must be {KEY_BYTES} bytes",
        )
    return key


def encrypt_credential_envelope(
    api_key: str,
    secret_key: str,
    user_id: str,
    mode: str,
    *,
    key_id: Optional[str] = None,
    key_bytes: Optional[bytes] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict:
    env = environ if environ is not None else os.environ
    resolved_key_id = key_id or resolve_active_key_id(env)
    material = key_bytes if key_bytes is not None else load_key_bytes(resolved_key_id, env)
    nonce = os.urandom(NONCE_BYTES)
    aad = build_aad(user_id, mode)
    plaintext = serialize_envelope(api_key, secret_key)
    ciphertext = AESGCM(material).encrypt(nonce, plaintext, aad)
    return {
        "credential_ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "credential_nonce": base64.b64encode(nonce).decode("ascii"),
        "enc_version": ENC_VERSION,
        "key_id": resolved_key_id,
    }


def decrypt_credential_envelope(
    fields: Mapping[str, Any],
    user_id: str,
    mode: str,
    *,
    key_bytes: Optional[bytes] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict:
    env = environ if environ is not None else os.environ
    key_id = str(fields.get("key_id") or "").strip()
    if not key_id:
        raise AlpacaCredsCryptoError("unknown_key_id", "key_id missing on encrypted row")
    enc_version = fields.get("enc_version")
    if enc_version is not None and int(enc_version) != ENC_VERSION:
        raise AlpacaCredsCryptoError("unsupported_enc_version", f"enc_version={enc_version}")
    material = key_bytes if key_bytes is not None else load_key_bytes(key_id, env)
    try:
        nonce = base64.b64decode(str(fields.get("credential_nonce") or ""), validate=True)
    except Exception as err:
        raise AlpacaCredsCryptoError("invalid_nonce", "Nonce Base64 decode failed") from err
    if len(nonce) != NONCE_BYTES:
        raise AlpacaCredsCryptoError("invalid_nonce", f"Nonce must be {NONCE_BYTES} bytes")
    try:
        ciphertext = base64.b64decode(str(fields.get("credential_ciphertext") or ""), validate=True)
    except Exception as err:
        raise AlpacaCredsCryptoError("invalid_ciphertext", "Ciphertext Base64 decode failed") from err
    if not ciphertext:
        raise AlpacaCredsCryptoError("invalid_ciphertext", "Empty ciphertext")
    aad = build_aad(user_id, mode)
    try:
        plaintext = AESGCM(material).decrypt(nonce, ciphertext, aad)
    except Exception as err:
        raise AlpacaCredsCryptoError("authentication_failure", "AES-GCM decrypt/auth failed") from err
    return parse_envelope(plaintext)


def is_encrypted_credential_row(row: Optional[Mapping[str, Any]]) -> bool:
    if not row:
        return False
    return row.get("enc_version") is not None or bool(row.get("credential_ciphertext"))


def is_legacy_plaintext_credential_row(row: Optional[Mapping[str, Any]]) -> bool:
    if not row:
        return False
    if row.get("enc_version") is not None or row.get("credential_ciphertext"):
        return False
    return bool(row.get("api_key") and row.get("secret_key"))
