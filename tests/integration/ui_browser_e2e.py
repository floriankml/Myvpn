"""Optionaler Browser-Ende-zu-Ende-Test (nicht Teil der pytest-Suite, da Playwright nötig).

Baut dieselbe Namespace-Topologie wie test_e2e_netns.py auf, bedient die Weboberfläche
mit Chromium DURCH den WireGuard-Tunnel und prüft:
  * Login, alle Seiten ohne JS-Fehler, kein horizontales Scrollen (Desktop + Mobil)
  * Im Browser erzeugte Konfiguration: QR-Code-Inhalt == Textinhalt
  * Diese Konfiguration baut einen echten Tunnel auf (Internet sieht die Server-IP)

  sudo PLAYWRIGHT_MODULE=/pfad/zu/playwright/index.mjs python tests/integration/ui_browser_e2e.py
Benötigt zusätzlich: node, Playwright mit Chromium, zbarimg (zbar-tools).
"""

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_e2e_netns as t  # noqa: E402

OUT = t.ROOT / "docs" / "screenshots"


def main() -> int:
    shutil.rmtree(t.WORK, ignore_errors=True)
    t.WORK.mkdir()
    e = t.Env()
    try:
        e.build_network(); e.render(False); e.load_firewall(); e.sysctl()  # noqa: E702
        e.wg_up(); e.start_unbound(); e.start_agent(); e.start_backend()  # noqa: E702
        pw = re.search(r"Initialpasswort.*: (\S+)", e.cli("create-admin", "admin", "--generate")).group(1)
        e.cli("create-device", "admin", "Laptop", "-o", str(t.WORK / "c1.conf"))
        e.client_up("c1", "wgc1", (t.WORK / "c1.conf").read_text())
        t.wait_for(lambda: t.curl("c1", "http://203.0.113.10/").stdout == "198.51.100.2", 20)
        api = t.Api("c1", "http://10.8.0.1:8080", "ui")
        api.req("POST", "/api/auth/login", {"username": "admin", "password": pw})
        new_pw = "browser-test-passwort-1"
        api.req("POST", "/api/auth/change-password", {"current_password": pw, "new_password": new_pw})
        OUT.mkdir(parents=True, exist_ok=True)
        r = t.sh("node", str(Path(__file__).with_suffix(".mjs")), "http://10.8.0.1:8080/", "admin", new_pw,
                 str(OUT), str(t.WORK), ns="c1", check=False, timeout=300)
        result = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"problems": [r.stderr[-2000:]]}
        checks = {"Oberfläche ohne Fehler": r.returncode == 0 and not result["problems"]}
        conf = (t.WORK / "desktop-browser.conf").read_text()
        qr = t.sh("zbarimg", "--raw", "-q", str(t.WORK / "desktop-qr.png")).stdout
        checks["QR-Code == Konfigurationstext"] = qr.strip() == conf.strip()
        e.client_up("c2", "wgc2", conf)
        checks["Browser-Konfiguration baut Tunnel auf"] = bool(t.wait_for(
            lambda: t.curl("c2", "http://203.0.113.10/").stdout == "198.51.100.2", 20, what="Browser-Konfig"))
        for k, v in checks.items():
            print(f"{'BESTANDEN' if v else 'FEHLGESCHLAGEN'}: {k}")
        for p in result["problems"]:
            print("  -", p)
        return 0 if all(checks.values()) else 1
    finally:
        e.teardown()


if __name__ == "__main__":
    sys.exit(main())
