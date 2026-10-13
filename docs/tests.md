# Phase 3 – Tests und dokumentierte Ergebnisse

Alle Ergebnisse unten stammen aus **tatsächlichen Läufen** am **13.10.2026** in der Entwicklungsumgebung (Ubuntu 24.04, Linux 6.18, Python 3.13, Node 22). Nichts ist geschätzt oder erfunden. Was **nicht** getestet werden konnte, steht ausdrücklich in Abschnitt 4.

## 1. Übersicht

| Suite | Befehl | Ergebnis |
|---|---|---|
| Agent (Unit + Socket) | `cd agent && pytest -q` | **37 bestanden** |
| Backend (Unit + API + CLI) | `cd backend && pytest -q` | **72 bestanden** |
| Frontend (Schlüssel, Konfiguration) | `cd frontend && npm test` | **6 bestanden** |
| Typprüfung Frontend | `npm run typecheck` | fehlerfrei |
| **Ende-zu-Ende mit echtem WireGuard** | `sudo python -m pytest -v tests/integration` | **15 bestanden, 2 übersprungen (IPv6, siehe 4.)** |
| Browser-E2E (Chromium durch den Tunnel) | `sudo python tests/integration/ui_browser_e2e.py` | **3/3 bestanden** |
| Installation unter systemd (Container) | `sudo tests/install/run.sh` | siehe Abschnitt 3.4 |
| Firewall-Syntax (3 Varianten) | `nft -c -f` (ohne IPv6 / IPv6 abgelehnt / IPv6-Ausgang + öffentliche UI) | gültig |
| Unbound-Konfiguration | `unbound-checkconf` | „no errors“ |
| Shell-Skripte | `shellcheck deploy/*.sh tests/install/run.sh` | keine Befunde |
| systemd-Units | `systemd-analyze verify` | gültig (nur Hinweis: venv-Pfad auf dem Testrechner nicht vorhanden) |

## 2. Unit- und API-Tests (Auszug der geprüften Eigenschaften)

**Agent** (`agent/tests/test_agent.py`)
- Schlüsselvalidierung: leere, zu kurze und zu lange Schlüssel, Null-Schlüssel, Pfade, `--help`, Shell-Metazeichen → abgelehnt
- AllowedIPs: nur `/32` bzw. `/128` im VPN-Netz. `0.0.0.0/0`, fremde Netze, Server-, Netz- und Broadcast-Adresse, Komma-Injektion → abgelehnt
- Unbekannte Operationen (`exec`) und Felder (`endpoint`) → abgelehnt
- Zustandsdatei mit Rechten 0600, Wiederherstellung nach „Neustart“, defekte Zustandsdatei wird ignoriert
- Abgleich (`sync`) ist idempotent und entfernt fremde Peers. Doppelte Adressen oder Schlüssel → abgelehnt
- Status-Antwort enthält **keine** Endpunkte (reale Client-IPs)
- Unix-Socket mit Rechten 0660. **Echter SO_PEERCRED-Test:** Ein Prozess mit UID 65534 wird abgewiesen

