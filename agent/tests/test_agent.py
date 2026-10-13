import base64
import ipaddress
import json
import os
import socket
import threading

import pytest

from dvpn_agent.server import Agent, AgentServer
from dvpn_agent.validation import ValidationError, validate_allowed_ips, validate_key
from dvpn_agent.wg import InterfaceState, PeerState

NETS = [ipaddress.ip_network("10.8.0.0/24"), ipaddress.ip_network("fd42:4242:4242::/64")]
RESERVED = {ipaddress.ip_address("10.8.0.1"), ipaddress.ip_address("fd42:4242:4242::1")}


def key(n: int) -> str:
    return base64.b64encode(bytes([n]) * 32).decode()


class FakeWg:
    """Simuliert den Kernel-Zustand eines WireGuard-Interfaces."""

    def __init__(self):
        self.peers: dict[str, PeerState] = {}
        self.calls: list[tuple] = []

    def dump(self):
        st = InterfaceState(public_key=key(200), listen_port=51820)
        st.peers = {k: PeerState(**vars(v)) for k, v in self.peers.items()}
        return st

    def set_peer(self, pub, ips, psk):
        self.calls.append(("set", pub, tuple(ips), psk))
        old = self.peers.get(pub)
        self.peers[pub] = PeerState(pub, psk, sorted(ips), old.latest_handshake if old else 0, 0, 0)

    def remove_peer(self, pub):
        self.calls.append(("remove", pub))
        self.peers.pop(pub, None)


@pytest.fixture
def agent(tmp_path):
    return Agent(FakeWg(), tmp_path / "state" / "peers.json", NETS, RESERVED)


def peer(n, ip4, ip6=None, psk=None):
    p = {"public_key": key(n), "allowed_ips": [ip4] + ([ip6] if ip6 else [])}
    if psk:
        p["preshared_key"] = psk
    return p


# ---------- Validierung ----------
@pytest.mark.parametrize("bad", [
    "", "abc", None, 5, key(1)[:-1], key(1) + "=", "A" * 44,
    base64.b64encode(bytes(32)).decode(),  # Null-Schlüssel
    "../../etc/passwd", "--help", key(1).replace("A", "A;rm -rf /", 1),
])
def test_invalid_keys_rejected(bad):
    with pytest.raises(ValidationError):
        validate_key(bad)


def test_valid_key():
    assert validate_key(key(1)) == key(1)


@pytest.mark.parametrize("ips", [
    ["0.0.0.0/0"], ["10.8.0.0/24"], ["10.8.1.5/32"], ["10.8.0.1/32"], ["10.8.0.0/32"],
    ["10.8.0.255/32"], ["fd42:4242:4242::1/128"], ["2001:db8::1/128"], ["10.8.0.2/32", "10.8.0.3/32"],
    ["10.8.0.2"], [], ["10.8.0.2/32", "fd42:4242:4242::2/128", "10.8.0.3/32"], "10.8.0.2/32",
    ["10.8.0.2/32,0.0.0.0/0"],
])
def test_invalid_allowed_ips(ips):
    if ips == ["10.8.0.2"]:  # ohne Präfix ist /32 – das ist gültig
        assert validate_allowed_ips(ips, NETS, RESERVED) == ["10.8.0.2/32"]
        return
    with pytest.raises(ValidationError):
        validate_allowed_ips(ips, NETS, RESERVED)


def test_valid_allowed_ips():
    assert validate_allowed_ips(["10.8.0.2/32", "fd42:4242:4242::2/128"], NETS, RESERVED) == [
        "10.8.0.2/32", "fd42:4242:4242::2/128"]


# ---------- Operationen ----------
def test_upsert_remove_and_persist(agent, tmp_path):
    r = agent.handle({"op": "upsert_peer", "peer": peer(1, "10.8.0.2/32", "fd42:4242:4242::2/128", key(50))})
    assert r == {"ok": True, "added": 1, "updated": 0, "removed": 0}
    assert agent.wg.peers[key(1)].preshared_key == key(50)
    state = tmp_path / "state" / "peers.json"
    assert oct(state.stat().st_mode & 0o777) == "0o600"
    assert json.loads(state.read_text())["peers"][0]["public_key"] == key(1)

    r = agent.handle({"op": "remove_peer", "public_key": key(1)})
    assert r["removed"] == 1 and key(1) not in agent.wg.peers
    assert json.loads(state.read_text())["peers"] == []


