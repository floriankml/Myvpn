"""Strikte Eingabevalidierung für den privilegierten Agenten.

Der Agent vertraut dem Backend NICHT blind: Jede Eingabe wird hier erneut
geprüft, bevor sie (als einzelnes Argument, nie über eine Shell) an `wg`
übergeben wird.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re

# WireGuard-Schlüssel: 32 Byte, Base64 mit Padding => 44 Zeichen, letztes "=".
# Das vorletzte Zeichen kann nur bestimmte Werte annehmen (die letzten 4 Bit
# sind bei 32 Byte immer 0).
_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$")
_IFACE_RE = re.compile(r"^[A-Za-z0-9_=+.-]{1,15}$")


class ValidationError(ValueError):
    """Ungültige Eingabe vom Client."""


def validate_key(value: object, what: str = "Schlüssel") -> str:
    if not isinstance(value, str) or not _KEY_RE.fullmatch(value):
        raise ValidationError(f"ungültiger {what}")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - durch Regex abgedeckt
        raise ValidationError(f"ungültiger {what}") from exc
    if len(raw) != 32:
        raise ValidationError(f"ungültiger {what}")
    if raw == bytes(32):
        raise ValidationError(f"ungültiger {what}")
    return value


def validate_interface(value: str) -> str:
    if not _IFACE_RE.fullmatch(value):
        raise ValidationError("ungültiger Interface-Name")
    return value


def validate_allowed_ips(
    value: object,
    allowed_nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
    reserved: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> list[str]:
    """Erlaubt nur Einzeladressen (/32 bzw. /128) innerhalb der VPN-Netze.

    Damit kann selbst ein kompromittiertes Backend keinem Peer z. B.
    0.0.0.0/0 zuweisen und so den Verkehr anderer Nutzer umleiten.
    """
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise ValidationError("allowed_ips muss 1-2 Einträge enthalten")
    result: list[str] = []
    seen_versions: set[int] = set()
    for item in value:
        if not isinstance(item, str) or len(item) > 64:
            raise ValidationError("ungültige Adresse")
        try:
            net = ipaddress.ip_network(item, strict=True)
        except ValueError as exc:
            raise ValidationError("ungültige Adresse") from exc
        if net.prefixlen != net.max_prefixlen:
            raise ValidationError("nur Einzeladressen erlaubt")
        if net.version in seen_versions:
            raise ValidationError("höchstens eine Adresse je IP-Version")
        seen_versions.add(net.version)
        addr = net.network_address
        if not any(net.version == n.version and addr in n for n in allowed_nets):
            raise ValidationError("Adresse außerhalb des VPN-Netzes")
        if addr in reserved:
            raise ValidationError("reservierte Adresse")
        for n in allowed_nets:
            if n.version == net.version and addr in n and n.version == 4:
                if addr in (n.network_address, n.broadcast_address):
                    raise ValidationError("reservierte Adresse")
        result.append(str(net))
    return result


def validate_peer(
    value: object,
    allowed_nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
    reserved: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("Peer muss ein Objekt sein")
    unknown = set(value) - {"public_key", "allowed_ips", "preshared_key"}
    if unknown:
        raise ValidationError("unbekannte Felder")
    peer: dict[str, object] = {
        "public_key": validate_key(value.get("public_key"), "öffentlicher Schlüssel"),
        "allowed_ips": validate_allowed_ips(value.get("allowed_ips"), allowed_nets, reserved),
    }
    psk = value.get("preshared_key")
    if psk is not None:
        peer["preshared_key"] = validate_key(psk, "Pre-Shared-Key")
    return peer
