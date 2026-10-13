"""Benutzerverwaltung – nur für Administratoren und nur aus VPN/localhost."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select

from ..agent_client import AgentError
from ..deps import AdminDep, AgentDep, DbDep, SettingsDep
from ..models import AuthSession, Device, User, utcnow
from ..schemas import AdminUserCreateIn, AdminUserPatchIn, UserOut
from ..security import generate_password, hash_password
from ..services import sync_agent
from .auth import user_out

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _get_user(db, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    return u


def _try_sync(db, s, agent) -> bool:
    try:
        sync_agent(db, s, agent)
        return True
    except AgentError:
        return False


@router.get("/users", response_model=list[UserOut])
def list_users(_: AdminDep, db: DbDep) -> list[UserOut]:
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: AdminUserCreateIn, _: AdminDep, db: DbDep) -> dict:
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "Benutzername existiert bereits")
    password = generate_password()
    u = User(username=body.username, password_hash=hash_password(password),
             is_admin=body.is_admin, must_change_password=True)
    db.add(u)
    db.commit()
    # Das Initialpasswort wird genau einmal angezeigt und nicht gespeichert.
    return {"user": user_out(u).model_dump(mode="json"), "initial_password": password}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, admin: AdminDep, db: DbDep) -> dict:
    u = _get_user(db, user_id)
    password = generate_password()
    u.password_hash = hash_password(password)
    u.must_change_password = True
    db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    db.commit()
    return {"initial_password": password}


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: AdminUserPatchIn, admin: AdminDep, db: DbDep,
               s: SettingsDep, agent: AgentDep) -> UserOut:
    u = _get_user(db, user_id)
    if u.id == admin.id and (body.is_active is False or body.is_admin is False):
        raise HTTPException(400, "Eigenes Administratorkonto kann nicht deaktiviert/herabgestuft werden")
    if body.is_admin is not None:
        u.is_admin = body.is_admin
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:
            db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
    db.commit()
    if body.is_active is not None:
        _try_sync(db, s, agent)  # deaktivierte Nutzer verlieren sofort den VPN-Zugang
    return user_out(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: AdminDep, db: DbDep, s: SettingsDep, agent: AgentDep) -> dict:
    u = _get_user(db, user_id)
    if u.id == admin.id:
        raise HTTPException(400, "Eigenes Konto kann nicht gelöscht werden")
    db.execute(delete(Device).where(Device.user_id == u.id))
    db.delete(u)
    db.commit()
    return {"deleted": True, "applied": _try_sync(db, s, agent)}
