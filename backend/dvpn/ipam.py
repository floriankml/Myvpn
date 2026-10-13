"""Vergabe der Tunnel-Adressen (IPv4 und optional IPv6 mit gleichem Host-Index)."""

from __future__ import annotations

import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Device


class AddressPoolExhausted(Exception):
    pass


def allocate(db: Session, settings: Settings, server_id: str) -> tuple[str, str | None]:
    net4 = settings.net_v4
    used = set(
        db.scalars(
            select(Device.ipv4).where(Device.server_id == server_id, Device.revoked_at.is_(None))
        )
    )
    # .1 = Server, letzte Adresse = Broadcast
    for index in range(2, net4.num_addresses - 1):
        ip4 = str(net4.network_address + index)
        if ip4 not in used:
            ip6 = None
            if settings.net_v6 is not None:
                ip6 = str(ipaddress.IPv6Address(int(settings.net_v6.network_address) + index))
            return ip4, ip6
    raise AddressPoolExhausted
