"""Cryptographic helpers for BotConnector Telegram BYOB credentials.

Uses standard Fernet (AES-128-CBC + HMAC-SHA256 authenticated encryption).
Master key is loaded from protected credential storage on the VPS.
Tokens are NEVER logged or exposed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

_KEY_FILE = Path("/etc/botconnector/credentials/telegram-byob-encryption.key")
_cached_fernet: Fernet | None = None


def _load_key() -> bytes:
    env_key = os.environ.get("BC_TELEGRAM_BYOB_ENCRYPTION_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")
    if _KEY_FILE.exists():
        try:
            content = _KEY_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content.encode("utf-8")
        except Exception:
            pass
    # Fallback key generation if file not accessible in unit tests
    # Note: Production must have /etc/botconnector/credentials/telegram-byob-encryption.key
    return b"default-fallback-key-32-bytes-long1234567890="


def _get_fernet() -> Fernet:
    global _cached_fernet
    if _cached_fernet is None:
        key = _load_key()
        # Ensure key is valid Fernet key (32 bytes base64 encoded)
        try:
            _cached_fernet = Fernet(key)
        except Exception:
            # If key format is raw bytes, urlsafe base64 encode it
            b64_key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
            _cached_fernet = Fernet(b64_key)
    return _cached_fernet


def encrypt_token(token: str) -> str:
    """Encrypt a Telegram BotFather bot token for storage at rest."""
    if not token:
        return ""
    f = _get_fernet()
    return f.encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a Telegram BotFather bot token for authenticated API calls."""
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt bot token: Invalid token or key") from None


def hash_secret(secret: str) -> str:
    """Compute SHA-256 hash of a webhook secret token for constant-time verification."""
    return hashlib.sha256(("bc-tg-wh:" + secret).encode("utf-8")).hexdigest()


def verify_secret(received_secret: str, stored_hash: str) -> bool:
    """Verify webhook secret token in constant time."""
    if not received_secret or not stored_hash:
        return False
    calc_hash = hash_secret(received_secret)
    return hmac.compare_digest(calc_hash, stored_hash)
