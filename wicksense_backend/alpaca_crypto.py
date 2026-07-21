"""
Alpaca credential field encryption (server-side only).

Format: enc:v1:<base64(iv || tag || ciphertext)>  (AES-256-GCM)

Key: ALPACA_CREDENTIALS_ENCRYPTION_KEY — base64-encoded 32 bytes.
Never log plaintext or the encryption key.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("wicksense.alpaca.crypto")

PREFIX = "enc:v1:"
PLACEHOLDERS = frozenset({"", "paper_not_configured", "pending"})


def _env_key_raw() -> str:
    return (os.environ.get("ALPACA_CREDENTIALS_ENCRYPTION_KEY") or "").strip()


def clear_encryption_cache() -> None:
    encryption_configured.cache_clear()


@lru_cache(maxsize=1)
def encryption_configured() -> bool:
    raw = _env_key_raw()
    if not raw:
        return False
    try:
        key = base64.b64decode(raw)
        return len(key) == 32
    except Exception:
        return False


def _key_bytes_from_b64(raw: str) -> bytes:
    key = base64.b64decode(raw.strip())
    if len(key) != 32:
        raise RuntimeError("encryption key must decode to exactly 32 bytes")
    return key


def _aesgcm() -> AESGCM:
    raw = _env_key_raw()
    if not raw:
        raise RuntimeError(
            "ALPACA_CREDENTIALS_ENCRYPTION_KEY is not set "
            "(base64-encoded 32-byte key required)"
        )
    return AESGCM(_key_bytes_from_b64(raw))


def is_encrypted(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def is_placeholder(value: str | None) -> bool:
    return value is None or str(value).strip() in PLACEHOLDERS


def mask_key_preview(plain: str | None) -> str | None:
    if not plain or is_placeholder(plain):
        return None
    s = str(plain)
    if len(s) < 8:
        return "••••"
    return f"{s[:4]}…{s[-4:]}"


def mask_account_number(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value)
    if len(s) <= 4:
        return "••••"
    return f"••••{s[-4:]}"


def mask_account_id(value: str | None) -> str | None:
    if not value:
        return None
    s = str(value)
    if len(s) <= 8:
        return "••••"
    return f"{s[:4]}…{s[-4:]}"


def last4(plain: str | None) -> str | None:
    if not plain or is_placeholder(plain):
        return None
    s = str(plain)
    return s[-4:] if len(s) >= 4 else s


def encrypt_field_with_key(plaintext: str, key_bytes: bytes) -> str:
    text = str(plaintext)
    if is_encrypted(text):
        # Caller must decrypt with old key first; do not double-wrap
        raise ValueError("value already encrypted — decrypt before re-encrypt")
    aes = AESGCM(key_bytes)
    iv = os.urandom(12)
    ct = aes.encrypt(iv, text.encode("utf-8"), None)
    blob = base64.b64encode(iv + ct).decode("ascii")
    return f"{PREFIX}{blob}"


def decrypt_field_with_key(value: str | None, key_bytes: bytes) -> str | None:
    if value is None:
        return None
    text = str(value)
    if is_placeholder(text):
        return None
    if not is_encrypted(text):
        return text
    raw = base64.b64decode(text[len(PREFIX) :])
    if len(raw) < 13:
        raise ValueError("invalid encrypted credential blob")
    iv, ct = raw[:12], raw[12:]
    aes = AESGCM(key_bytes)
    return aes.decrypt(iv, ct, None).decode("utf-8")


def encrypt_field(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("cannot encrypt empty credential")
    text = str(plaintext)
    if is_encrypted(text):
        return text
    return encrypt_field_with_key(text, _key_bytes_from_b64(_env_key_raw()))


def decrypt_field(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    if is_placeholder(text):
        return None
    if not is_encrypted(text):
        return text
    return decrypt_field_with_key(text, _key_bytes_from_b64(_env_key_raw()))


def ensure_encrypted_pair(api_key: str, secret_key: str) -> tuple[str, str, bool]:
    """
    Returns (enc_api_key, enc_secret_key, changed).
    Encrypts plaintext fields; leaves already-encrypted values unchanged.
    """
    if not encryption_configured():
        raise RuntimeError("encryption_not_configured")

    changed = False
    out_key, out_secret = api_key, secret_key

    if not is_encrypted(api_key) and not is_placeholder(api_key):
        out_key = encrypt_field(api_key)
        changed = True
    if not is_encrypted(secret_key) and not is_placeholder(secret_key):
        out_secret = encrypt_field(secret_key)
        changed = True

    return out_key, out_secret, changed


def rotate_ciphertext_field(value: str | None, old_key: bytes, new_key: bytes) -> tuple[str | None, bool]:
    """
    Re-encrypt a single field from old_key → new_key.
    Plaintext legacy values are encrypted with new_key.
    Returns (new_value, changed).
    """
    if value is None or is_placeholder(value):
        return value, False
    plain = decrypt_field_with_key(value, old_key) if is_encrypted(value) else str(value)
    if not plain:
        return value, False
    new_ct = encrypt_field_with_key(plain, new_key)
    return new_ct, new_ct != value


def fingerprint_plain(plain: str | None) -> str | None:
    """Non-reversible digest for audits — never a substitute for encryption."""
    if not plain or is_placeholder(plain):
        return None
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()[:16]