def test_ip_conflict_rejected(agent):
    agent.handle({"op": "upsert_peer", "peer": peer(1, "10.8.0.2/32")})
    with pytest.raises(ValidationError):
        agent.handle({"op": "upsert_peer", "peer": peer(2, "10.8.0.2/32")})
    # Gleicher Peer darf seine eigene Adresse behalten/aktualisieren
    agent.handle({"op": "upsert_peer", "peer": peer(1, "10.8.0.2/32", psk=key(9))})
    assert agent.wg.peers[key(1)].preshared_key == key(9)


def test_sync_removes_unknown_peers_and_is_idempotent(agent):
    agent.wg.peers[key(99)] = PeerState(key(99), None, ["10.8.0.99/32"], 0, 0, 0)  # fremder Peer
    r = agent.handle({"op": "sync", "peers": [peer(1, "10.8.0.2/32"), peer(2, "10.8.0.3/32")]})
    assert r == {"ok": True, "added": 2, "updated": 0, "removed": 1}
    r = agent.handle({"op": "sync", "peers": [peer(1, "10.8.0.2/32"), peer(2, "10.8.0.3/32")]})
    assert r == {"ok": True, "added": 0, "updated": 0, "removed": 0}


def test_sync_rejects_duplicates(agent):
    with pytest.raises(ValidationError):
        agent.handle({"op": "sync", "peers": [peer(1, "10.8.0.2/32"), peer(2, "10.8.0.2/32")]})
    with pytest.raises(ValidationError):
        agent.handle({"op": "sync", "peers": [peer(1, "10.8.0.2/32"), peer(1, "10.8.0.3/32")]})


def test_unknown_op_and_fields(agent):
    for req in [{"op": "exec", "cmd": "id"}, {"op": 1}, [], "ping",
                {"op": "upsert_peer", "peer": {**peer(1, "10.8.0.2/32"), "endpoint": "1.2.3.4:1"}}]:
        with pytest.raises(ValidationError):
            agent.handle(req)


def test_status_never_contains_endpoint(agent):
    agent.handle({"op": "upsert_peer", "peer": peer(1, "10.8.0.2/32")})
    st = agent.handle({"op": "status"})
    assert set(st["peers"][0]) == {"public_key", "latest_handshake", "rx_bytes", "tx_bytes"}


def test_restore_after_restart(agent, tmp_path):
    agent.handle({"op": "upsert_peer", "peer": peer(1, "10.8.0.2/32")})
    fresh = Agent(FakeWg(), agent.state_file, NETS, RESERVED)  # "Neustart": Kernel-Zustand leer
    fresh.load_state()
    assert fresh.apply() == {"added": 1, "updated": 0, "removed": 0}
    assert key(1) in fresh.wg.peers


def test_corrupt_state_file_is_ignored(agent):
    agent.state_file.parent.mkdir(parents=True)
    agent.state_file.write_text('{"peers": [{"public_key": "x"}]}')
    agent.load_state()
    assert agent.desired == {}


# ---------- Socket ----------
def test_socket_roundtrip_and_errors(agent, tmp_path):
    path = str(tmp_path / "a.sock")
    srv = AgentServer(path, agent, set())
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert oct(os.stat(path).st_mode & 0o777) == "0o660"

        def call(raw: bytes):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(path)
                s.sendall(raw)
                return json.loads(s.makefile().readline())

        assert call(b'{"op":"ping"}\n') == {"ok": True}
        assert call(b"kein json\n")["ok"] is False
        assert call(b'{"op":"rm -rf"}\n') == {"ok": False, "error": "unbekannte Operation"}
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(os.geteuid() != 0, reason="benötigt root, um eine fremde UID zu simulieren")
def test_socket_rejects_foreign_uid(agent, tmp_path):
    """Echter Test mit SO_PEERCRED: ein Kindprozess mit UID 65534 (nobody)."""
    import tempfile
    sockdir = tempfile.mkdtemp(prefix="dvpn-agent-test-")  # für UID 65534 erreichbar
    os.chmod(sockdir, 0o755)
    path = os.path.join(sockdir, "b.sock")
    srv = AgentServer(path, agent, allowed_uids=set())
    os.chmod(path, 0o666)  # Dateirechte bewusst öffnen, damit nur SO_PEERCRED schützt
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # Kind
        try:
            os.setgid(65534)
            os.setuid(65534)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(path)
                s.sendall(b'{"op":"ping"}\n')
                os.write(w, s.makefile().readline().encode())
        finally:
            os._exit(0)
    os.close(w)
    os.waitpid(pid, 0)
    answer = os.read(r, 4096).decode()
    srv.shutdown()
    srv.server_close()
    import shutil
    shutil.rmtree(sockdir)
    assert json.loads(answer) == {"ok": False, "error": "nicht berechtigt"}
