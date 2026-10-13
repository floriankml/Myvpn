"""Passwörter, Sitzungstoken und WireGuard-Schlüsselformat."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id mit den Standardparametern von argon2-cffi (RFC 9106, "low memory").
_ph = PasswordHasher()
# Dummy-Hash: auch bei unbekanntem Benutzernamen wird ein Hash geprüft, damit
# die Antwortzeit nicht verrät, ob ein Konto existiert.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))

PASSWORD_MIN = 12
PASSWORD_MAX = 256
_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def new_session_token() -> tuple[str, str]:
    """Liefert (Token für das Cookie, Hash für die Datenbank)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_password() -> str:
    """Zufälliges Initialpasswort (~120 Bit), gut abtippbar."""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    return "-".join(groups)


def generate_psk() -> str:
    """32 Byte aus dem CSPRNG des Betriebssystems – entspricht `wg genpsk`."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def is_valid_wg_key(value: str) -> bool:
    if not _KEY_RE.fullmatch(value):
        return False
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) == 32 and raw != bytes(32)


def as_utc(dt: datetime) -> datetime:
    """SQLite liefert naive Zeitstempel zurück – wir speichern immer UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
