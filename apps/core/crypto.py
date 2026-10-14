"""Symmetric field-level encryption helper for sensitive data at rest."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet_key() -> bytes:
    """Derive a URL-safe 32-byte base64-encoded key from Django's SECRET_KEY."""
    raw_secret = getattr(settings, "FIELD_ENCRYPTION_KEY", None) or settings.SECRET_KEY
    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(value: str | None) -> str:
    """Encrypt a plaintext string, returning a base64 Fernet token."""
    if not value:
        return ""
    fernet = Fernet(_get_fernet_key())
    token = fernet.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_value(token: str | None) -> str:
    """Decrypt a Fernet token back into plaintext. Returns empty string on failure or empty input."""
    if not token:
        return ""
    try:
        fernet = Fernet(_get_fernet_key())
        plaintext = fernet.decrypt(token.encode("utf-8"))
        return plaintext.decode("utf-8")
    except Exception:
        return ""


def mask_sensitive_value(value: str | None, visible_tail: int = 4) -> str:
    """Mask a sensitive identifier showing only the last N characters."""
    if not value:
        return ""
    clean = value.strip()
    if len(clean) <= visible_tail:
        return "*" * len(clean)
    masked_head = "*" * (len(clean) - visible_tail)
    return f"{masked_head}{clean[-visible_tail:]}"
