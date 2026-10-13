"""Sicherheitsprüfungen der API: CSRF, Header, Eingabevalidierung, Fehlerbehandlung."""

import pytest
from conftest import make_client, rand_key


def test_security_headers(alice):
    r = alice.get("/api/auth/me")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_cross_origin_post_rejected(alice):
    r = alice.post("/api/devices", json={"name": "x", "public_key": rand_key()},
                   headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = alice.post("/api/devices", json={"name": "x", "public_key": rand_key()},
                   headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_post_allowed(alice):
    r = alice.post("/api/devices", json={"name": "x", "public_key": rand_key()},
                   headers={"Origin": "http://testserver"})
    assert r.status_code == 201


def test_form_post_rejected(alice):
    r = alice.post("/api/devices", content="name=x&public_key=y",
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


@pytest.mark.parametrize("payload", [
    {"name": "x", "public_key": "nicht-base64"},
    {"name": "x", "public_key": "A" * 44},
    {"name": "x", "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="},  # Null-Schlüssel
    {"name": "", "public_key": rand_key()},
    {"name": "x" * 41, "public_key": rand_key()},
    {"name": "<script>alert(1)</script>", "public_key": rand_key()},
    {"name": "a; rm -rf /", "public_key": rand_key()},
    {"name": "x\n[Peer]", "public_key": rand_key()},
    {"name": "x", "public_key": rand_key(), "ipv4": "10.8.0.1"},  # Massenzuweisung
    {"name": "x", "public_key": rand_key(), "allowed_ips": ["0.0.0.0/0"]},
    {"name": "x", "public_key": rand_key() + "\nAllowedIPs = 0.0.0.0/0"},
])
def test_device_input_validation(alice, payload):
    r = alice.post("/api/devices", json=payload)
    assert r.status_code == 422
    # Eingabewerte werden nicht zurückgespiegelt
    assert "rm -rf" not in r.text and "<script>" not in r.text


def test_validation_error_does_not_echo_password(app):
    c = make_client(app)
    r = c.post("/api/auth/login", json={"username": "a", "password": "geheim123", "extra": 1})
    assert r.status_code == 422
    assert "geheim123" not in r.text


def test_global_rate_limit(app, alice):
    app.state.limits["global"].limit = 5
    codes = [alice.get("/api/auth/me").status_code for _ in range(7)]
    assert codes[-1] == 429


def test_openapi_disabled_by_default(app):
    c = make_client(app)
    assert c.get("/api/docs").status_code in (401, 404)
    assert c.get("/api/openapi.json").status_code in (401, 404)


def test_health_is_public_and_minimal(app):
    r = make_client(app).get("/api/health")
    assert r.json() == {"status": "ok"}


def test_internal_errors_are_generic(app, alice, monkeypatch):
    from dvpn.routers import devices

    def boom(*a, **k):
        raise RuntimeError("geheimer Stacktrace /etc/dvpn")

    monkeypatch.setattr(devices, "live_status", boom)
    c = make_client(app, "10.8.0.50")
    c.cookies = alice.cookies
    r = TestClientNoRaise(app, alice).get("/api/devices")
    assert r.status_code == 500
    assert r.json() == {"detail": "Interner Fehler"}


def TestClientNoRaise(app, logged_in):
    from fastapi.testclient import TestClient

    c = TestClient(app, raise_server_exceptions=False, client=("10.8.0.50", 1))
    c.cookies = logged_in.cookies
    return c
