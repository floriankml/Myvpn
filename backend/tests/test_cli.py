"""Tests der Admin-CLI (dvpn-admin) gegen echten Agent-Code über einen Unix-Socket."""

import shutil
import sqlite3

import pytest

from dvpn import cli
from dvpn.config import get_settings

pytestmark = pytest.mark.skipif(shutil.which("wg") is None, reason="benötigt wg (wireguard-tools)")


@pytest.fixture
def cli_env(agent_env, tmp_path, monkeypatch):
    db = tmp_path / "cli.db"
    monkeypatch.setenv("DVPN_DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("DVPN_AGENT_SOCKET", agent_env["socket"])
    monkeypatch.setenv("DVPN_ENDPOINT_HOST", "vpn.example.de")
    monkeypatch.setenv("DVPN_SUBNET_V6", "fd42:4242:4242::/64")
    get_settings.cache_clear()
    import dvpn.services as svc

    svc._server_key_cache.clear()
    cli.main(["create-user", "anna", "--generate"])
    yield db
    get_settings.cache_clear()


def device_count(db) -> int:
    return sqlite3.connect(db).execute("select count(*) from devices").fetchone()[0]


def test_create_device_stdout_is_pure_config(cli_env, capsys, agent_env):
    cli.main(["create-device", "anna", "Laptop"])
    out, err = capsys.readouterr()
    assert out.startswith("[Interface]\nPrivateKey = ")
    assert "Gerät #1" not in out and "Gerät #1" in err  # Hinweise nur auf stderr
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in out
    priv = out.split("PrivateKey = ")[1].split("\n")[0]
    assert priv.encode() not in open(cli_env, "rb").read()  # privater Schlüssel nicht in der DB
    assert len(agent_env["wg"].peers) == 1


def test_unwritable_output_creates_no_device(cli_env, tmp_path):
    """Kann die Datei nicht geschrieben werden, darf KEIN Gerät entstehen (sonst wäre der
    private Schlüssel verloren). Nicht existierendes Verzeichnis: scheitert auch als root."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["create-device", "anna", "X", "-o", str(tmp_path / "fehlt" / "x.conf")])
    assert "kann nicht geschrieben werden" in str(exc.value)
    assert device_count(cli_env) == 0


def test_existing_output_file_is_not_overwritten(cli_env, tmp_path):
    target = tmp_path / "vorhanden.conf"
    target.write_text("alt")
    with pytest.raises(SystemExit):
        cli.main(["create-device", "anna", "X", "-o", str(target)])
    assert target.read_text() == "alt"
    assert device_count(cli_env) == 0


def test_output_file_mode_0600(cli_env, tmp_path):
    target = tmp_path / "neu.conf"
    cli.main(["create-device", "anna", "Handy", "-o", str(target)])
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert target.read_text().startswith("[Interface]")


def test_revoke_and_list(cli_env, capsys, agent_env):
    cli.main(["create-device", "anna", "Weg"])
    capsys.readouterr()
    cli.main(["revoke-device", "1"])
    cli.main(["list-devices"])
    out = capsys.readouterr().out
    assert "widerrufen" in out
    assert agent_env["wg"].peers == {}
