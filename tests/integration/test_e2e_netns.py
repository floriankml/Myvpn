"""Ende-zu-Ende-Test mit ECHTEM WireGuard in Linux-Netzwerk-Namespaces.

Topologie (alles lokal, keine echten Fremdsysteme):

    [c1] 192.0.2.2 / 2001:db8:1::2 ──┐
                                     ├── [isp] "Internet": Router, Echo-Webserver 203.0.113.10
    [c2] 198.18.0.2 / 2001:db8:4::2 ─┤        und Provider-DNS 203.0.113.53 (protokolliert Quell-IPs)
                                     │
    [vpn] 198.51.100.2 / 2001:db8:2::2 ──┘  WireGuard-Server (wireguard-go), nftables aus
                                            deploy/render.py, Unbound, dvpn-agent, Backend

Geprüft wird u. a.: NAT-Ausgang über die Server-IP, DNS-Leckschutz, IPv6-Leckschutz,
Client-Isolation, Firewall von außen, Widerruf, Wiederherstellung nach Neustart.

Voraussetzungen: root, ip, nft, wg, wg-quick, wireguard-go, unbound, dig, curl.
Start:  sudo python -m pytest -v tests/integration
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = Path(__file__).resolve().parent / "helpers"
PY = sys.executable
WORK = Path("/tmp/dvpn-e2e")

REQUIRED = ["ip", "nft", "wg", "wg-quick", "wireguard-go", "unbound", "dig", "curl", "ping"]
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or any(shutil.which(b) is None for b in REQUIRED) or not Path("/dev/net/tun").exists(),
    reason="benötigt root, /dev/net/tun und: " + ", ".join(REQUIRED),
)

NS = ["isp", "vpn", "c1", "c2"]
# Manche Umgebungen (z. B. Kernel mit ipv6.disable=1) haben gar kein IPv6.
# Dann laufen alle IPv4-Tests; IPv6-Tests werden ausdrücklich als übersprungen gemeldet.
HAS_V6 = Path("/proc/sys/net/ipv6").exists()
needs_v6 = pytest.mark.skipif(not HAS_V6, reason="Kernel ohne IPv6 (ipv6.disable=1) – IPv6-Test nur auf echtem Server möglich")
SUBNET6 = "fd42:4242:4242::/64"
USERSPACE_ENV = {
    "WG_QUICK_USERSPACE_IMPLEMENTATION": "wireguard-go",
    "WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD": "1",
}


# ---------------------------------------------------------------- Hilfen
def sh(*args: str, ns: str | None = None, check: bool = True, input: str | None = None,
       env: dict | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    cmd = (["ip", "netns", "exec", ns] if ns else []) + list(args)
    full_env = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, capture_output=True, text=True, input=input, env=full_env, timeout=timeout)
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(cmd)} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


def bg(*args: str, ns: str, log: Path, env: dict | None = None) -> subprocess.Popen:
    return subprocess.Popen(["ip", "netns", "exec", ns, *args], stdout=log.open("w"), stderr=subprocess.STDOUT,
                            env={**os.environ, **(env or {})}, start_new_session=True)


def curl(ns: str, url: str, *extra: str, timeout: int = 5) -> subprocess.CompletedProcess:
    return sh("curl", "-sS", "--max-time", str(timeout), *extra, url, ns=ns, check=False, timeout=timeout + 5)


def wait_for(pred, timeout: float = 30, interval: float = 0.5, what: str = "Bedingung"):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = pred()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"Zeitüberschreitung: {what} (zuletzt: {last!r})")


def kill_ns_procs(ns: str, comm: str | None = None) -> None:
    """Beendet NUR Prozesse im angegebenen Test-Namespace (nie fremde Prozesse)."""
    pids = sh("ip", "netns", "pids", ns, check=False).stdout.split()
    for pid in pids:
        try:
            if comm and Path(f"/proc/{pid}/comm").read_text().strip() != comm:
                continue
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass
    time.sleep(0.3)


class Api:
    """HTTP-Client per curl innerhalb eines Namespace (mit Cookie-Jar)."""

    def __init__(self, ns: str, base: str, name: str) -> None:
        self.ns, self.base = ns, base
        self.jar = WORK / f"cookies-{name}.txt"
        self.jar.unlink(missing_ok=True)

    def req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
        args = ["curl", "-sS", "--max-time", "10", "-o", "-", "-w", "\n%{http_code}", "-X", method,
                "-b", str(self.jar), "-c", str(self.jar)]
        if body is not None:
            args += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body)]
        r = sh(*args, self.base + path, ns=self.ns, check=False)
        text, _, code = r.stdout.rpartition("\n")
        try:
            data = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            data = {"raw": text}
        return int(code or 0), data


# ---------------------------------------------------------------- Umgebung
class Env:
    procs: dict[str, subprocess.Popen]
    rendered: Path

    def __init__(self) -> None:
        self.procs = {}

    # --- Netz ---
    def build_network(self) -> None:
        for ns in NS:
            if ns in sh("ip", "netns", "list", check=False).stdout:
                kill_ns_procs(ns)
            sh("ip", "netns", "del", ns, check=False)
            sh("ip", "netns", "add", ns)
            sh("ip", "link", "set", "lo", "up", ns=ns)
        links = [("c1", "192.0.2.2/24", "2001:db8:1::2/64", "192.0.2.1/24", "2001:db8:1::1/64"),
                 ("c2", "198.18.0.2/24", "2001:db8:4::2/64", "198.18.0.1/24", "2001:db8:4::1/64"),
                 ("vpn", "198.51.100.2/24", "2001:db8:2::2/64", "198.51.100.1/24", "2001:db8:2::1/64")]
        for ns, a4, a6, gw4, gw6 in links:
            inner, outer = f"{ns}-eth0", f"isp-{ns}"
            sh("ip", "link", "add", inner, "netns", ns, "type", "veth", "peer", "name", outer, "netns", "isp")
            sh("ip", "addr", "add", a4, "dev", inner, ns=ns)
            sh("ip", "link", "set", inner, "up", ns=ns)
            sh("ip", "addr", "add", gw4, "dev", outer, ns="isp")
            sh("ip", "link", "set", outer, "up", ns="isp")
            sh("ip", "route", "add", "default", "via", gw4.split("/")[0], ns=ns)
            if HAS_V6:
                sh("ip", "-6", "addr", "add", a6, "dev", inner, "nodad", ns=ns)
                sh("ip", "-6", "addr", "add", gw6, "dev", outer, "nodad", ns="isp")
                sh("ip", "-6", "route", "add", "default", "via", gw6.split("/")[0], ns=ns)
        sh("ip", "addr", "add", "203.0.113.10/32", "dev", "lo", ns="isp")
        sh("ip", "addr", "add", "203.0.113.53/32", "dev", "lo", ns="isp")
        sh("sysctl", "-qw", "net.ipv4.ip_forward=1", ns="isp")
        if HAS_V6:
            sh("ip", "-6", "addr", "add", "2001:db8:3::10/128", "dev", "lo", ns="isp")
            sh("sysctl", "-qw", "net.ipv6.conf.all.forwarding=1", ns="isp")
        self.procs["echo"] = bg(PY, str(HELPERS / "echo_http.py"), "203.0.113.10",
                                "2001:db8:3::10" if HAS_V6 else "-",
                                ns="isp", log=WORK / "echo.log")
        self.procs["dns"] = bg(PY, str(HELPERS / "fake_dns.py"), "203.0.113.53", str(WORK / "isp-dns-queries.log"),
                               ns="isp", log=WORK / "fake-dns.log")
        for port in ("25", "587"):  # Mail-Ports im "Internet" (für den SMTP-Sperrtest)
            self.procs[f"http{port}"] = bg(PY, "-m", "http.server", port, "--bind", "203.0.113.10",
                                           "--directory", str(HELPERS), ns="isp", log=WORK / f"http{port}.log")
        wait_for(lambda: curl("c1", "http://203.0.113.10/").returncode == 0, 10, what="Echo-Server")

    # --- Server-Konfiguration (produktive Vorlagen) ---
    def render(self, ipv6_egress: bool) -> None:
        self.rendered = WORK / ("rendered-egress" if ipv6_egress else "rendered")
        shutil.rmtree(self.rendered, ignore_errors=True)
        key_file = WORK / "server.key"
        if not key_file.exists():
            key_file.write_text(sh("wg", "genkey").stdout.strip())
        args = ["--out", str(self.rendered), "--wan-if", "vpn-eth0", "--endpoint", "198.51.100.2",
                "--server-private-key", key_file.read_text().strip(),
                "--location", "Testlabor", "--public-ipv4", "198.51.100.2"]
        if HAS_V6:
            args += ["--subnet-v6", SUBNET6, "--server-has-ipv6"]
        if ipv6_egress:
            args.append("--ipv6-egress")
        sh(PY, str(ROOT / "deploy" / "render.py"), *args)

    def load_firewall(self) -> None:
        sh("nft", "-f", str(self.rendered / "nftables.nft"), ns="vpn")

    def sysctl(self) -> None:
        for line in (self.rendered / "sysctl-dvpn.conf").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                k, v = (x.strip() for x in line.split("=", 1))
                if k.startswith("net.ipv6") and not HAS_V6:
                    continue
                sh("sysctl", "-qw", f"{k}={v}", ns="vpn")

    def wg_up(self) -> None:
        conf = WORK / "wg0.conf"
        shutil.copy(self.rendered / "wg0.conf", conf)
        os.chmod(conf, 0o600)
        sh("wg-quick", "up", str(conf), ns="vpn", env=USERSPACE_ENV)

    def wg_down_hard(self) -> None:
        """Simuliert Absturz/Neustart: Interface weg, alle Kernel-Peers weg."""
        sh("ip", "link", "del", "wg0", ns="vpn", check=False)
        kill_ns_procs("vpn", "wireguard-go")
        Path("/var/run/wireguard/wg0.sock").unlink(missing_ok=True)

    def start_unbound(self) -> None:
        conf = WORK / "unbound.conf"
        conf.write_text(
            "server:\n    directory: \"\"\n    chroot: \"\"\n    username: \"\"\n    pidfile: \"\"\n"
            "    do-daemonize: no\n    use-syslog: no\n"
            "    module-config: \"iterator\"\n"
            f"include: \"{self.rendered / 'unbound-dvpn.conf'}\"\n"
            "forward-zone:\n    name: \".\"\n    forward-addr: 203.0.113.53\n"
        )
        sh("unbound-checkconf", str(conf))
        self.procs["unbound"] = bg("unbound", "-d", "-c", str(conf), ns="vpn", log=WORK / "unbound.log")

    def agent_env(self) -> dict[str, str]:
        env = {}
        for line in (self.rendered / "agent.env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
        env.update({
            "DVPN_AGENT_SOCKET": str(WORK / "agent.sock"),
            "DVPN_AGENT_SOCKET_GROUP": "",
            "DVPN_AGENT_STATE_FILE": str(WORK / "agent-state" / "peers.json"),
            "DVPN_AGENT_ALLOWED_USERS": "",
            "DVPN_AGENT_WG_BINARY": shutil.which("wg") or "wg",
            "PYTHONPATH": str(ROOT / "agent"),
        })
        return env

    def start_agent(self) -> None:
        self.procs["agent"] = bg(PY, "-m", "dvpn_agent", ns="vpn", log=WORK / "agent.log", env=self.agent_env())
        wait_for(lambda: (WORK / "agent.sock").exists(), 10, what="Agent-Socket")

    def backend_env(self) -> dict[str, str]:
        env = {}
        for line in (self.rendered / "dvpn.env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
        env.update({
            "DVPN_DATABASE_URL": f"sqlite:///{WORK / 'dvpn.db'}",
            "DVPN_AGENT_SOCKET": str(WORK / "agent.sock"),
            "DVPN_STATIC_DIR": str(ROOT / "frontend" / "dist"),
            "DVPN_RECONCILE_INTERVAL": "3",
            "PYTHONPATH": str(ROOT / "backend"),
        })
        return env

    def start_backend(self) -> None:
        env = self.backend_env()
        self.procs["backend"] = bg(
            PY, "-m", "uvicorn", "--factory", "dvpn.main:app_from_env", "--host", env["DVPN_WEB_HOST"],
            "--port", env["DVPN_WEB_PORT"], "--no-access-log", "--proxy-headers",
            "--forwarded-allow-ips", env["DVPN_FORWARDED_ALLOW_IPS"],
            ns="vpn", log=WORK / "backend.log", env=env)
        wait_for(lambda: curl("vpn", "http://10.8.0.1:8080/api/health").stdout == '{"status":"ok"}', 20,
                 what="Backend")

    def cli(self, *args: str) -> str:
        r = sh(PY, "-m", "dvpn.cli", *args, ns="vpn", env=self.backend_env())
        return r.stdout + r.stderr  # Hinweise schreibt dvpn-admin nach stderr

    def stop(self, name: str) -> None:
        p = self.procs.pop(name, None)
        if p and p.poll() is None:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)

    def client_up(self, ns: str, iface: str, config: str) -> None:
        # wg-quick würde für "DNS =" resolvconf benötigen; DNS wird separat und
        # explizit gegen den Tunnel-Resolver getestet.
        conf = WORK / f"{iface}.conf"
        lines = [l for l in config.splitlines() if not l.startswith("DNS")]
        if not HAS_V6:  # ohne IPv6-Stack kann wg-quick keine ::/0-Route setzen
            lines = [l.replace(", ::/0", "") for l in lines]
        conf.write_text("\n".join(lines) + "\n")
        os.chmod(conf, 0o600)
        sh("wg-quick", "up", str(conf), ns=ns, env=USERSPACE_ENV)

    def client_down(self, ns: str, iface: str) -> None:
        sh("wg-quick", "down", str(WORK / f"{iface}.conf"), ns=ns, check=False, env=USERSPACE_ENV)

    def teardown(self) -> None:
        for name in list(self.procs):
            self.stop(name)
        for ns in NS:
            if ns in sh("ip", "netns", "list", check=False).stdout:
                kill_ns_procs(ns)
            sh("ip", "netns", "del", ns, check=False)
        for s in ("wg0", "wgc1", "wgc2"):
            Path(f"/var/run/wireguard/{s}.sock").unlink(missing_ok=True)


@pytest.fixture(scope="module")
def env():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    os.chmod(WORK, 0o700)
    e = Env()
    try:
        e.build_network()
        e.render(ipv6_egress=False)
        e.load_firewall()
        e.sysctl()
        e.wg_up()
        e.start_unbound()
        e.start_agent()
        e.start_backend()
        yield e
    finally:
        e.teardown()


STATE: dict = {}


# ---------------------------------------------------------------- Tests
def test_01_ohne_vpn_sieht_internet_die_echte_ip(env):
    assert curl("c1", "http://203.0.113.10/").stdout == "192.0.2.2"
    if HAS_V6:
        assert curl("c1", "http://[2001:db8:3::10]/").stdout == "2001:db8:1::2"
    # Kontrollmessung: Der Provider-DNS sieht ohne VPN die echte Client-IP
    sh("dig", "+short", "+time=2", "+tries=1", "@203.0.113.53", "kontrolle.example.org", ns="c1")
    assert "192.0.2.2 kontrolle.example.org" in (WORK / "isp-dns-queries.log").read_text()


def test_02_backend_nicht_aus_dem_internet_erreichbar(env):
    for port in ("8080", "53"):
        r = curl("isp", f"http://198.51.100.2:{port}/api/health", timeout=3)
        assert r.returncode != 0, f"Port {port} von außen erreichbar!"
    r = sh("dig", "+time=2", "+tries=1", "@198.51.100.2", "x.example.org", ns="isp", check=False)
    assert r.returncode != 0, "DNS-Resolver ist von außen erreichbar (offener Resolver)!"


def test_03_bootstrap_per_cli_und_erstes_geraet(env):
    out = env.cli("create-admin", "admin", "--generate")
    STATE["admin_pw"] = re.search(r"Initialpasswort.*: (\S+)", out).group(1)
    out = env.cli("create-device", "admin", "Laptop c1", "-o", str(WORK / "c1-cli.conf"))
    assert "aktiv" in out and "NICHT gespeichert" in out
    conf = (WORK / "c1-cli.conf").read_text()
    assert oct((WORK / "c1-cli.conf").stat().st_mode & 0o777) == "0o600"
    # Der private Schlüssel steht NICHT in der Datenbank
    priv = re.search(r"PrivateKey = (\S+)", conf).group(1)
    assert priv.encode() not in (WORK / "dvpn.db").read_bytes()
    # wg-quick akzeptiert die erzeugte Datei
    sh("wg-quick", "strip", str(WORK / "c1-cli.conf"))
    env.client_up("c1", "wgc1", conf)


def test_04_vollstaendiges_routing_ueber_deutsche_server_ip(env):
    r = wait_for(lambda: curl("c1", "http://203.0.113.10/").stdout == "198.51.100.2" and "ok",
                 20, what="Verkehr über VPN")
    assert r
    # Handshake auf dem Server sichtbar
    dump = sh("wg", "show", "wg0", "latest-handshakes", ns="vpn").stdout
    assert re.search(r"\t[1-9]\d+", dump)


@needs_v6
def test_05_ipv6_leckschutz_ohne_ipv6_ausgang(env):
    t0 = time.time()
    r = curl("c1", "http://[2001:db8:3::10]/", timeout=5)
    assert r.returncode != 0, f"IPv6 lief am Tunnel vorbei: {r.stdout}"
    assert time.time() - t0 < 4, "IPv6 sollte sofort abgelehnt werden (ICMP), nicht ins Timeout laufen"
    # Route für IPv6 zeigt in den Tunnel, nicht auf die native Leitung
    assert "dev wgc1" in sh("ip", "-6", "route", "get", "2001:db8:3::10", ns="c1").stdout


def test_06_dns_leckschutz(env):
    log = WORK / "isp-dns-queries.log"
    log.write_text("")
    # a) Anfrage an den Tunnel-Resolver
    ans = sh("dig", "+short", "+time=3", "+tries=2", "@10.8.0.1", "tunnel.example.org", "A", ns="c1").stdout.strip()
    assert ans == "203.0.113.10"
    # b) Gerät nutzt "falschen" DNS (Provider-DNS) -> wird im Tunnel auf Unbound umgeleitet
    ans = sh("dig", "+short", "+time=3", "+tries=2", "@203.0.113.53", "umgeleitet.example.org", "A", ns="c1").stdout.strip()
    assert ans == "203.0.113.10"
    # c) DNS über die IPv6-Adresse des Tunnel-Resolvers
    if HAS_V6:
        ans = sh("dig", "+short", "+time=3", "+tries=2", "@fd42:4242:4242::1", "v6dns.example.org", "A",
                 ns="c1").stdout.strip()
        assert ans == "203.0.113.10"
    # d) "Fremder" öffentlicher Resolver (im Testnetz nicht existent) -> trotzdem Antwort vom Tunnel
    ans = sh("dig", "+short", "+time=3", "+tries=2", "@9.9.9.9", "fremd.example.org", "A", ns="c1").stdout.strip()
    assert ans == "203.0.113.10"
    seen = log.read_text().splitlines()
    sources = {line.split()[0] for line in seen}
    assert sources == {"198.51.100.2"}, f"DNS-Quellen beim Provider: {seen}"
    assert not any("192.0.2.2" in line for line in seen)


def test_07_weboberflaeche_nur_durch_den_tunnel_und_login(env):
    api = Api("c1", "http://10.8.0.1:8080", "admin")
    STATE["api"] = api
    assert curl("c1", "http://10.8.0.1:8080/").stdout.startswith("<!doctype html>")
    code, _ = api.req("POST", "/api/auth/login", {"username": "admin", "password": "falsch-falsch"})
    assert code == 401
    code, me = api.req("POST", "/api/auth/login", {"username": "admin", "password": STATE["admin_pw"]})
    assert code == 200 and me["must_change_password"] is True
    code, _ = api.req("POST", "/api/auth/change-password",
                      {"current_password": STATE["admin_pw"], "new_password": "ein-langes-neues-passwort"})
    assert code == 204
    code, conn = api.req("GET", "/api/connection")
    assert conn["via_vpn"] is True and conn["device"]["name"] == "Laptop c1"
    code, st = api.req("GET", "/api/status")
    assert st["agent"] and st["interface_up"] and st["listen_port"] == 51820
    code, users = api.req("GET", "/api/admin/users")
    assert code == 200


def test_08_zweites_geraet_ueber_api(env):
    api: Api = STATE["api"]
    priv = sh("wg", "genkey").stdout.strip()
    pub = sh("wg", "pubkey", input=priv + "\n").stdout.strip()
    code, body = api.req("POST", "/api/devices", {"name": "Handy c2", "public_key": pub})
    assert code == 201 and body["applied"] is True
    STATE["c2_id"], STATE["c2_pub"] = body["device"]["id"], pub
    sys.path.insert(0, str(ROOT / "backend"))
    from dvpn.services import render_config

    config = render_config(body["config"], priv)
    env.client_up("c2", "wgc2", config)
    wait_for(lambda: curl("c2", "http://203.0.113.10/").stdout == "198.51.100.2", 20, what="c2 über VPN")
    assert curl("c2", "http://203.0.113.10/").stdout == "198.51.100.2"
    code, devices = api.req("GET", "/api/devices?all=true")
    assert {d["name"]: d["connected"] for d in devices} == {"Laptop c1": True, "Handy c2": True}


def test_08b_smtp_port_25_gesperrt(env):
    """Port 25 aus dem Tunnel ist gesperrt (Spam-Schutz), Submission-Port 587 nicht."""
    assert curl("c1", "http://203.0.113.10:587/").returncode == 0
    r = curl("c1", "http://203.0.113.10:25/")
    assert r.returncode == 7, f"Port 25 erreichbar oder unerwarteter Fehler: rc={r.returncode} {r.stderr}"
    # Kontrolle: ohne VPN (Server-Namespace selbst) ist Port 25 erreichbar – die Sperre gilt nur für Clients
    assert curl("vpn", "http://203.0.113.10:25/").returncode == 0


def test_09_client_isolation(env):
    # Positivkontrolle: Der Server (10.8.0.1) ist von beiden Geräten per ICMP erreichbar ...
    assert sh("ping", "-c", "1", "-W", "2", "10.8.0.1", ns="c1", check=False).returncode == 0
    assert sh("ping", "-c", "1", "-W", "2", "10.8.0.1", ns="c2", check=False).returncode == 0
    # ... die Geräte untereinander aber nicht.
    r = sh("ping", "-c", "2", "-W", "1", "10.8.0.3", ns="c1", check=False)
    assert r.returncode == 1 and "0 received" in r.stdout, f"Geräte können sich erreichen: {r.stdout}{r.stderr}"


def test_10_fremde_absenderadresse_wird_verworfen(env):
    """Cryptokey-Routing: c2 darf keine Pakete mit der Tunnel-IP von c1 senden."""
    sh("ip", "addr", "add", "10.8.0.2/32", "dev", "wgc2", ns="c2")
    r = sh("curl", "-sS", "--max-time", "4", "--interface", "10.8.0.2", "http://203.0.113.10/", ns="c2", check=False)
    sh("ip", "addr", "del", "10.8.0.2/32", "dev", "wgc2", ns="c2")
    assert r.returncode == 28, f"erwartet Timeout (Pakete verworfen), erhalten: {r.returncode} {r.stderr}"


def test_11_widerruf_sperrt_sofort(env):
    api: Api = STATE["api"]
    code, body = api.req("POST", f"/api/devices/{STATE['c2_id']}/revoke")
    assert code == 200 and body["applied"] is True
    assert STATE["c2_pub"] not in sh("wg", "show", "wg0", "peers", ns="vpn").stdout
    r = curl("c2", "http://203.0.113.10/", timeout=5)
    assert r.returncode == 28, f"Widerrufenes Gerät hat noch Zugang (curl rc={r.returncode}, {r.stdout})"
    assert curl("c1", "http://203.0.113.10/").stdout == "198.51.100.2"


def test_12_neustart_wiederherstellung_ohne_backend(env):
    """Server-"Neustart": Interface, Firewall und alle Prozesse weg. Der Agent stellt
    die Peers aus seiner Zustandsdatei wieder her – auch wenn das Backend noch nicht läuft."""
    env.stop("backend")
    env.stop("agent")
    env.stop("unbound")
    env.wg_down_hard()
    sh("nft", "flush", "ruleset", ns="vpn")
    assert curl("c1", "http://203.0.113.10/", timeout=3).returncode != 0  # Server ist "aus"
    # Boot-Reihenfolge wie systemd: Firewall -> wg-quick -> Unbound -> Agent
    env.load_firewall()
    env.wg_up()
    env.start_unbound()
    env.start_agent()
    peers = sh("wg", "show", "wg0", "peers", ns="vpn").stdout
    assert STATE["c2_pub"] not in peers, "widerrufenes Gerät nach Neustart wieder aktiv!"
    wait_for(lambda: curl("c1", "http://203.0.113.10/", timeout=3).stdout == "198.51.100.2", 45,
             interval=1, what="c1 nach Neustart wieder verbunden")
    assert curl("c2", "http://203.0.113.10/", timeout=3).returncode != 0


def test_13_backend_abgleich_nach_verlorenem_agentenzustand(env):
    """Agent-Zustand verloren UND Interface leer: Das Backend stellt alles wieder her."""
    env.stop("agent")
    env.wg_down_hard()
    env.wg_up()
    (WORK / "agent-state" / "peers.json").unlink()
    env.start_agent()
    assert sh("wg", "show", "wg0", "peers", ns="vpn").stdout.strip() == ""
    env.start_backend()  # Abgleich beim Start + alle 3 s
    wait_for(lambda: len(sh("wg", "show", "wg0", "peers", ns="vpn").stdout.split()) == 1, 15,
             what="Backend-Abgleich")
    wait_for(lambda: curl("c1", "http://203.0.113.10/", timeout=3).stdout == "198.51.100.2", 45,
             interval=1, what="c1 nach Abgleich")


@needs_v6
def test_14_ipv6_ausgang_wenn_aktiviert(env):
    env.render(ipv6_egress=True)
    env.load_firewall()
    env.sysctl()
    r = wait_for(lambda: (x := curl("c1", "http://[2001:db8:3::10]/")).returncode == 0 and x.stdout, 15,
                 what="IPv6 über VPN")
    assert r == "2001:db8:2::2", f"IPv6-Ausgang falsch: {r}"
    assert curl("c1", "http://203.0.113.10/").stdout == "198.51.100.2"
    env.render(ipv6_egress=False)
    env.load_firewall()
    assert curl("c1", "http://[2001:db8:3::10]/", timeout=3).returncode != 0


def test_15_tunnel_aus_dann_echte_ip(env):
    """Kontrollmessung: Nach dem Trennen ist die echte IP wieder sichtbar – der Test
    unterscheidet also tatsächlich zwischen "über VPN" und "direkt"."""
    env.client_down("c1", "wgc1")
    assert curl("c1", "http://203.0.113.10/").stdout == "192.0.2.2"


def test_16_keine_protokolle_mit_client_ips(env):
    """Backend- und Agent-Logs enthalten keine realen Client-IP-Adressen."""
    for name in ("backend.log", "agent.log", "unbound.log"):
        text = (WORK / name).read_text()
        for ip in ("192.0.2.2", "198.18.0.2"):
            assert ip not in text, f"{name} enthält Client-IP {ip}"
