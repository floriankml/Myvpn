import time

from conftest import SERVER_PUB, make_client, make_user, login, rand_key

from dvpn.services import render_config


def create(c, name="Pixel", key=None):
    return c.post("/api/devices", json={"name": name, "public_key": key or rand_key()})


def test_create_device_applies_peer_and_returns_template(alice, agent_env):
    key = rand_key()
    r = create(alice, "Pixel 8", key)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["applied"] is True
    dev, conf = body["device"], body["config"]
    assert dev["ipv4"] == "10.8.0.2" and dev["ipv6"] == "fd42:4242:4242::2"
    # Peer wurde im (simulierten) Kernel angelegt – inkl. PSK und nur /32 + /128
    peer = agent_env["wg"].peers[key]
    assert peer.allowed_ips == ["10.8.0.2/32", "fd42:4242:4242::2/128"]
    assert peer.preshared_key == conf["peer"]["preshared_key"]
    assert conf["peer"]["public_key"] == SERVER_PUB
    assert conf["peer"]["endpoint"] == "vpn.example.de:51820"
    assert conf["peer"]["allowed_ips"] == ["0.0.0.0/0", "::/0"]
    assert conf["interface"]["dns"] == ["10.8.0.1", "fd42:4242:4242::1"]
    # Server kennt den privaten Schlüssel nicht
    assert "private" not in r.text.lower()


def test_rendered_config_format(alice):
    conf = create(alice).json()["config"]
    text = render_config(conf, "PRIVATE")
    assert text.startswith("[Interface]\nPrivateKey = PRIVATE\nAddress = 10.8.0.2/32, fd42:4242:4242::2/128\n")
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in text
    assert "PersistentKeepalive = 25" in text


def test_addresses_are_unique_and_reused_after_revoke(alice):
    ids = [create(alice, f"g{i}").json()["device"] for i in range(3)]
    assert [d["ipv4"] for d in ids] == ["10.8.0.2", "10.8.0.3", "10.8.0.4"]
    alice.post(f"/api/devices/{ids[1]['id']}/revoke")
    assert create(alice, "neu").json()["device"]["ipv4"] == "10.8.0.3"


def test_device_limit(alice):
    for i in range(3):
        assert create(alice, f"g{i}").status_code == 201
    r = create(alice, "zu viel")
    assert r.status_code == 409


def test_duplicate_public_key_rejected(alice, bob):
    key = rand_key()
    assert create(alice, "a", key).status_code == 201
    assert create(bob, "b", key).status_code == 409


def test_server_key_cannot_be_used_as_device_key(alice):
    assert create(alice, "a", SERVER_PUB).status_code == 400


def test_revoke_removes_peer_immediately(alice, agent_env):
    key = rand_key()
    dev = create(alice, "a", key).json()["device"]
    r = alice.post(f"/api/devices/{dev['id']}/revoke")
    assert r.json() == {"revoked": True, "applied": True}
    assert key not in agent_env["wg"].peers
    listed = alice.get("/api/devices").json()
    assert listed[0]["revoked_at"] is not None
    assert alice.get(f"/api/devices/{dev['id']}/config").status_code == 410


def test_user_cannot_see_or_revoke_foreign_devices(alice, bob, agent_env):
    key = rand_key()
    dev = create(alice, "alices", key).json()["device"]
    assert bob.get("/api/devices").json() == []
    assert bob.get("/api/devices?all=true").json() == []  # Nicht-Admins ignorieren ?all
    assert bob.get(f"/api/devices/{dev['id']}/config").status_code == 404
    assert bob.post(f"/api/devices/{dev['id']}/revoke").status_code == 404
    assert key in agent_env["wg"].peers
    assert bob.post("/api/devices/99999/revoke").status_code == 404


def test_admin_can_list_and_revoke_all_but_not_read_configs(alice, admin, agent_env):
    key = rand_key()
    dev = create(alice, "alices", key).json()["device"]
    all_devices = admin.get("/api/devices?all=true").json()
    assert all_devices[0]["owner"] == "alice"
    assert admin.get(f"/api/devices/{dev['id']}/config").status_code == 404
    assert admin.post(f"/api/devices/{dev['id']}/revoke").status_code == 200
    assert key not in agent_env["wg"].peers


def test_live_status_from_kernel(alice, agent_env):
    key = rand_key()
    create(alice, "a", key)
    p = agent_env["wg"].peers[key]
    p.latest_handshake, p.rx_bytes, p.tx_bytes = int(time.time()) - 10, 1234, 5678
    d = alice.get("/api/devices").json()[0]
    assert d["connected"] is True and d["rx_bytes"] == 1234
    p.latest_handshake = int(time.time()) - 600
    assert alice.get("/api/devices").json()[0]["connected"] is False


def test_agent_down_create_fails_cleanly(alice, agent_env):
    import dvpn.services as svc

    svc._server_key_cache.clear()
    agent_env["wg"].fail = True
    r = create(alice)
    assert r.status_code == 503
    agent_env["wg"].fail = False


def test_revoke_while_agent_down_is_applied_by_reconcile(app, alice, agent_env):
    from dvpn.main import reconcile_once

    key = rand_key()
    dev = create(alice, "a", key).json()["device"]
    real = app.state.agent.path
    app.state.agent.path = "/nonexistent.sock"
    r = alice.post(f"/api/devices/{dev['id']}/revoke")
    assert r.json() == {"revoked": True, "applied": False}
    assert key in agent_env["wg"].peers  # noch aktiv, Agent war weg
    app.state.agent.path = real
    reconcile_once(app)
    assert key not in agent_env["wg"].peers


def test_reconcile_restores_peers_after_kernel_reset(app, alice, agent_env):
    """Simuliert Neustart: Kernel-Interface leer, Agent-Zustand verloren."""
    from dvpn.main import reconcile_once

    keys = [rand_key() for _ in range(2)]
    for k in keys:
        create(alice, "a", k)
    agent_env["wg"].peers.clear()
    agent_env["agent"].desired.clear()
    reconcile_once(app)
    assert set(agent_env["wg"].peers) == set(keys)


def test_reconcile_removes_unknown_peers(app, agent_env):
    from dvpn.main import reconcile_once
    from dvpn_agent.wg import PeerState

    k = rand_key()
    agent_env["wg"].peers[k] = PeerState(k, None, ["10.8.0.77/32"], 0, 0, 0)
    reconcile_once(app)
    assert k not in agent_env["wg"].peers


def test_connection_detection(app, alice):
    dev = create(alice, "Laptop").json()["device"]
    via = make_client(app, dev["ipv4"])
    via.cookies = alice.cookies
    r = via.get("/api/connection").json()
    assert r["via_vpn"] is True and r["device"]["name"] == "Laptop"
    direct = make_client(app, "203.0.113.5")
    direct.cookies = alice.cookies
    r = direct.get("/api/connection").json()
    assert r == {"via_vpn": False, "client_ip": "203.0.113.5", "device": None}


def test_connection_does_not_reveal_foreign_device(app, alice):
    dev = create(alice, "Geheim").json()["device"]
    make_user(app, "mallory")
    m = make_client(app, dev["ipv4"])
    login(m, "mallory")
    r = m.get("/api/connection").json()
    assert r["via_vpn"] is True and r["device"] is None


def test_status_and_servers(alice, admin):
    st = alice.get("/api/status").json()
    assert st["agent"] is True and st["listen_port"] == 51820
    assert st["peers_configured"] is None  # nur für Admins
    assert admin.get("/api/status").json()["peers_configured"] == 0
    srv = alice.get("/api/servers").json()
    assert srv[0]["id"] == "de-1" and srv[0]["online"] is True
