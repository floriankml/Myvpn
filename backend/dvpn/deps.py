"""Gemeinsame Abhängigkeiten: DB-Sitzung, angemeldeter Benutzer, Admin-Prüfung."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .agent_client import AgentClient
from .config import Settings
from .models import AuthSession, User, utcnow
from .security import as_utc, hash_token

COOKIE_NAME = "dvpn_session"


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def get_agent(request: Request) -> AgentClient:
    return request.app.state.agent


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Session, Depends(get_db)]
AgentDep = Annotated[AgentClient, Depends(get_agent)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def current_session(request: Request, db: DbDep) -> AuthSession:
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 128:
        raise HTTPException(401, "Nicht angemeldet")
    sess = db.query(AuthSession).filter_by(token_hash=hash_token(token)).one_or_none()
    if sess is None or as_utc(sess.expires_at) < utcnow() or not sess.user.is_active:
        raise HTTPException(401, "Sitzung abgelaufen")
    return sess


def current_user(sess: Annotated[AuthSession, Depends(current_session)]) -> User:
    return sess.user


def require_admin(request: Request, user: Annotated[User, Depends(current_user)], s: SettingsDep) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Keine Berechtigung")
    # Administrative Funktionen nur aus dem VPN-Tunnel oder lokal (SSH-Tunnel).
    try:
        ip = ipaddress.ip_address(client_ip(request))
    except ValueError:
        raise HTTPException(403, "Administration nur über VPN oder lokal") from None
    if not any(ip.version == n.version and ip in n for n in s.admin_nets):
        raise HTTPException(403, "Administration nur über VPN oder lokal")
    return user


UserDep = Annotated[User, Depends(current_user)]
AdminDep = Annotated[User, Depends(require_admin)]


def ready_user(user: UserDep) -> User:
    """Benutzer mit Initialpasswort müssen dieses erst ändern."""
    if user.must_change_password:
        raise HTTPException(403, "Bitte ändern Sie zuerst Ihr Initialpasswort.")
    return user


ReadyUserDep = Annotated[User, Depends(ready_user)]