**Backend** (`backend/tests/`, spricht über einen echten Unix-Socket mit dem echten Agent-Code. Nur das Kernel-Interface ist simuliert.)
- Login: gehärtetes Cookie, Groß-/Kleinschreibung, gleiche Antwort für falsches Passwort und unbekannten Nutzer, gesperrte Konten
- Alle geschützten Endpunkte ohne Anmeldung → 401. Gefälschte oder zu lange Cookies → 401
- Logout invalidiert die Sitzung serverseitig. Token und Passwort stehen nicht im Klartext in der Datenbank (argon2id-Hash)
- Rate-Limit pro IP und pro Konto (über mehrere IPs), globales Rate-Limit
- Passwortänderung beendet andere Sitzungen. Mit Initialpasswort keine Geräteverwaltung
- **Berechtigungen:** fremde Geräte weder sichtbar noch widerrufbar oder abrufbar (404), `?all=true` für Nicht-Admins wirkungslos, Admins sehen alle Geräte, erhalten aber keine fremden Konfigurationen
- **Admin nur aus VPN/localhost** (aus dem „Internet“ 403, aus dem VPN-Netz IPv4/IPv6 erlaubt). Kein Selbst-Aussperren
- CSRF: fremde Origin, `Sec-Fetch-Site: cross-site` und Formular-POST → abgelehnt
- Eingabevalidierung inkl. XSS-, Shell- und Konfigurations-Injektion und Massenzuweisung. Fehlerantworten spiegeln keine Eingaben (Passwörter) zurück
- Interne Fehler liefern eine generische Meldung ohne Stacktrace
- Gerätelimit, eindeutige Adressen (Wiederverwendung nach Widerruf), doppelte Schlüssel, Server-Schlüssel als Geräteschlüssel → abgelehnt
- Widerruf entfernt den Peer sofort. Bei nicht erreichbarem Agent erledigt das der nächste Abgleich
- Abgleich stellt Peers nach „Kernel-Reset“ wieder her und entfernt unbekannte Peers
- Verbindungserkennung („über VPN?“) verrät keine fremden Gerätenamen
- CLI: stdout enthält nur die Konfiguration, kein Gerät ohne beschreibbare Ausgabedatei, keine Überschreibung vorhandener Dateien, Rechte 0600

**Frontend** (`frontend/src/lib/wg.test.ts`)
- X25519 gegen den **RFC-7748-Testvektor**
- Browser-Schlüssel sind gültig, geklemmt und zufällig. **Öffentlicher Schlüssel identisch mit `wg pubkey`** (offizielles Werkzeug)
- Konfiguration byte-identisch zur Backend-Ausgabe. Dateinamen sicher (≤ 15 Zeichen, keine Pfade)

## 3. Ende-zu-Ende-Tests mit echtem WireGuard

### 3.1 Aufbau (`tests/integration/test_e2e_netns.py`)

Vier Linux-Netzwerk-Namespaces: `isp` (simuliertes Internet mit Echo-Webserver, der die Quell-IP zurückgibt, und einem „Provider-DNS“, der Quell-IPs protokolliert), `vpn` (Server), `c1` und `c2` (Clients). Der Server nutzt die **produktiven** Vorlagen aus `deploy/render.py` (nftables, wg0, Unbound, sysctl), den echten Agent und das echte Backend. WireGuard läuft als `wireguard-go` (Userspace), weil die Testumgebung kein Kernelmodul hat. Clients verbinden sich mit `wg-quick`.

### 3.2 Ergebnis (Lauf vom 13.10.2026)

```
test_01_ohne_vpn_sieht_internet_die_echte_ip ............... PASSED
test_02_backend_nicht_aus_dem_internet_erreichbar .......... PASSED
test_03_bootstrap_per_cli_und_erstes_geraet ................ PASSED
test_04_vollstaendiges_routing_ueber_deutsche_server_ip .... PASSED
test_05_ipv6_leckschutz_ohne_ipv6_ausgang .................. SKIPPED (Kernel ohne IPv6)
test_06_dns_leckschutz ..................................... PASSED
test_07_weboberflaeche_nur_durch_den_tunnel_und_login ...... PASSED
test_08_zweites_geraet_ueber_api ........................... PASSED
test_08b_smtp_port_25_gesperrt ............................. PASSED
test_09_client_isolation ................................... PASSED
test_10_fremde_absenderadresse_wird_verworfen .............. PASSED
test_11_widerruf_sperrt_sofort ............................. PASSED
test_12_neustart_wiederherstellung_ohne_backend ............ PASSED
test_13_backend_abgleich_nach_verlorenem_agentenzustand .... PASSED
test_14_ipv6_ausgang_wenn_aktiviert ........................ SKIPPED (Kernel ohne IPv6)
test_15_tunnel_aus_dann_echte_ip ........................... PASSED
test_16_keine_protokolle_mit_client_ips .................... PASSED
15 passed, 2 skipped in 66 s
```

