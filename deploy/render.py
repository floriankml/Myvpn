#!/usr/bin/env python3
"""Rendert die Server-Konfigurationsdateien aus validierten Parametern.

Nur Standardbibliothek. Wird von install.sh UND vom Integrationstest verwendet,
damit genau die produktiven Firewall-/DNS-/WireGuard-Regeln getestet werden.

Jeder Parameter wird streng validiert, bevor er in eine Vorlage eingesetzt
wird – so können keine Befehle oder zusätzlichen Regeln eingeschleust werden.

Aufruf:
  render.py --out DIR --wan-if eth0 --endpoint vpn.example.de [Optionen]
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"

IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
TEXT_RE = re.compile(r"^[\w äöüÄÖÜß().,/+-]{0,64}$")
KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$")


def die(msg: str) -> None:
    sys.exit(f"render.py: {msg}")


def port(v: str) -> int:
    p = int(v)
    if not 1 <= p <= 65535:
        raise argparse.ArgumentTypeError("Port ungültig")
    return p


def iface(v: str) -> str:
    if not IFACE_RE.fullmatch(v):
        raise argparse.ArgumentTypeError("Interface-Name ungültig")
    return v


def host(v: str) -> str:
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        if not HOST_RE.fullmatch(v):
            raise argparse.ArgumentTypeError("Hostname ungültig") from None
        return v.lower()


def text(v: str) -> str:
    if not TEXT_RE.fullmatch(v):
        raise argparse.ArgumentTypeError("Text enthält unzulässige Zeichen")
    return v


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--wan-if", required=True, type=iface)
    p.add_argument("--wg-if", default="wg0", type=iface)
    p.add_argument("--endpoint", required=True, type=host)
    p.add_argument("--wg-port", default=51820, type=port)
    p.add_argument("--ssh-port", default=22, type=port)
    p.add_argument("--web-port", default=8080, type=port)
    p.add_argument("--subnet-v4", default="10.8.0.0/24")
    p.add_argument("--subnet-v6", default="", help="ULA /64, leer = kein IPv6 im Tunnel")
    p.add_argument("--ipv6-egress", action="store_true")
    p.add_argument("--server-has-ipv6", action="store_true", help="Server selbst hat IPv6 (für Unbound)")
    p.add_argument("--public-web", action="store_true", help="TCP 80/443 öffnen (Caddy)")
    p.add_argument("--server-private-key", default="", help="leer = Platzhalter")
    p.add_argument("--server-name", default="Deutschland 1", type=text)
    p.add_argument("--location", default="Deutschland", type=text)
    p.add_argument("--provider", default="", type=text)
    p.add_argument("--public-ipv4", default="", type=lambda v: str(ipaddress.IPv4Address(v)) if v else "")
    p.add_argument("--public-ipv6", default="", type=lambda v: str(ipaddress.IPv6Address(v)) if v else "")
    p.add_argument("--domain", default="", type=lambda v: host(v) if v else "")
    p.add_argument("--install-dir", default="/opt/dvpn")
    p.add_argument("--state-dir", default="/var/lib/dvpn")
    a = p.parse_args(argv)

    net4 = ipaddress.ip_network(a.subnet_v4, strict=True)
    if net4.version != 4 or not net4.is_private:
        die("subnet-v4 muss ein privates IPv4-Netz sein")
    net6 = None
    if a.subnet_v6:
        net6 = ipaddress.ip_network(a.subnet_v6, strict=True)
        if net6.version != 6 or not net6.subnet_of(ipaddress.ip_network("fc00::/7")) or net6.prefixlen != 64:
            die("subnet-v6 muss ein ULA-/64 (fc00::/7) sein")
    if a.ipv6_egress and net6 is None:
        die("--ipv6-egress erfordert --subnet-v6")
    if a.server_private_key and not KEY_RE.fullmatch(a.server_private_key):
        die("server-private-key ungültig")
    for path in (a.install_dir, a.state_dir):
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
            die("Pfad ungültig")

    srv4 = net4.network_address + 1
    srv6 = (net6.network_address + 1) if net6 else None
    wg_addresses = f"{srv4}/{net4.prefixlen}" + (f", {srv6}/{net6.prefixlen}" if net6 else "")

    # ---------- IPv6-Regeln (Firewall) ----------
    if net6 is None:
        # Kein IPv6 im Tunnel: trotzdem jeglichen IPv6-Verkehr aus wg0 verwerfen.
        v6_forward = f'        iifname "{a.wg_if}" meta nfproto ipv6 reject with icmpx type admin-prohibited'
        nat6 = ""
    elif a.ipv6_egress:
        v6_forward = (f'        iifname "{a.wg_if}" oifname "{a.wan_if}" ip6 saddr {net6} accept\n'
                      f'        iifname "{a.wg_if}" meta nfproto ipv6 reject with icmpx type admin-prohibited')
        nat6 = (
            "table ip6 dvpn_nat6\ndelete table ip6 dvpn_nat6\n"
            "table ip6 dvpn_nat6 {\n"
            "    chain prerouting {\n        type nat hook prerouting priority dstnat; policy accept;\n"
            f'        iifname "{a.wg_if}" ip6 daddr != {srv6} udp dport 53 dnat to [{srv6}]:53\n'
            f'        iifname "{a.wg_if}" ip6 daddr != {srv6} tcp dport 53 dnat to [{srv6}]:53\n'
            "    }\n"
            "    chain postrouting {\n        type nat hook postrouting priority srcnat; policy accept;\n"
            f'        oifname "{a.wan_if}" ip6 saddr {net6} masquerade\n'
            "    }\n}\n"
        )
    else:
        # IPv6 im Tunnel, aber KEIN Ausgang: sofort ablehnen (schneller Fallback auf IPv4, kein Leck)
        v6_forward = f'        iifname "{a.wg_if}" meta nfproto ipv6 reject with icmpx type admin-prohibited'
        nat6 = (
            "table ip6 dvpn_nat6\ndelete table ip6 dvpn_nat6\n"
            "table ip6 dvpn_nat6 {\n"
            "    chain prerouting {\n        type nat hook prerouting priority dstnat; policy accept;\n"
            f'        iifname "{a.wg_if}" ip6 daddr != {srv6} udp dport 53 dnat to [{srv6}]:53\n'
            f'        iifname "{a.wg_if}" ip6 daddr != {srv6} tcp dport 53 dnat to [{srv6}]:53\n'
            "    }\n}\n"
        )

    values = {
        "WAN_IF": a.wan_if, "WG_IF": a.wg_if, "WG_PORT": a.wg_port, "SSH_PORT": a.ssh_port,
        "WEB_PORT": a.web_port, "SUBNET_V4": str(net4), "SUBNET_V6": str(net6) if net6 else "",
        "SERVER_V4": str(srv4), "SERVER_V6": str(srv6) if srv6 else "",
        "WG_ADDRESSES": wg_addresses,
        "SERVER_PRIVATE_KEY": a.server_private_key or "<SERVER_PRIVATE_KEY>",
        "V6_FORWARD_RULES": v6_forward, "NAT6_TABLE": nat6,
        "PUBLIC_WEB_RULE": "        tcp dport { 80, 443 } accept" if a.public_web else "        # Weboberfläche nur über VPN (privater Modus)",
        "UNBOUND_IFACE_V6": f"    interface: {srv6}\n    access-control: {net6} allow" if net6 else "",
        "UNBOUND_DO_IP6": "yes" if a.server_has_ipv6 else "no",
        "IPV6_FORWARDING": "1" if net6 else "0",
        "ENDPOINT": a.endpoint, "SERVER_NAME": a.server_name, "LOCATION": a.location,
        "PROVIDER": a.provider, "PUBLIC_IPV4": a.public_ipv4, "PUBLIC_IPV6": a.public_ipv6,
        "IPV6_EGRESS": "true" if a.ipv6_egress else "false",
        "DOMAIN": a.domain, "INSTALL_DIR": a.install_dir, "STATE_DIR": a.state_dir,
        "COOKIE_SECURE": "true" if a.domain else "false",
        "ALLOWED_ORIGINS": f"https://{a.domain}" if a.domain else "",
        "FORWARDED_ALLOW": str(srv4),
        "AGENT_SERVER_ADDRESSES": ",".join(x for x in (str(srv4), str(srv6) if srv6 else "") if x),
    }

    outputs = {
        "wg0.conf": "wg0.conf.tmpl",
        "nftables.nft": "nftables.nft.tmpl",
        "unbound-dvpn.conf": "unbound-dvpn.conf.tmpl",
        "sysctl-dvpn.conf": "sysctl-dvpn.conf.tmpl",
        "dvpn.env": "dvpn.env.tmpl",
        "agent.env": "agent.env.tmpl",
        "dvpn-agent.service": "dvpn-agent.service.tmpl",
        "dvpn-backend.service": "dvpn-backend.service.tmpl",
        "dvpn-firewall.service": "dvpn-firewall.service.tmpl",
        "Caddyfile": "Caddyfile.tmpl",
    }
    a.out.mkdir(parents=True, exist_ok=True)
    old = os.umask(0o077)
    try:
        for name, tmpl in outputs.items():
            if name == "Caddyfile" and not a.domain:
                continue
            content = string.Template((TEMPLATES / tmpl).read_text(encoding="utf-8")).substitute(values)
            (a.out / name).write_text(content, encoding="utf-8")
    finally:
        os.umask(old)
    print(json.dumps({"rendered": sorted(os.listdir(a.out))}))


if __name__ == "__main__":
    main()
