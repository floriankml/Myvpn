# Phase 1 – Planung

Stand: 13.10.2026 · Projekt: **DeutschlandVPN** (privates MVP)

## 1. Machbarkeit

| Frage | Ergebnis |
|---|---|
| Kann ein einzelner günstiger VPS einen echten VPN-Dienst mit deutscher Ausgangs-IP bereitstellen? | **Ja.** WireGuard ist seit Linux 5.6 im Kernel enthalten (Debian 12, Ubuntu 24.04). Ein VPS mit öffentlicher IPv4 in einem deutschen Rechenzentrum leitet den Verkehr per NAT über diese IP ins Internet. |
| Reicht eine Weboberfläche? | **Nein.** Ein Browser kann den Verkehr eines Geräts nicht umleiten. Die Verbindung baut die **offizielle WireGuard-App** auf. Die Weboberfläche verwaltet nur Geräte und Konfigurationen. |
| Ressourcen | WireGuard im Kernel schafft auf 1 vCPU je nach CPU mehrere hundert Mbit/s. Backend und Unbound brauchen zusammen ca. 100–150 MB RAM. **1 vCPU / 1–2 GB RAM / 10+ GB SSD reichen für das private MVP.** |
| Kosten | ca. 1–6 € pro Monat für einen Server, siehe [kosten.md](kosten.md). Keine weiteren Pflichtdienste. |
| Nachweis | Ende-zu-Ende-Tests mit echtem WireGuard (Netzwerk-Namespaces), eine echte Installation unter systemd (Ubuntu 24.04) und ein Browser-Test, siehe [tests.md](tests.md). |

**Fazit:** Das Projekt ist mit geringem Aufwand und geringen Kosten machbar. Der Aufwand liegt bei Sicherheit, Datenschutz und Wartung, nicht bei der Technik.

## 2. Architektur

```
                         Internet (deutsche öffentliche IPv4/IPv6 des VPS)
                                          ▲  NAT (masquerade)
┌─────────────────────────── VPS (Debian 12 / Ubuntu 24.04) ─────────────────────────────┐
│                                                                                          │
│  nftables  (Policy DROP; erlaubt: SSH, UDP 51820; aus wg0: DNS 53, Web 8080)             │
│                                                                                          │
│  ┌──────────── Datenebene ────────────┐     ┌──────── Verwaltung ─────────────────┐     │
│  │ WireGuard wg0 (Kernel)             │     │ dvpn-backend (FastAPI, User "dvpn",  │     │
│  │  10.8.0.1/24 + fdXX::1/64          │◄───┐│  KEINE Capabilities)                 │     │
│  │ Unbound (DNS nur für Tunnel)       │    ││  lauscht NUR auf 10.8.0.1:8080       │     │
│  └────────────────────────────────────┘    ││  SQLite /var/lib/dvpn/dvpn.db        │     │
│               ▲ wg set (Argumentliste)     ││  liefert auch die React-Oberfläche   │     │
│  ┌────────────┴───────────────────────┐    │└──────────────┬───────────────────────┘     │
│  │ dvpn-agent (User "dvpn-agent",     │    │   Unix-Socket │ JSON, 5 feste Operationen    │
│  │  nur CAP_NET_ADMIN, nur stdlib)    │◄───┼───────────────┘ + SO_PEERCRED-Prüfung        │
│  │  Zustand: /var/lib/dvpn-agent      │    │                                              │
│  └────────────────────────────────────┘    │ dvpn-admin (CLI, als User "dvpn")            │
└────────────────────────────────────────────┼─────────────────────────────────────────────┘
                                             │
        UDP 51820 (verschlüsselt)            │ HTTP nur innerhalb des Tunnels
┌────────────────────────┐                   │ (optional: HTTPS über Caddy + Domain)
│ Gerät mit offizieller  │───────────────────┘
│ WireGuard-App          │   Browser → Weboberfläche: Schlüsselpaar wird IM BROWSER erzeugt,
└────────────────────────┘   nur der öffentliche Schlüssel geht an den Server.
```

### Getrennte Komponenten

| Komponente | Aufgabe | Rechte |
|---|---|---|
| **WireGuard (wg0)** | Datenebene: Verschlüsselung, Routing | Kernel |
| **nftables** (`dvpn-firewall.service`) | Firewall, NAT, DNS-Umleitung, Client-Isolation | root (oneshot) |
| **Unbound** | rekursiver, validierender DNS-Resolver nur für Tunnel-Clients | Paket-Standard (eigener User) |
| **dvpn-agent** | einzige Komponente, die Peers ändert; kleine feste Befehlsmenge | eigener User + **nur** `CAP_NET_ADMIN` |
| **dvpn-backend** | API, Benutzer, Geräte, Abgleich, Weboberfläche | unprivilegiert, keine Capabilities |
| **Weboberfläche** | React/TypeScript, deutschsprachig | läuft im Browser |
| **dvpn-admin / check.sh** | Administration und Monitoring auf dem Server | root bzw. `dvpn` |

