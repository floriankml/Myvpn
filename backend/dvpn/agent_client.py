"""Client für den dvpn-agent (Unix-Socket, eine JSON-Zeile je Anfrage)."""

from __future__ import annotations

import json
import socket
from typing import Any


class AgentError(RuntimeError):
    pass


class AgentClient:
    def __init__(self, path: str, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout

    def call(self, op: str, **payload: Any) -> dict[str, Any]:
        req = json.dumps({"op": op, **payload}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.path)
                s.sendall(req)
                with s.makefile("rb") as f:
                    line = f.readline(1024 * 1024)
        except OSError as exc:
            raise AgentError("Agent nicht erreichbar") from exc
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AgentError("ungültige Antwort vom Agenten") from exc
        if not isinstance(resp, dict) or not resp.get("ok"):
            raise AgentError(str(resp.get("error", "Fehler")) if isinstance(resp, dict) else "Fehler")
        return resp

    # Komfortmethoden
    def ping(self) -> bool:
        try:
            self.call("ping")
            return True
        except AgentError:
            return False

    def status(self) -> dict[str, Any]:
        return self.call("status")

    def upsert_peer(self, public_key: str, allowed_ips: list[str], preshared_key: str | None) -> None:
        peer: dict[str, Any] = {"public_key": public_key, "allowed_ips": allowed_ips}
        if preshared_key:
            peer["preshared_key"] = preshared_key
        self.call("upsert_peer", peer=peer)

    def remove_peer(self, public_key: str) -> None:
        self.call("remove_peer", public_key=public_key)

    def sync(self, peers: list[dict[str, Any]]) -> dict[str, Any]:
        return self.call("sync", peers=peers)
