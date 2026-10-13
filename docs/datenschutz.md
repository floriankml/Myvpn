# Datenschutzdokumentation

Grundsatz: **Datensparsamkeit (Art. 5 Abs. 1 lit. c DSGVO).** Gespeichert wird nur, was für den Betrieb nötig ist. Wir unterscheiden ehrlich zwischen **„nicht gespeichert“** und **„technisch vorhanden, aber nicht ausgewertet“**. Ein pauschales „No-Logs“-Versprechen geben wir bewusst nicht ab.

> Diese Dokumentation beschreibt die Technik. Sie ist **keine Rechtsberatung**. Vor einem öffentlichen Start muss sie von einer fachkundigen Person geprüft werden, siehe [produktivbetrieb.md](produktivbetrieb.md).

## 1. Datenübersicht

| Datum | Ort | Dauerhaft gespeichert? | Dauer | Ausgewertet? | Zweck |
|---|---|---|---|---|---|
| Benutzername | SQLite | ja | bis Kontolöschung | nein | Anmeldung |
| Passwort-Hash (argon2id) | SQLite | ja | bis Änderung/Löschung | nein | Anmeldung |
| Rolle, Aktiv-Status, Anlagedatum | SQLite | ja | bis Kontolöschung | nein | Berechtigungen |
| Gerätename, öffentlicher Schlüssel, VPN-Adresse, Anlage-/Widerrufsdatum | SQLite | ja | bis Widerruf + 30 Tage | nein | Betrieb des Tunnels |
| Pre-Shared-Key | SQLite, Agent-Zustand | ja | bis Widerruf (dann gelöscht) | nein | Verschlüsselung |
| Sitzungs-Token (nur Hash) + Ablaufzeit | SQLite | ja | bis Ablauf (max. 12 h), danach gelöscht | nein | Anmeldung |
| **Reale IP-Adresse des Geräts** (WireGuard-Endpunkt) | Kernel-RAM | **nein** | solange der Peer aktiv ist; nach Neustart weg | **nein.** Der Agent liest sie nicht aus und gibt sie nicht weiter | WireGuard muss wissen, wohin es Antworten sendet |
| Zeitpunkt des letzten Handshakes, übertragene Bytes | Kernel-RAM | **nein** | bis Neustart bzw. Peer-Entfernung | nur **live** angezeigt (Dashboard), nicht gespeichert | Verbindungsstatus |
| NAT-Verbindungstabelle (conntrack): innere/äußere Adressen, Zielports | Kernel-RAM | **nein** | Sekunden bis wenige Tage (TCP-Timeout) | **nein** | technisch zwingend für NAT |
| DNS-Cache (Domainnamen, ohne Bezug zum Gerät) | Unbound-RAM | **nein** | bis TTL / Neustart | nein | Geschwindigkeit |
| DNS-Anfragen pro Gerät | – | **nein** (`log-queries: no`) | – | – | – |
| Webserver-Zugriffslog | – | **nein** (`--no-access-log`, Caddy `output discard`) | – | – | – |
| Anfrage-IP für Rate-Limiting | Backend-RAM | **nein** | max. 15 min | nur Zählung | Schutz vor Brute-Force |
| Dienst-Logs (Fehler, Start/Stopp) | systemd-journal | ja | **max. 7 Tage** (`MaxRetentionSec=7day`) | bei Fehlersuche | Betrieb. Enthalten keine Client-IPs (getestet) |
| SSH-Logins der Administration | journal/auth.log | ja | 7 Tage (journal) bzw. logrotate | bei Sicherheitsvorfällen | Schutz des Servers |
| Backups (Datenbank, Konfiguration) | verschlüsseltes Backup-Ziel | ja | laut Backup-Rotation | nein | Wiederherstellung |
| Surfverlauf, aufgerufene Ziele, Inhalte | – | **nein** | – | – | – |
| Analyse- oder Tracking-Daten, Cookies Dritter | – | **nein** | – | – | – |

### Was technisch anfällt, das wir nicht kontrollieren
- **Hoster und Netzbetreiber** können Verkehrsmetadaten sehen, z. B. Datenmengen von Ihrer realen IP zum VPN-Server und vom Server zu Zielen. Der Inhalt ist bei HTTPS-Zielen verschlüsselt.
- **Zielwebseiten** sehen die IP des VPN-Servers, nicht Ihre.
- **Root auf dem Server** kann die RAM-Daten (z. B. `wg show` mit Endpunkten, `conntrack -L`) jederzeit einsehen. Wir tun das nicht routinemäßig, technisch möglich ist es aber. Genau deshalb steht hier „nicht ausgewertet“ und nicht „nicht vorhanden“.

## 2. Umsetzung im Code (nachprüfbar)

- Der Agent verwirft das Endpunkt-Feld bereits beim Einlesen (`agent/dvpn_agent/wg.py`, `dump()`). Ein Test stellt sicher, dass die Status-Antwort keine Endpunkte enthält (`test_status_never_contains_endpoint`).
- Das Backend speichert keine IP-Adressen. Die Seite „Verbindung“ nutzt die IP nur für die aktuelle Antwort.
- E2E-Test `test_16_keine_protokolle_mit_client_ips`: Die Logs von Backend, Agent und Unbound enthalten keine realen Client-IPs.
- SQLite mit `secure_delete=ON`: Gelöschte Datensätze werden überschrieben.
- Widerrufene Geräte werden nach 30 Tagen automatisch gelöscht (`DVPN_REVOKED_RETENTION_DAYS`), der PSK sofort beim Widerruf.

## 3. Betroffenenrechte (technische Unterstützung)

| Recht | Umsetzung |
|---|---|
| Auskunft (Art. 15) / Datenübertragbarkeit (Art. 20) | Einstellungen → „Meine gespeicherten Daten herunterladen“ (JSON) |
| Berichtigung (Art. 16) | Gerätename über Neuanlage. Benutzername über Admin |
| Löschung (Art. 17) | Admin → Benutzer löschen: entfernt Konto, Geräte, Sitzungen und Peers sofort. Backups laufen nach der Rotation aus |
| Widerspruch / Einschränkung | Admin → Benutzer sperren |

## 4. Für einen öffentlichen Start zu prüfen (Auszug)

Ausführlich in [produktivbetrieb.md](produktivbetrieb.md):
- Datenschutzerklärung (Art. 13 DSGVO) auf Basis dieser Tabelle
- Auftragsverarbeitungsvertrag (Art. 28) mit dem Hoster
- Verzeichnis von Verarbeitungstätigkeiten (Art. 30), TOMs (Art. 32)
- Rechtsgrundlagen (i. d. R. Art. 6 Abs. 1 lit. b – Vertrag)
- Pflichten aus TKG/TDDDG (u. a. Fernmeldegeheimnis, ggf. Melde- und Auskunftspflichten), Stand der Gesetzgebung zur IP-Adressen-Speicherung
- Impressum (§ 5 DDG)
