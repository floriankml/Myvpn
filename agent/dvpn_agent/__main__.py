"""Startpunkt: python -m dvpn_agent [Optionen]

Alle Optionen können auch über Umgebungsvariablen (DVPN_AGENT_*) gesetzt werden,
damit die systemd-Unit eine EnvironmentFile verwenden kann.
"""

from __future__ import annotations

import argparse
import grp
import ipaddress
import logging
import os
import pwd
import signal
import sys
from pathlib import Path

from .server import Agent, AgentServer
from .validation import validate_interface
from .wg import Wg, WgError


def _env(name: str, default: str) -> str:
    return os.environ.get(f"DVPN_AGENT_{name}", default)


def _uid(value: str) -> int:
    return int(value) if value.isdigit() else pwd.getpwnam(value).pw_uid


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dvpn-agent")
    p.add_argument("--interface", default=_env("INTERFACE", "wg0"))
    p.add_argument("--socket", default=_env("SOCKET", "/run/dvpn-agent/agent.sock"))
    p.add_argument("--socket-group", default=_env("SOCKET_GROUP", ""))
    p.add_argument("--state-file", default=_env("STATE_FILE", "/var/lib/dvpn-agent/peers.json"))
    p.add_argument("--subnet-v4", default=_env("SUBNET_V4", "10.8.0.0/24"))
    p.add_argument("--subnet-v6", default=_env("SUBNET_V6", ""))
    p.add_argument("--server-addresses", default=_env("SERVER_ADDRESSES", "10.8.0.1"),
                   help="kommagetrennt; diese Adressen dürfen nie an Peers vergeben werden")
    p.add_argument("--allowed-users", default=_env("ALLOWED_USERS", ""),
                   help="kommagetrennte Benutzer/UIDs, die den Socket nutzen dürfen")
    p.add_argument("--wg-binary", default=_env("WG_BINARY", "wg"))
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("dvpn-agent")

    iface = validate_interface(args.interface)
    nets = [ipaddress.ip_network(args.subnet_v4, strict=True)]
    if args.subnet_v6:
        nets.append(ipaddress.ip_network(args.subnet_v6, strict=True))
    reserved = {ipaddress.ip_address(a.strip()) for a in args.server_addresses.split(",") if a.strip()}
    allowed_uids = {_uid(u.strip()) for u in args.allowed_users.split(",") if u.strip()}

    agent = Agent(Wg(iface, args.wg_binary), Path(args.state_file), nets, reserved)
    agent.load_state()
    try:
        stats = agent.apply()
        log.info("Zustand wiederhergestellt: %s Peers (%s)", len(agent.desired), stats)
    except WgError as exc:
        # Interface evtl. noch nicht oben – der nächste Sync des Backends holt das nach.
        log.error("Wiederherstellung fehlgeschlagen: %s", exc)

    Path(args.socket).parent.mkdir(parents=True, exist_ok=True)
    server = AgentServer(args.socket, agent, allowed_uids)
    if args.socket_group:
        os.chown(args.socket, -1, grp.getgrnam(args.socket_group).gr_gid)

    def _stop(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    log.info("lausche auf %s (Interface %s)", args.socket, iface)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        Path(args.socket).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
