"""Geräteverwaltung (eigene Geräte; Admins zusätzlich alle)."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..agent_client import AgentClient, AgentError
from ..deps import AgentDep, DbDep, ReadyUserDep, SettingsDep
from ..ipam import AddressPoolExhausted
from ..models import Device, Server, User
from ..schemas import DeviceCreateIn, DeviceOut
from ..services import DeviceError, config_template, create_device, revoke_device, server_public_key

router = APIRouter(prefix="/api/devices", tags=["devices"])

HANDSHAKE_ACTIVE_SECONDS = 180  # WireGuard erneuert Handshakes spätestens alle ~2 Min.


def live_status(agent: AgentClient) -> dict[str, dict]:
    try:
        return {p["public_key"]: p for p in agent.status()["peers"]}
    except (AgentError, KeyError, TypeError):
        return {}


def device_out(d: Device, live: dict[str, dict] | None, owner: str | None = None) -> DeviceOut:
    out = DeviceOut.model_validate(d, from_attributes=True)
    out.owner = owner
    if live is not None and d.revoked_at is None:
        p = live.get(d.public_key)
        if p:
            hs = int(p["latest_handshake"])
            out.latest_handshake = hs or None
            out.connected = bool(hs) and time.time() - hs < HANDSHAKE_ACTIVE_SECONDS
            out.rx_bytes, out.tx_bytes = int(p["rx_bytes"]), int(p["tx_bytes"])
        else:
            out.connected = False
    return out


def _get_owned(db, user: User, device_id: int) -> Device:
    dev = db.get(Device, device_id)
    # Gleiche Antwort für "existiert nicht" und "gehört jemand anderem" (keine IDOR-Hinweise).
    if dev is None or (dev.user_id != user.id and not user.is_admin):
        raise HTTPException(404, "Gerät nicht gefunden")
    return dev


@router.get("", response_model=list[DeviceOut])
def list_devices(user: ReadyUserDep, db: DbDep, agent: AgentDep, all: bool = False) -> list[DeviceOut]:
    q = select(Device).order_by(Device.revoked_at.is_not(None), Device.created_at.desc())
    if not (all and user.is_admin):
        q = q.where(Device.user_id == user.id)
    devices = db.scalars(q).all()
    live = live_status(agent)
    return [device_out(d, live, d.user.username if all and user.is_admin else None) for d in devices]


@router.post("", status_code=201)
def add_device(body: DeviceCreateIn, request: Request, user: ReadyUserDep, db: DbDep,
               s: SettingsDep, agent: AgentDep) -> dict:
    if not request.app.state.limits["device_create"].hit(str(user.id)):
        raise HTTPException(429, "Zu viele neue Geräte in kurzer Zeit.")
    server_pub = server_public_key(agent)
    if server_pub is None:
        raise HTTPException(503, "VPN-Server derzeit nicht erreichbar. Bitte später erneut versuchen.")
    try:
        dev, applied = create_device(db, s, agent, user, body.name, body.public_key)
    except DeviceError as exc:
        raise HTTPException(exc.status, exc.message) from None
    except AddressPoolExhausted:
        raise HTTPException(409, "Keine freien VPN-Adressen mehr.") from None
    srv = db.get(Server, dev.server_id)
    return {
        "device": device_out(dev, None).model_dump(mode="json"),
        "config": config_template(s, srv, dev, server_pub),
        "applied": applied,
    }


@router.get("/{device_id}/config")
def get_config(device_id: int, user: ReadyUserDep, db: DbDep, s: SettingsDep, agent: AgentDep) -> dict:
    dev = _get_owned(db, user, device_id)
    if dev.user_id != user.id:  # Konfigurationen nur für den Eigentümer
        raise HTTPException(404, "Gerät nicht gefunden")
    if dev.revoked_at is not None:
        raise HTTPException(410, "Gerät wurde widerrufen")
    server_pub = server_public_key(agent)
    if server_pub is None:
        raise HTTPException(503, "VPN-Server derzeit nicht erreichbar.")
    return config_template(s, db.get(Server, dev.server_id), dev, server_pub)


@router.post("/{device_id}/revoke")
def revoke(device_id: int, user: ReadyUserDep, db: DbDep, agent: AgentDep) -> dict:
    dev = _get_owned(db, user, device_id)
    applied = revoke_device(db, agent, dev)
    return {"revoked": True, "applied": applied}