| Test | Nachweis |
|---|---|
| 01/15 | **Kontrollmessung:** Ohne VPN sieht der Echo-Server `192.0.2.2` (Client), mit VPN `198.51.100.2` (Server). Der Test unterscheidet also tatsächlich |
| 02 | Port 8080 und DNS des Servers sind aus dem „Internet“ nicht erreichbar (kein offener Resolver) |
| 04 | Gesamter IPv4-Verkehr läuft über die Server-IP. Handshake auf dem Server sichtbar |
| 06 | **DNS-Leckschutz:** Anfragen an 10.8.0.1, an den Provider-DNS und an `9.9.9.9` werden beantwortet. Der Provider-DNS sieht **ausschließlich** die Server-IP, nie die Client-IP |
| 08b | Port 25 aus dem Tunnel gesperrt, Port 587 offen. Kontrolle: Vom Server selbst ist Port 25 erreichbar |
| 09 | **Client-Isolation** mit Positivkontrolle (Ping zum Server geht, zum anderen Gerät nicht) |
| 10 | Ein Client kann nicht mit der Tunnel-IP eines anderen Clients senden (Cryptokey-Routing, Timeout) |
| 11 | **Widerruf:** Peer sofort entfernt, Verbindung des widerrufenen Geräts läuft in den Timeout, anderes Gerät unbeeinträchtigt |
| 12 | **Neustart:** Interface, Firewall und Prozesse weg. Nach der Boot-Reihenfolge stellt der Agent die Peers **ohne Backend** wieder her. Das widerrufene Gerät bleibt gesperrt |
| 13 | Agent-Zustand **und** Interface verloren: Das Backend stellt beim Start alles wieder her |
| 16 | Backend-, Agent- und Unbound-Logs enthalten keine Client-IPs |

### 3.3 Browser-E2E (`tests/integration/ui_browser_e2e.py`)

Chromium (Playwright) läuft im Client-Namespace und spricht **durch den WireGuard-Tunnel** mit der Weboberfläche:
```
BESTANDEN: Oberfläche ohne Fehler           (Desktop 1280 px + Mobil 390 px/Dark Mode: alle Seiten,
                                             keine JS-Fehler, kein horizontales Scrollen)
BESTANDEN: QR-Code == Konfigurationstext    (QR-Bild mit zbarimg dekodiert)
BESTANDEN: Browser-Konfiguration baut Tunnel auf (im Browser erzeugter Schlüssel → echter Tunnel,
                                             Echo-Server sieht die Server-IP)
```
Dabei gefundene und behobene Fehler: Auf Smartphones war der Dialog nicht scrollbar (Buttons unerreichbar). Absolut positionierte Screenreader-Texte verbreiterten die Seite. Das `pattern`-Attribut war im `v`-Regex-Modus ungültig. Der „Menü“-Button wurde auf dem Desktop angezeigt.

### 3.4 Installation unter systemd (`tests/install/run.sh`)

Echter Lauf von `install.sh` in einem Ubuntu-24.04-Container mit **systemd als PID 1**:

| Prüfung | Ergebnis |
|---|---|
| `install.sh` Erstinstallation und zweiter Lauf (Idempotenz) | bestanden |
| `check.sh`: Dienste aktiv und beim Boot aktiviert, Forwarding, Firewall-Policies DROP, Client-Isolation, NAT, Rechte, Backend nicht öffentlich, kein DNS-Query-Logging | bestanden |
| `check.sh`: Unbound-Auflösung | **FEHLER, korrekt erkannt.** Die Testumgebung erlaubt keine DNS-Rekursion ins Internet. Auf einem echten VPS erwartet |
| `dvpn-admin create-admin/create-device`, Datei mit Rechten 0600 | bestanden |
| **Echter systemd-Neustart:** System `running`, Peer automatisch wiederhergestellt | bestanden |
| WireGuard-Client vom Host: Ping und API durch den Tunnel | bestanden |
| API und DNS von außen gesperrt | bestanden |
| `uninstall.sh`: Tabellen entfernt, Forwarding aus. `--purge`: Daten, Schlüssel und Programme gelöscht | bestanden |

