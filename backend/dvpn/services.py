"""Geschäftslogik: Geräte anlegen/widerrufen, Abgleich mit dem Agenten,
Erzeugen der WireGuard-Client-Konfiguration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_client import AgentClient, AgentError
from .config import Settings
from .ipam import allocate
from .models import AuthSession, Device, Server, User, utcnow
from .security import generate_psk

log = logging.getLogger("dvpn")


class DeviceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def ensure_server(db: Session, s: Settings) -> Server:
    """Legt den (einzigen) Server aus der Konfiguration an bzw. aktualisiert ihn."""
    srv = db.get(Server, s.server_id)
    if srv is None:
        srv = Server(id=s.server_id)
        db.add(srv)
    srv.name = s.server_name
    srv.location = s.server_location
    srv.provider = s.server_provider
    srv.endpoint_host = s.endpoint_host
    srv.endpoint_port = s.endpoint_port
    db.commit()
    return srv


def allowed_ips_for(device: Device) -> list[str]:
    ips = [f"{device.ipv4}/32"]
    if device.ipv6:
        ips.append(f"{device.ipv6}/128")
    return ips


def desired_peers(db: Session, server_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Device)
        .join(User)
        .where(Device.server_id == server_id, Device.revoked_at.is_(None), User.is_active.is_(True))
        .order_by(Device.id)
    )
    peers = []
    for d in rows:
        p: dict[str, Any] = {"public_key": d.public_key, "allowed_ips": allowed_ips_for(d)}
        if d.preshared_key:
            p["preshared_key"] = d.preshared_key
        peers.append(p)
    return peers


def sync_agent(db: Session, s: Settings, agent: AgentClient) -> dict[str, Any]:
    return agent.sync(desired_peers(db, s.server_id))


def create_device(
    db: Session, s: Settings, agent: AgentClient, user: User, name: str, public_key: str
) -> tuple[Device, bool]:
    """Legt ein Gerät an. Rückgabe: (Gerät, ob der Agent es sofort übernommen hat)."""
    active = db.scalar(
        select(func.count()).select_from(Device).where(Device.user_id == user.id, Device.revoked_at.is_(None))
    )
    if (active or 0) >= s.max_devices_per_user:
        raise DeviceError(f"Maximal {s.max_devices_per_user} aktive Geräte pro Konto.", 409)
    server_pub = _server_public_key(agent)
    if server_pub and server_pub == public_key:
        raise DeviceError("Dieser Schlüssel ist nicht zulässig.")
    if db.scalar(select(Device.id).where(Device.public_key == public_key, Device.revoked_at.is_(None))):
        raise DeviceError("Dieser öffentliche Schlüssel wird bereits verwendet.", 409)
    ipv4, ipv6 = allocate(db, s, s.server_id)
    dev = Device(
        user_id=user.id,
        server_id=s.server_id,
        name=name,
        public_key=public_key,
        preshared_key=generate_psk(),
        ipv4=ipv4,
        ipv6=ipv6,
    )
    db.add(dev)
    try:
        db.commit()
    except IntegrityError as exc:  # parallele Anlage – sehr selten
        db.rollback()
        raise DeviceError("Konflikt beim Anlegen, bitte erneut versuchen.", 409) from exc
    try:
        agent.upsert_peer(dev.public_key, allowed_ips_for(dev), dev.preshared_key)
        applied = True
    except AgentError as exc:
        log.warning("Peer konnte nicht sofort angewendet werden: %s", exc)
        applied = False
    return dev, applied


def revoke_device(db: Session, agent: AgentClient, dev: Device) -> bool:
    """Widerruft ein Gerät. Die Datenbank ist maßgeblich: auch wenn der Agent
    gerade nicht erreichbar ist, entfernt der nächste Abgleich den Peer."""
    if dev.revoked_at is None:
        dev.revoked_at = utcnow()
        dev.preshared_key = None  # nicht mehr benötigt -> löschen
        db.commit()
    try:
        agent.remove_peer(dev.public_key)
        return True
    except AgentError as exc:
        log.warning("Peer konnte nicht sofort entfernt werden: %s", exc)
        return False


def housekeeping(db: Session, s: Settings) -> None:
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    if s.revoked_retention_days >= 0:
        cutoff = now - timedelta(days=s.revoked_retention_days)
        db.execute(delete(Device).where(Device.revoked_at.is_not(None), Device.revoked_at < cutoff))
    db.commit()


_server_key_cache: dict[str, str] = {}


def _server_public_key(agent: AgentClient) -> str | None:
    if "key" in _server_key_cache:
        return _server_key_cache["key"]
    try:
        key = agent.call("info")["public_key"]
    except (AgentError, KeyError):
        return None
    _server_key_cache["key"] = key
    return key


def server_public_key(agent: AgentClient) -> str | None:
    return _server_public_key(agent)


def config_template(s: Settings, srv: Server, dev: Device, server_pub: str) -> dict[str, Any]:
    """Alle Bestandteile der Client-Konfiguration AUSSER dem privaten Schlüssel.

    Der private Schlüssel wird im Browser (bzw. per CLI lokal) erzeugt und
    verlässt das Gerät des Nutzers nie Richtung Server.
    """
    addresses = [f"{dev.ipv4}/32"]
    if dev.ipv6:
        addresses.append(f"{dev.ipv6}/128")
    host = srv.endpoint_host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6-Literal
    # Immer 0.0.0.0/0 UND ::/0: Auch ohne IPv6-Ausgang wird IPv6 in den Tunnel
    # gezogen und dort verworfen – so kann IPv6 nicht am Tunnel vorbei lecken.
    return {
        "interface": {"addresses": addresses, "dns": s.dns_servers, "mtu": s.client_mtu},
        "peer": {
            "public_key": server_pub,
            "preshared_key": dev.preshared_key,
            "endpoint": f"{host}:{srv.endpoint_port}",
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            "persistent_keepalive": s.persistent_keepalive or None,
        },
    }


def render_config(template: dict[str, Any], private_key: str) -> str:
    """Erzeugt eine wg-quick-kompatible Konfiguration (wie das Frontend)."""
    i, p = template["interface"], template["peer"]
    lines = ["[Interface]", f"PrivateKey = {private_key}", f"Address = {', '.join(i['addresses'])}"]
    if i.get("dns"):
        lines.append(f"DNS = {', '.join(i['dns'])}")
    if i.get("mtu"):
        lines.append(f"MTU = {i['mtu']}")
    lines += ["", "[Peer]", f"PublicKey = {p['public_key']}"]
    if p.get("preshared_key"):
        lines.append(f"PresharedKey = {p['preshared_key']}")
    lines += [f"AllowedIPs = {', '.join(p['allowed_ips'])}", f"Endpoint = {p['endpoint']}"]
    if p.get("persistent_keepalive"):
        lines.append(f"PersistentKeepalive = {p['persistent_keepalive']}")
    return "\n".join(lines) + "\n"
