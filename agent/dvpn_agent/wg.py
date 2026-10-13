"""Dünner Wrapper um das offizielle `wg`-Werkzeug.

Alle Aufrufe verwenden Argumentlisten (`shell=False`). Es findet keinerlei
String-Verkettung zu Shell-Befehlen statt. Geheimnisse (Pre-Shared-Keys)
werden über stdin übergeben, damit sie nicht in der Prozessliste auftauchen.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field


class WgError(RuntimeError):
    pass


@dataclass
class PeerState:
    public_key: str
    preshared_key: str | None
    allowed_ips: list[str]
    latest_handshake: int
    rx_bytes: int
    tx_bytes: int


@dataclass
class InterfaceState:
    public_key: str
    listen_port: int
    peers: dict[str, PeerState] = field(default_factory=dict)


class Wg:
    def __init__(self, interface: str, wg_binary: str = "wg", timeout: float = 10.0) -> None:
        self.interface = interface
        self.wg_binary = wg_binary
        self.timeout = timeout

    def _run(self, args: list[str], stdin: str | None = None) -> str:
        try:
            proc = subprocess.run(
                [self.wg_binary, *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WgError(f"wg konnte nicht ausgeführt werden: {exc.__class__.__name__}") from exc
        if proc.returncode != 0:
            # stderr kann Schlüsselmaterial nicht enthalten (PSK geht über stdin),
            # wird aber trotzdem gekürzt.
            raise WgError(f"wg {args[0]} fehlgeschlagen: {proc.stderr.strip()[:200]}")
        return proc.stdout

    def dump(self) -> InterfaceState:
        """Liest den aktuellen Zustand über `wg show <if> dump`.

        Die Endpunkte (reale Client-IP-Adressen) werden bewusst verworfen:
        Sie verlassen den Agenten nie (Datensparsamkeit).
        """
        out = self._run(["show", self.interface, "dump"])
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if not lines:
            raise WgError("leere Ausgabe von wg show")
        head = lines[0].split("\t")
        if len(head) < 4:
            raise WgError("unerwartetes Format von wg show")
        state = InterfaceState(public_key=head[1], listen_port=int(head[2]))
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) < 8:
                continue
            pub, psk, _endpoint, allowed, handshake, rx, tx = cols[:7]
            state.peers[pub] = PeerState(
                public_key=pub,
                preshared_key=None if psk == "(none)" else psk,
                allowed_ips=sorted(a for a in allowed.split(",") if a and a != "(none)"),
                latest_handshake=int(handshake),
                rx_bytes=int(rx),
                tx_bytes=int(tx),
            )
        return state

    def set_peer(self, public_key: str, allowed_ips: list[str], preshared_key: str | None) -> None:
        # "/dev/null" entfernt laut wg(8) einen vorhandenen Pre-Shared-Key.
        args = ["set", self.interface, "peer", public_key]
        args += ["preshared-key", "/dev/stdin" if preshared_key is not None else "/dev/null"]
        args += ["allowed-ips", ",".join(allowed_ips)]
        self._run(args, stdin=(preshared_key + "\n") if preshared_key is not None else None)

    def remove_peer(self, public_key: str) -> None:
        self._run(["set", self.interface, "peer", public_key, "remove"])
