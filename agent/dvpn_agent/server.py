"""dvpn-agent: kleiner privilegierter Dienst, der WireGuard-Peers verwaltet.

Sicherheitsmodell
-----------------
* Läuft als eigener Systembenutzer mit nur CAP_NET_ADMIN (siehe systemd-Unit),
  nicht als root und ohne Shell.
* Erreichbar ausschließlich über einen Unix-Socket (kein Netzwerkport).
  Zugriff wird über Dateirechte UND SO_PEERCRED (erlaubte UIDs) beschränkt.
* Kennt nur eine feste, kleine Menge an Operationen. Es gibt keine Operation,
  die beliebige Befehle oder Argumente entgegennimmt.
* Jede Eingabe wird erneut validiert (siehe validation.py).
* Der gewünschte Peer-Zustand wird lokal persistiert, damit das VPN nach einem
  Neustart auch dann funktioniert, wenn das Backend (noch) nicht läuft.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import socketserver
import struct
import tempfile
import threading
from pathlib import Path
from typing import Any

from .validation import ValidationError, validate_key, validate_peer
from .wg import Wg, WgError

log = logging.getLogger("dvpn-agent")

MAX_REQUEST_BYTES = 1024 * 1024
MAX_PEERS = 1000


class Agent:
    """Geschäftslogik ohne Socket-Code (separat testbar)."""

    def __init__(
        self,
        wg: Wg,
        state_file: Path,
        allowed_nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
        reserved: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
    ) -> None:
        self.wg = wg
        self.state_file = state_file
        self.allowed_nets = allowed_nets
        self.reserved = reserved
        self.lock = threading.Lock()
        self.desired: dict[str, dict[str, Any]] = {}

    # ---------- Persistenz ----------
    def load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            peers = [validate_peer(p, self.allowed_nets, self.reserved) for p in data.get("peers", [])]
        except (OSError, ValueError, ValidationError) as exc:
            log.error("Zustandsdatei unlesbar, starte leer: %s", exc.__class__.__name__)
            return
        self.desired = {p["public_key"]: p for p in peers}  # type: ignore[misc]

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "peers": list(self.desired.values())}, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.state_file.parent, prefix=".peers-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.state_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---------- Anwenden ----------
    def apply(self) -> dict[str, int]:
        """Gleicht das Interface mit dem gewünschten Zustand ab (idempotent)."""
        current = self.wg.dump()
        added = updated = removed = 0
        for key, peer in self.desired.items():
            cur = current.peers.get(key)
            want_ips = sorted(peer["allowed_ips"])
            want_psk = peer.get("preshared_key")
            if cur is None:
                self.wg.set_peer(key, want_ips, want_psk)
                added += 1
            elif cur.allowed_ips != want_ips or cur.preshared_key != want_psk:
                self.wg.set_peer(key, want_ips, want_psk)
                updated += 1
        for key in current.peers:
            if key not in self.desired:
                self.wg.remove_peer(key)
                removed += 1
        return {"added": added, "updated": updated, "removed": removed}

    # ---------- Operationen ----------
    def handle(self, req: Any) -> dict[str, Any]:
        if not isinstance(req, dict) or not isinstance(req.get("op"), str):
            raise ValidationError("ungültige Anfrage")
        op = req["op"]
        if op == "ping":
            return {"ok": True}
        if op == "info":
            st = self.wg.dump()
            return {"ok": True, "public_key": st.public_key, "listen_port": st.listen_port, "peers": len(st.peers)}
        if op == "status":
            st = self.wg.dump()
            return {
                "ok": True,
                "public_key": st.public_key,
                "listen_port": st.listen_port,
                # Absichtlich OHNE Endpoint (reale Client-IP).
                "peers": [
                    {
                        "public_key": p.public_key,
                        "latest_handshake": p.latest_handshake,
                        "rx_bytes": p.rx_bytes,
                        "tx_bytes": p.tx_bytes,
                    }
                    for p in st.peers.values()
                ],
            }
        with self.lock:
            if op == "upsert_peer":
                peer = validate_peer(req.get("peer"), self.allowed_nets, self.reserved)
                self._check_ip_conflicts([peer], replacing=str(peer["public_key"]))
                if peer["public_key"] not in self.desired and len(self.desired) >= MAX_PEERS:
                    raise ValidationError("zu viele Peers")
                self.desired[str(peer["public_key"])] = peer
            elif op == "remove_peer":
                key = validate_key(req.get("public_key"), "öffentlicher Schlüssel")
                self.desired.pop(key, None)
            elif op == "sync":
                raw = req.get("peers")
                if not isinstance(raw, list) or len(raw) > MAX_PEERS:
                    raise ValidationError("ungültige Peer-Liste")
                peers = [validate_peer(p, self.allowed_nets, self.reserved) for p in raw]
                self._check_ip_conflicts(peers, replacing=None, against_self=True)
                self.desired = {str(p["public_key"]): p for p in peers}
            else:
                raise ValidationError("unbekannte Operation")
            self._save_state()
            result = self.apply()
        return {"ok": True, **result}

    def _check_ip_conflicts(
        self, peers: list[dict[str, Any]], replacing: str | None, against_self: bool = False
    ) -> None:
        used: dict[str, str] = {}
        if not against_self:
            for key, p in self.desired.items():
                if key != replacing:
                    for ip in p["allowed_ips"]:
                        used[ip] = key
        for p in peers:
            for ip in p["allowed_ips"]:
                if ip in used and used[ip] != p["public_key"]:
                    raise ValidationError("Adresse bereits vergeben")
                used[ip] = p["public_key"]
        if against_self and len({p["public_key"] for p in peers}) != len(peers):
            raise ValidationError("doppelter Schlüssel")


class _Handler(socketserver.StreamRequestHandler):
    server: "AgentServer"

    def handle(self) -> None:
        self.connection.settimeout(10)
        try:
            if not self.server.peer_allowed(self.connection):
                self._reply({"ok": False, "error": "nicht berechtigt"})
                return
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(line) > MAX_REQUEST_BYTES:
                self._reply({"ok": False, "error": "Anfrage zu groß"})
                return
            req = json.loads(line)
            self._reply(self.server.agent.handle(req))
        except ValidationError as exc:
            self._reply({"ok": False, "error": str(exc)})
        except json.JSONDecodeError:
            self._reply({"ok": False, "error": "ungültiges JSON"})
        except WgError as exc:
            log.error("%s", exc)
            self._reply({"ok": False, "error": "WireGuard-Fehler"})
        except Exception:  # noqa: BLE001 - Agent darf nicht abstürzen
            log.exception("unerwarteter Fehler")
            self._reply({"ok": False, "error": "interner Fehler"})

    def _reply(self, obj: dict[str, Any]) -> None:
        try:
            self.wfile.write(json.dumps(obj).encode() + b"\n")
        except OSError:
            pass


class AgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, agent: Agent, allowed_uids: set[int]) -> None:
        self.agent = agent
        self.allowed_uids = allowed_uids
        if os.path.exists(path):
            os.unlink(path)
        old_umask = os.umask(0o117)  # Socket: rw für Eigentümer und Gruppe
        try:
            super().__init__(path, _Handler)
        finally:
            os.umask(old_umask)

    def peer_allowed(self, conn: socket.socket) -> bool:
        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        return uid == 0 or uid == os.getuid() or uid in self.allowed_uids