## 3. Technologieentscheidungen (mit Begründung)

| Entscheidung | Begründung | Verworfene Alternative |
|---|---|---|
| **WireGuard** | Kleine, auditierte Codebasis, moderne Kryptografie ohne Auswahlmöglichkeiten (keine Fehlkonfiguration), im Linux-Kernel, offizielle Apps für alle Plattformen | OpenVPN/IPsec: deutlich komplexer und mehr Angriffsfläche |
| **Debian 12 / Ubuntu 24.04 LTS** | Langzeit-Sicherheitsupdates, WireGuard im Kernel, Python ≥ 3.11 | Ubuntu 22.04 (Python 3.10): nicht unterstützt |
| **Python 3 + FastAPI** | Etabliert, automatische Eingabevalidierung mit Pydantic, wenig Code | Node/Go: möglich, aber kein Vorteil für das MVP |
| **SQLAlchemy + SQLite** | SQLite braucht keinen Serverprozess, ein Backup ist eine Datei. Mit SQLAlchemy reicht für den Wechsel zu PostgreSQL eine geänderte URL | Sofort PostgreSQL: zusätzlicher Dienst ohne Nutzen bei < 100 Nutzern |
| **argon2id** (argon2-cffi) | Aktueller Standard für Passwort-Hashing (RFC 9106) | bcrypt: ebenfalls ok, argon2id bevorzugt |
| **Eigener Agent statt Backend als root** | Ein Fehler im Web-Code darf nicht zu Root- oder Shell-Zugriff führen. Der Agent kennt nur 5 Operationen und prüft jede Eingabe erneut | Backend mit `sudo wg …`: große Angriffsfläche |
| **Schlüssel im Browser erzeugen** (`@noble/curves`, auditiert) | Der Server sieht den privaten Schlüssel nie. Eine Datenbank-Kompromittierung verrät damit keine Client-Schlüssel | Serverseitige Erzeugung: Server kennt alle Schlüssel |
| **React + TypeScript + Vite** | Vorgabe, typsicher, kleine statische Auslieferung durch das Backend (kein zweiter Webserver nötig) | – |
| **Keine Router-/UI-Bibliotheken** | 7 Seiten brauchen kein Framework. Weniger Abhängigkeiten bedeuten weniger Lieferkettenrisiko | react-router, UI-Kits |
| **Unbound** | Eigener Resolver: DNS-Anfragen verlassen den Server ohne Bezug zum Gerät. DNSSEC-Validierung, kein Query-Logging | Öffentliche Resolver (Dritte sehen alle Anfragen) |
| **nftables** | Aktueller Standard, atomares Neuladen eigener Tabellen ohne fremde Regeln zu löschen | iptables (veraltet), ufw (zu grob für NAT/DNS-Umleitung) |
| **systemd statt Docker auf dem Server** | WireGuard, NAT und Firewall müssen ohnehin auf dem Host laufen. systemd bietet Sandboxing (ProtectSystem, Capabilities, SystemCallFilter) ohne zusätzlichen Daemon | Docker: zusätzliche Komplexität und Netzwerk-Sonderfälle bei NAT und Firewall. Docker wurde nur als **Testumgebung** genutzt |
| **Weboberfläche nur im Tunnel (Standard)** | Keine öffentlich erreichbare Verwaltungsoberfläche, kein TLS-Zertifikat und keine Domain nötig | Öffentliche Web-UI: optional über `--domain` (Caddy + Let's Encrypt) |

## 4. Verzeichnisstruktur

```
Myvpn/
├── agent/                  dvpn-agent (privilegiert, nur Python-Standardbibliothek)
│   ├── dvpn_agent/         server.py (Operationen, Socket), validation.py, wg.py
│   └── tests/
├── backend/                dvpn-backend (FastAPI)
│   ├── dvpn/               main.py, config.py, models.py, services.py, security.py,
│   │   └── routers/        auth.py, devices.py, admin.py, info.py
│   ├── tests/              Unit- und API-Tests (inkl. echtem Agent über Unix-Socket)
│   ├── pyproject.toml
│   └── requirements.lock   fixierte Versionen für reproduzierbare Installation
├── frontend/               React + TypeScript (Vite)
│   └── src/                App.tsx, pages/, components/, lib/wg.ts (Schlüssel, Konfig)
├── deploy/
│   ├── install.sh          Installation/Update (idempotent)
│   ├── check.sh            Selbsttest des Servers
│   ├── uninstall.sh        sicheres Abschalten (optional mit vollständiger Löschung)
│   ├── render.py           erzeugt alle Konfigurationen aus validierten Parametern
│   └── templates/          wg0.conf, nftables, unbound, sysctl, systemd-Units, Caddyfile
├── tests/integration/      Ende-zu-Ende-Tests mit echtem WireGuard in Netzwerk-Namespaces
└── docs/                   diese Dokumentation
```

## 5. Sicherheitsgrenzen (Trust Boundaries)

1. **Internet → Server:** Offen sind nur SSH (Schlüssel-Login empfohlen) und UDP 51820. WireGuard beantwortet Pakete ohne gültigen Schlüssel nicht. Alles andere wird verworfen.
2. **VPN-Client → Server:** Clients erreichen nur DNS (53) und die Weboberfläche (8080) auf 10.8.0.1. Untereinander sind die Clients isoliert. Absenderadressen sind durch WireGuard-Cryptokey-Routing an den Schlüssel gebunden.
3. **Browser → Backend:** Authentifizierung mit Sitzungs-Cookie (HttpOnly, SameSite=Strict). CSRF-Schutz über Origin- und Fetch-Metadata-Prüfung plus Pflicht zu JSON. Rate-Limiting, strenge Validierung. Admin-Funktionen nur aus dem VPN oder lokal.
4. **Backend → Agent:** Unix-Socket (keine Netzwerkschnittstelle), Dateirechte plus SO_PEERCRED (nur Benutzer `dvpn`). Feste Operationen, erneute Validierung, nur `/32`- bzw. `/128`-Adressen aus dem VPN-Netz.
5. **Agent → Kernel:** `wg` wird nur mit Argumentlisten aufgerufen (`shell=False`), Geheimnisse gehen über stdin.

## 6. Externe Dienste und laufende Kosten

| Dienst | Pflicht? | Kosten/Monat |
|---|---|---|
| VPS mit deutscher IPv4 | ja | ca. 1–6 € (siehe [kosten.md](kosten.md)) |
| Domain | nein (die IP genügt als Endpunkt) | ca. 0,50–1,50 € |
| TLS-Zertifikat | nur für die öffentliche Web-UI | 0 € (Let's Encrypt) |
| Externe Analyse-, CDN- oder Font-Dienste | **nein, bewusst nicht genutzt** | 0 € |

## 7. Risiken und offene Entscheidungen

| Risiko | Bewertung | Maßnahme |
|---|---|---|
| Missbrauch der Server-IP durch Nutzer (Abuse, Urheberrecht) | hoch bei öffentlichem Betrieb | MVP privat, nur eingeladene Nutzer. Vor Öffnung: Nutzungsbedingungen und Abuse-Prozess, siehe [produktivbetrieb.md](produktivbetrieb.md) |
| Rechtliche Pflichten als TK-Anbieter (TKG, Meldepflicht, Auskunft) | vor öffentlichem Start zu klären | siehe [produktivbetrieb.md](produktivbetrieb.md) |
| Ausfall des einzelnen Servers | mittel | Backups, dokumentierte Wiederherstellung. Bewusst kein Multi-Server-Betrieb (Kosten) |
| Hoster sieht Metadaten bzw. kann den Server beschlagnahmen lassen | systemimmanent | Keine Verkehrs- oder DNS-Protokolle, Datensparsamkeit, transparente Doku |
| Geo-IP-Datenbanken ordnen die IP falsch zu | mittel | Vor dem Kauf prüfen (siehe [kosten.md](kosten.md)) |
| Leck bei Verbindungsabbruch | client-seitig | Kill-Switch und Always-on je Plattform dokumentiert |
| Kompromittierung des Backends | mittel | Agent-Trennung: Backend kann höchstens Peers im VPN-Netz anlegen oder löschen, keine Shell |

**Offene Entscheidungen** (für das MVP mit sicheren Standardwerten vorbelegt):

- Hosting-Anbieter → Empfehlung in [kosten.md](kosten.md), **Ihre Bestätigung nötig**
- IPv6 → Standard: IPv6 wird in den Tunnel gezogen (ULA-Adresse) und am Server sofort abgelehnt. Kein Leck, schneller Rückfall auf IPv4. Ausgang über die IPv6 des Servers optional mit `--ipv6-egress`, abschaltbar mit `--no-ipv6`
- Öffentliche Web-UI → Standard: nein (nur im Tunnel)
- Geschäftsmodell und Zahlungsabwicklung → nicht Teil des MVP
