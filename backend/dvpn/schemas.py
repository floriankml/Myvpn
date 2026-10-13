"""Pydantic-Schemas: strenge Validierung aller Eingaben (unbekannte Felder verboten)."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .security import PASSWORD_MAX, PASSWORD_MIN, is_valid_wg_key

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_DEVICE_NAME_RE = re.compile(r"^[\w äöüÄÖÜß().,+-]{1,40}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_username(v: str) -> str:
    v = v.lower()
    if not _USERNAME_RE.fullmatch(v):
        raise ValueError("Benutzername: 3–32 Zeichen, a–z, 0–9, . _ -")
    return v


class LoginIn(Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX)


class PasswordChangeIn(Strict):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool
    must_change_password: bool
    created_at: datetime


class DeviceCreateIn(Strict):
    name: str = Field(min_length=1, max_length=40)
    public_key: str = Field(min_length=44, max_length=44)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _DEVICE_NAME_RE.fullmatch(v):
            raise ValueError("Gerätename: 1–40 Zeichen (Buchstaben, Ziffern, Leerzeichen, - _ . ( ) +)")
        return v

    @field_validator("public_key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not is_valid_wg_key(v):
            raise ValueError("Ungültiger öffentlicher WireGuard-Schlüssel")
        return v


class DeviceOut(BaseModel):
    id: int
    name: str
    public_key: str
    ipv4: str
    ipv6: str | None
    server_id: str
    created_at: datetime
    revoked_at: datetime | None
    owner: str | None = None
    # Live-Daten aus dem Kernel (nicht gespeichert):
    connected: bool | None = None
    latest_handshake: int | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None


class AdminUserCreateIn(Strict):
    username: str = Field(min_length=3, max_length=32)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def _u(cls, v: str) -> str:
        return _check_username(v)


class AdminUserPatchIn(Strict):
    is_active: bool | None = None
    is_admin: bool | None = None
