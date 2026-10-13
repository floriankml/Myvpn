"""Server-Übersicht, Status und Verbindungserkennung."""

from __future__ import annotations

import ipaddress
import time

from fastapi import APIRouter, Request
from sqlalchemy import select

from ..agent_client import AgentError
from ..deps import AgentDep, DbDep, SettingsDep, UserDep, client_ip
from ..models import Device, Server
from .devices import HANDSHAKE_ACTIVE_SECONDS

router = APIRouter(prefix="/api", tags=["info"])


@router.get("/health")
def health() -> dict:
    """Minimaler, unauthentifizierter Lebenszeichen-Endpunkt (für Monitoring)."""
    return {"status": "ok"}


@router.get("/connection")
def connection(request: Request, user: UserDep, db: DbDep, s: SettingsDep) -> dict:
    """Erkennt, ob DIESE Anfrage durch den VPN-Tunnel kam (Quell-IP im VPN-Netz).

    Die IP wird nur für diese Antwort verwendet und nicht gespeichert.
    """
    ip_str = client_ip(request)
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return {"via_vpn": False, "client_ip": None, "device": None}
    nets = [s.net_v4] + ([s.net_v6] if s.net_v6 else [])
    via_vpn = any(ip.version == n.version and ip in n for n in nets)
    device = None
    if via_vpn:
        col = Device.ipv4 if ip.version == 4 else Device.ipv6
        d = db.scalar(select(Device).where(col == str(ip), Device.revoked_at.is_(None)))
        if d is not None and d.user_id == user.id:
            device = {"id": d.id, "name": d.name, "ipv4": d.ipv4, "ipv6": d.ipv6}
    return {"via_vpn": via_vpn, "client_ip": str(ip), "device": device}


@router.get("/servers")
def servers(_: UserDep, db: DbDep, s: SettingsDep, agent: AgentDep) -> list[dict]:
    online = agent.ping()
    return [
        {
            "id": srv.id, "name": srv.name, "location": srv.location, "provider": srv.provider,
            "endpoint": f"{srv.endpoint_host}:{srv.endpoint_port}",
            "public_ipv4": s.public_ipv4 or None, "public_ipv6": s.public_ipv6 or None,
            "ipv6_egress": s.ipv6_egress, "online": online,
        }
        for srv in db.scalars(select(Server))
    ]


@router.get("/status")
def status(user: UserDep, s: SettingsDep, agent: AgentDep) -> dict:
    result: dict = {
        "agent": False, "interface_up": False, "listen_port": None, "server_public_key": None,
        "peers_configured": None, "peers_active": None,
        "ipv6_tunnel": s.net_v6 is not None, "ipv6_egress": s.ipv6_egress,
        "dns_servers": s.dns_servers, "subnet_v4": s.subnet_v4, "subnet_v6": s.subnet_v6 or None,
        "server_time": int(time.time()),
    }
    try:
        st = agent.status()
    except AgentError:
        result["agent"] = agent.ping()
        return result
    now = time.time()
    result.update(agent=True, interface_up=True, listen_port=st["listen_port"],
                  server_public_key=st["public_key"])
    if user.is_admin:  # Aggregierte Zahlen nur für Admins
        result["peers_configured"] = len(st["peers"])
        result["peers_active"] = sum(
            1 for p in st["peers"] if p["latest_handshake"] and now - p["latest_handshake"] < HANDSHAKE_ACTIVE_SECONDS
        )
    return result
