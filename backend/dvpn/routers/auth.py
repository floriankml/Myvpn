"""Anmeldung, Abmeldung, Passwortänderung, Datenauskunft."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from ..deps import COOKIE_NAME, DbDep, SettingsDep, UserDep, client_ip, current_session
from ..models import AuthSession, Device, User, utcnow
from ..schemas import LoginIn, PasswordChangeIn, UserOut
from ..security import hash_password, needs_rehash, new_session_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut.model_validate(u, from_attributes=True)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DbDep, s: SettingsDep) -> UserOut:
    limits = request.app.state.limits
    username = body.username.lower()
    if not limits["login_ip"].hit(client_ip(request)) or not limits["login_user"].hit(username):
        raise HTTPException(429, "Zu viele Anmeldeversuche. Bitte später erneut versuchen.")
    user = db.scalar(select(User).where(User.username == username))
    ok = verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None or not user.is_active:
        raise HTTPException(401, "Benutzername oder Passwort falsch")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    limits["login_user"].reset(username)
    token, token_hash = new_session_token()
    db.add(AuthSession(token_hash=token_hash, user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=s.session_ttl_hours)))
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=s.session_ttl_hours * 3600, httponly=True,
        secure=s.cookie_secure, samesite="strict", path="/",
    )
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DbDep) -> None:
    try:
        sess = current_session(request, db)
        db.delete(sess)
        db.commit()
    except HTTPException:
        pass
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: UserDep) -> UserOut:
    return user_out(user)


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, response: Response,
                    user: UserDep, db: DbDep, s: SettingsDep,
                    sess: Annotated[AuthSession, Depends(current_session)]) -> None:
    if not request.app.state.limits["login_user"].hit(user.username):
        raise HTTPException(429, "Zu viele Versuche. Bitte später erneut versuchen.")
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Aktuelles Passwort ist falsch")
    if body.new_password == body.current_password:
        raise HTTPException(400, "Das neue Passwort muss sich unterscheiden")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Alle anderen Sitzungen beenden
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != sess.id))
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, user: UserDep, db: DbDep) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/export")
def export_my_data(user: UserDep, db: DbDep) -> dict:
    """Auskunft nach Art. 15 DSGVO: alle zum Konto gespeicherten Daten."""
    devices = db.scalars(select(Device).where(Device.user_id == user.id)).all()
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
    return {
        "hinweis": "Vollständige Auskunft über die zu Ihrem Konto gespeicherten Daten. "
                   "Passwort-Hash und Pre-Shared-Keys sind aus Sicherheitsgründen nicht enthalten.",
        "konto": {"benutzername": user.username, "administrator": user.is_admin,
                  "aktiv": user.is_active, "angelegt": user.created_at.isoformat()},
        "geraete": [{"name": d.name, "oeffentlicher_schluessel": d.public_key, "ipv4": d.ipv4,
                     "ipv6": d.ipv6, "angelegt": d.created_at.isoformat(),
                     "widerrufen": d.revoked_at.isoformat() if d.revoked_at else None} for d in devices],
        "sitzungen": [{"angelegt": x.created_at.isoformat(), "laeuft_ab": x.expires_at.isoformat()}
                      for x in sessions],
    }