Dabei gefundene und behobene Fehler: Der Agent startete nicht (`python3 -I` ignoriert `PYTHONPATH`). `check.sh` meldete Fehlalarme (SIGPIPE bei `grep -q` mit `pipefail`, falsche `ss`-Spalte) und hatte einen Scheinerfolg bei DNS (SERVFAIL wurde als Erfolg gewertet). `dvpn-admin -o` legte bei fehlenden Schreibrechten trotzdem ein Gerät an.

## 4. Nicht getestet bzw. Einschränkungen der Testumgebung

| Was | Warum | Was vor Produktivbetrieb zu tun ist |
|---|---|---|
| **IPv6** (Leckschutz, NAT66) | Der Kernel der Testumgebung startet mit `ipv6.disable=1` | `test_05`/`test_14` auf dem VPS ausführen. Manuell: test-ipv6.com mit verbundenem Gerät |
| **Kernel-WireGuard** | kein Kernelmodul verfügbar, getestet mit `wireguard-go` (gleiches Protokoll, gleiche `wg`-Schnittstelle) | auf dem VPS automatisch genutzt. `check.sh` und Gerät anlegen/widerrufen prüfen |
| **Agent ohne root mit nur `CAP_NET_ADMIN`** | Der `wireguard-go`-Steuersocket gehört root, im Container lief der Agent daher als root (Test-Drop-in) | auf dem VPS: `ps -o user= -C python3` → `dvpn-agent`, dann ein Gerät anlegen. Rückfall bei Problemen: in `dvpn-agent.service` `User=root` (dokumentierte Abschwächung) |
| **Echte Endgeräte** (Android, iOS, Windows, macOS) | keine Geräte in der Testumgebung | Anleitung [android.md](android.md) Schritt 5. Leak-Tests je Plattform |
| **Debian 12/13** | Debian-Paketquellen aus der Testumgebung nicht erreichbar | einmal auf Debian installieren. Unterschiede: Python 3.11, kein systemd-resolved |
| **Echte DNS-Rekursion und DNSSEC** | kein ausgehendes DNS in der Testumgebung | `check.sh` prüft beides auf dem VPS |
| **Öffentlicher Modus mit Caddy (`--domain`)** | keine Domain bzw. kein Zertifikat in der Testumgebung | optional. Vor Nutzung testen |
| **Last/Performance** | nicht Ziel des MVP | z. B. `iperf3` durch den Tunnel |

## 5. Tests selbst ausführen

```bash
# Unit/API (ohne root)
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.lock pytest httpx2 && pip install -e backend
(cd agent && pytest -q) && (cd backend && pytest -q)
(cd frontend && npm ci && npm test && npm run typecheck)

# Ende-zu-Ende (root; Pakete: wireguard-tools wireguard-go nftables unbound dnsutils curl iputils-ping)
sudo .venv/bin/python -m pytest -v tests/integration

# Browser-E2E (zusätzlich node, Playwright mit Chromium, zbar-tools)
cd frontend && npm run build && cd ..
sudo PLAYWRIGHT_MODULE=$(npm root -g)/playwright/index.mjs .venv/bin/python tests/integration/ui_browser_e2e.py

# Installation unter systemd (Docker)
sudo tests/install/run.sh
```
Die Integrationstests verändern nur eigene Namespaces (`isp`, `vpn`, `c1`, `c2`) und `/tmp/dvpn-e2e`. Sie beenden ausschließlich Prozesse in diesen Namespaces.
