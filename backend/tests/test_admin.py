from conftest import login, make_client, make_user, rand_key


def test_normal_user_cannot_use_admin_api(alice):
    assert alice.get("/api/admin/users").status_code == 403
    assert alice.post("/api/admin/users", json={"username": "evil", "is_admin": True}).status_code == 403
    assert alice.patch("/api/admin/users/1", json={"is_admin": True}).status_code == 403


def test_admin_only_from_vpn_or_localhost(app):
    make_user(app, "boss", admin=True)
    internet = make_client(app, "203.0.113.9")
    login(internet, "boss")
    assert internet.get("/api/admin/users").status_code == 403
    vpn = make_client(app, "10.8.0.33")
    login(vpn, "boss")
    assert vpn.get("/api/admin/users").status_code == 200
    v6 = make_client(app, "fd42:4242:4242::33")
    login(v6, "boss")
    assert v6.get("/api/admin/users").status_code == 200


def test_create_user_returns_one_time_password(admin, app):
    r = admin.post("/api/admin/users", json={"username": "Neu.Nutzer"})
    assert r.status_code == 201
    pw = r.json()["initial_password"]
    assert r.json()["user"]["username"] == "neu.nutzer"
    assert r.json()["user"]["must_change_password"] is True
    c = make_client(app)
    assert login(c, "neu.nutzer", pw).status_code == 200
    assert admin.post("/api/admin/users", json={"username": "neu.nutzer"}).status_code == 409


def test_invalid_usernames(admin):
    for name in ["ab", "a" * 40, "root;id", "../x", "Ünicode"]:
        assert admin.post("/api/admin/users", json={"username": name}).status_code == 422, name


def test_deactivate_user_removes_vpn_access_and_sessions(admin, alice, agent_env):
    key = rand_key()
    alice.post("/api/devices", json={"name": "a", "public_key": key})
    assert key in agent_env["wg"].peers
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    r = admin.patch(f"/api/admin/users/{users['alice']['id']}", json={"is_active": False})
    assert r.status_code == 200
    assert key not in agent_env["wg"].peers
    assert alice.get("/api/auth/me").status_code == 401
    admin.patch(f"/api/admin/users/{users['alice']['id']}", json={"is_active": True})
    assert key in agent_env["wg"].peers


def test_delete_user(admin, alice, agent_env):
    key = rand_key()
    alice.post("/api/devices", json={"name": "a", "public_key": key})
    uid = {u["username"]: u for u in admin.get("/api/admin/users").json()}["alice"]["id"]
    assert admin.delete(f"/api/admin/users/{uid}").json()["deleted"] is True
    assert key not in agent_env["wg"].peers


def test_admin_cannot_lock_self_out(admin):
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert admin.delete(f"/api/admin/users/{me['id']}").status_code == 400


def test_reset_password(admin, alice, app):
    uid = {u["username"]: u for u in admin.get("/api/admin/users").json()}["alice"]["id"]
    pw = admin.post(f"/api/admin/users/{uid}/reset-password").json()["initial_password"]
    assert alice.get("/api/auth/me").status_code == 401
    assert login(make_client(app), "alice", pw).json()["must_change_password"] is True
