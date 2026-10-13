"""Test-Fixtures.

Das Backend spricht in den Tests mit dem ECHTEN Agenten-Code über einen
echten Unix-Socket. Nur das Kernel-Interface wird durch FakeWg ersetzt
(echte WireGuard-Tests: siehe tests/integration im Projektwurzelverzeichnis).
"""

from __future__ import annotations

import base64
import ipaddress
import os
import secrets
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))

from dvpn_agent.server import Agent, AgentServer  # noqa: E402
from dvpn_agent.wg import InterfaceState, PeerState  # noqa: E402

from dvpn.config import Settings  # noqa: E402
from dvpn.main import create_app  # noqa: E402
from dvpn.models import User  # noqa: E402
from dvpn.security import hash_password  # noqa: E402

SERVER_PUB = base64.b64encode(b"S" * 32).decode()
PASSWORD = "korrekt-pferd-batterie"


def rand_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


class FakeWg:
    def __init__(self) -> None:
        self.peers: dict[str, PeerState] = {}
        self.fail = False

    def dump(self) -> InterfaceState:
        if self.fail:
            from dvpn_agent.wg import WgError

            raise WgError("Interface fehlt")
        st = InterfaceState(public_key=SERVER_PUB, listen_port=51820)
        st.peers = dict(self.peers)
        return st

    def set_peer(self, pub, ips, psk):
        old = self.peers.get(pub)
        self.peers[pub] = PeerState(pub, psk, sorted(ips), old.latest_handshake if old else 0, 0, 0)

    def remove_peer(self, pub):
        self.peers.pop(pub, None)


@pytest.fixture
def agent_env():
    d = tempfile.mkdtemp(prefix="dvpn-test-")
    wg = FakeWg()
    nets = [ipaddress.ip_network("10.8.0.0/24"), ipaddress.ip_network("fd42:4242:4242::/64")]
    reserved = {ipaddress.ip_address("10.8.0.1"), ipaddress.ip_address("fd42:4242:4242::1")}
    agent = Agent(wg, Path(d) / "peers.json", nets, reserved)
    sock = os.path.join(d, "agent.sock")
    srv = AgentServer(sock, agent, set())
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield {"wg": wg, "agent": agent, "socket": sock, "dir": d}
    srv.shutdown()
    srv.server_close()
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def settings(agent_env, tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        agent_socket=agent_env["socket"],
        endpoint_host="vpn.example.de",
        subnet_v4="10.8.0.0/24",
        subnet_v6="fd42:4242:4242::/64",
        reconcile_interval=0,
        cookie_secure=False,
        max_devices_per_user=3,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


def make_user(app, username: str, admin: bool = False, must_change: bool = False, active: bool = True) -> User:
    with app.state.db.sessionmaker() as db:
        u = User(username=username, password_hash=hash_password(PASSWORD), is_admin=admin,
                 must_change_password=must_change, is_active=active)
        db.add(u)
        db.commit()
        return u


def make_client(app, client_ip: str = "127.0.0.1") -> TestClient:
    # client=(ip, port) simuliert die Quell-IP (z. B. aus dem VPN-Tunnel)
    return TestClient(app, client=(client_ip, 50000), base_url="http://testserver")


def login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture
def alice(app):
    make_user(app, "alice")
    c = make_client(app, "10.8.0.50")
    assert login(c, "alice").status_code == 200
    return c


@pytest.fixture
def bob(app):
    make_user(app, "bob")
    c = make_client(app, "10.8.0.51")
    assert login(c, "bob").status_code == 200
    return c


@pytest.fixture
def admin(app):
    make_user(app, "root-admin", admin=True)
    c = make_client(app, "127.0.0.1")
    assert login(c, "root-admin").status_code == 200
    return c
