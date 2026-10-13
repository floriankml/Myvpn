from conftest import PASSWORD, login, make_client, make_user

from dvpn.deps import COOKIE_NAME


def test_login_success_sets_hardened_cookie(app):
    make_user(app, "alice")
    c = make_client(app)
    r = login(c, "alice")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert "password_hash" not in r.json()
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert c.get("/api/auth/me").json()["username"] == "alice"


def test_username_case_insensitive(app):
    make_user(app, "alice")
    assert login(make_client(app), "ALICE").status_code == 200


def test_wrong_password_and_unknown_user_same_response(app):
    make_user(app, "alice")
    c = make_client(app)
    r1 = login(c, "alice", "falsch-falsch-falsch")
    r2 = login(c, "niemand", "falsch-falsch-falsch")
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_inactive_user_cannot_login(app):
    make_user(app, "carol", active=False)
    assert login(make_client(app), "carol").status_code == 401


def test_unauthenticated_access_denied(app):
    c = make_client(app)
    for path in ["/api/auth/me", "/api/devices", "/api/status", "/api/servers", "/api/connection",
                 "/api/admin/users", "/api/auth/export"]:
        assert c.get(path).status_code == 401, path
    assert c.post("/api/devices", json={"name": "x", "public_key": "A" * 43 + "="}).status_code == 401


def test_forged_cookie_rejected(app):
    c = make_client(app)
    c.cookies.set(COOKIE_NAME, "gefaelscht")
    assert c.get("/api/auth/me").status_code == 401
    c.cookies.set(COOKIE_NAME, "x" * 5000)
    assert c.get("/api/auth/me").status_code == 401


def test_logout_invalidates_session_server_side(app):
    make_user(app, "alice")
    c = make_client(app)
    login(c, "alice")
    token = c.cookies.get(COOKIE_NAME)
    assert c.post("/api/auth/logout").status_code == 204
    c2 = make_client(app)
    c2.cookies.set(COOKIE_NAME, token)
    assert c2.get("/api/auth/me").status_code == 401


def test_session_token_stored_only_as_hash(app):
    make_user(app, "alice")
    c = make_client(app)
    login(c, "alice")
    token = c.cookies.get(COOKIE_NAME)
    import sqlite3

    path = app.state.settings.database_url.removeprefix("sqlite:///")
    raw = open(path, "rb").read()
    assert token.encode() not in raw
    assert PASSWORD.encode() not in raw
    con = sqlite3.connect(path)
    (h,) = con.execute("select password_hash from users").fetchone()
    assert h.startswith("$argon2id$")


def test_login_rate_limit_per_ip(app):
    make_user(app, "alice")
    c = make_client(app, "198.51.100.7")
    codes = [login(c, "alice", f"falsch-{i}-xxxxxxxx").status_code for i in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[10:] == [429, 429]
    # Auch das richtige Passwort wird jetzt geblockt
    assert login(c, "alice").status_code == 429


def test_login_rate_limit_per_account_across_ips(app):
    make_user(app, "alice")
    for i in range(10):
        c = make_client(app, f"198.51.100.{i + 10}")
        assert login(c, "alice", "falsch-falsch-falsch").status_code == 401
    assert login(make_client(app, "198.51.100.99"), "alice").status_code == 429


def test_change_password_flow(app):
    make_user(app, "alice", must_change=True)
    c = make_client(app, "10.8.0.9")
    login(c, "alice")
    other = make_client(app, "10.8.0.10")
    login(other, "alice")
    # Mit Initialpasswort keine Geräteverwaltung
    assert c.get("/api/devices").status_code == 403
    assert c.post("/api/auth/change-password",
                  json={"current_password": "falsch", "new_password": "neues-sicheres-pw-1"}).status_code == 400
    assert c.post("/api/auth/change-password",
                  json={"current_password": PASSWORD, "new_password": "kurz"}).status_code == 422
    r = c.post("/api/auth/change-password",
               json={"current_password": PASSWORD, "new_password": "neues-sicheres-pw-1"})
    assert r.status_code == 204
    assert c.get("/api/devices").status_code == 200
    assert other.get("/api/auth/me").status_code == 401  # andere Sitzungen beendet
    assert login(make_client(app), "alice", "neues-sicheres-pw-1").status_code == 200


def test_logout_all(app):
    make_user(app, "alice")
    a, b = make_client(app), make_client(app)
    login(a, "alice")
    login(b, "alice")
    assert a.post("/api/auth/logout-all").status_code == 204
    assert b.get("/api/auth/me").status_code == 401


def test_data_export_contains_no_secrets(alice):
    r = alice.get("/api/auth/export")
    assert r.status_code == 200
    body = r.text
    assert "argon2" not in body and "alice" in body
