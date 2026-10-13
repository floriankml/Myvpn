# Sicherheitsdokumentation

## 1. Kryptografie

- **WireGuard** (Noise_IKpsk2): Curve25519 (Schlüsseltausch), ChaCha20-Poly1305 (Verschlüsselung), BLAKE2s (Hash), HKDF. Es gibt keine Algorithmen-Auswahl und damit keine Fehlkonfiguration.
- **Pre-Shared-Key je Gerät** (32 Byte aus dem Betriebssystem-CSPRNG, wie `wg genpsk`). Er bildet eine zusätzliche symmetrische Schicht als Schutz gegen „jetzt speichern, später mit Quantencomputer entschlüsseln“.
- **Keine eigene Kryptografie.** Schlüssel erzeugen das offizielle `wg` (Server und CLI) bzw. `@noble/curves` (auditierte X25519-Implementierung) im Browser. Ein Test vergleicht die Browser-Schlüssel mit `wg pubkey`.
- **Passwörter:** argon2id (argon2-cffi, Parameter nach RFC 9106). Bei unbekanntem Benutzernamen wird ein Dummy-Hash geprüft (gleiche Antwortzeit).
- **Sitzungen:** 256-Bit-Zufallstoken. In der Datenbank liegt nur der SHA-256-Hash.

## 2. Schlüsselverwaltung

| Schlüssel | Erzeugt von | Gespeichert | Rechte |
|---|---|---|---|
| Server-Privatschlüssel | `wg genkey` bei der Installation | `/etc/wireguard/wg0.key`, `/etc/wireguard/wg0.conf` | root, 0600 |
| Server-Öffentlicher Schlüssel | abgeleitet | Kernel; über den Agent abfragbar | öffentlich |
| Geräte-Privatschlüssel | **Browser des Nutzers** (bzw. `dvpn-admin` lokal) | **nirgends auf dem Server**, nur in der App bzw. Datei des Nutzers | – |
| Geräte-Öffentlicher Schlüssel | Browser | Datenbank, Kernel, Agent-Zustand | dvpn 0600 / dvpn-agent 0600 |
| Pre-Shared-Key | Backend (CSPRNG) | Datenbank, Kernel, Agent-Zustand. Wird bei Widerruf gelöscht | 0600 |
| Initialpasswörter | Backend/CLI (≈ 120 Bit) | **nicht gespeichert**, nur einmal angezeigt | – |

Die Konfiguration mit privatem Schlüssel wird **genau einmal** angezeigt (QR-Code bzw. Download) und lässt sich nicht erneut abrufen. Für ein neues Gerät legt man ein neues Gerät an und widerruft das alte.

## 3. Sichere Provisionierung neuer Geräte

1. Ein Nutzer meldet sich an. Konten legt nur ein Admin an, Initialpasswörter müssen bei der ersten Anmeldung geändert werden.
2. Der Browser erzeugt das Schlüsselpaar und sendet **nur den öffentlichen Schlüssel**.
3. Das Backend prüft Format, Duplikate (auch gegen den Server-Schlüssel), das Gerätelimit (Standard 5) und das Rate-Limit (10 pro Stunde). Danach vergibt es die nächste freie Adresse.
4. Der Agent prüft erneut: Schlüsselformat, nur `/32`- bzw. `/128`-Adressen innerhalb des VPN-Netzes, keine reservierten oder doppelten Adressen. Erst dann setzt er den Peer.
5. Der Browser setzt die Konfiguration zusammen und zeigt QR-Code und Download an.

**Bootstrap** (erstes Gerät, bevor die Weboberfläche über VPN erreichbar ist): `dvpn-admin create-device <user> "<Name>" --qr` auf dem Server. Alternativ ein SSH-Tunnel zur Weboberfläche.

## 4. Sperrung kompromittierter Geräte

- **Weboberfläche** → Geräte → „Widerrufen“, oder **CLI** `dvpn-admin revoke-device <id>`.
- Die Datenbank ist maßgeblich. Der Peer wird sofort aus dem Kernel entfernt, WireGuard verwirft danach jedes Paket dieses Schlüssels. Ein E2E-Test weist das nach: Nach dem Widerruf läuft die Verbindung in einen Timeout.
- Ist der Agent gerade nicht erreichbar, entfernt der nächste Abgleich den Peer (alle 60 s). Auch der persistierte Agent-Zustand wird dabei korrigiert. Das ist getestet.
- **Konto sperren** (Admin) entfernt sofort alle Peers des Nutzers und beendet seine Sitzungen.
- Bei Verdacht auf Kompromittierung des **Servers**: Serverschlüssel rotieren, siehe [wartung.md](wartung.md).

## 5. Schutz vor Befehlsinjektion und Rechteausweitung

- Das Backend hat **keine** Rechte am Netzwerk (`CapabilityBoundingSet=` leer, eigener Benutzer, `NoNewPrivileges`, `ProtectSystem=strict`, `SystemCallFilter`).
- Systembefehle führt **nur der Agent** aus: `wg show|set` als **Argumentliste** (`subprocess.run([...], shell=False)`). Es gibt keine String-Verkettung und keine Shell. Pre-Shared-Keys gehen über stdin, damit sie nicht in der Prozessliste erscheinen.
- Der Agent kennt genau die Operationen `ping`, `info`, `status`, `upsert_peer`, `remove_peer` und `sync`. Unbekannte Operationen oder Felder werden abgelehnt (getestet, u. a. mit `{"op":"exec"}` und Shell-Metazeichen).
- Selbst ein vollständig kompromittiertes Backend könnte über den Agenten nur Peers mit Einzeladressen im VPN-Netz anlegen oder entfernen. `0.0.0.0/0`, fremde Netze und die Serveradresse werden abgelehnt.
- `render.py` validiert alle Installationsparameter (Interface-Namen, Hostnamen, Ports, Texte) per Positivliste, bevor sie in Firewall- oder Konfigurationsvorlagen eingesetzt werden.

## 6. Web- und API-Sicherheit

| Maßnahme | Umsetzung |
|---|---|
| Authentifizierung | Sitzungs-Cookie `HttpOnly`, `SameSite=Strict`, `Secure` (bei HTTPS), Ablauf nach 12 h, serverseitig widerrufbar |
| Autorisierung | Nutzer sehen nur eigene Geräte. Für fremde IDs gibt es dieselbe 404-Antwort (keine IDOR-Hinweise). Konfigurationen erhält nur der Eigentümer, auch Admins nicht |
| Admin-Funktionen | Rolle **und** Quell-IP aus dem VPN-Netz oder localhost |
| CSRF | SameSite=Strict, Origin muss zum Host passen, `Sec-Fetch-Site: cross-site` wird abgelehnt, nur `application/json` |
| Rate-Limiting | 300 API-Anfragen pro Minute und IP. Login: 10 pro 5 min und IP sowie 10 pro 15 min und Konto. Gerätanlage: 10 pro Stunde |
| Eingabevalidierung | Pydantic mit `extra="forbid"` (keine Massenzuweisung), Regex-Positivlisten, Längenbegrenzungen |
| Fehlerbehandlung | Generische Fehlermeldungen ohne Stacktrace. Validierungsfehler geben keine Eingabewerte zurück (keine Passwörter im Response) |
| Security-Header | strikte CSP (`default-src 'self'`, keine Inline-Skripte), `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `Cache-Control: no-store` für die API |
| Keine externen Ressourcen | Keine CDNs, Fonts oder Tracker. QR-Codes werden lokal erzeugt |
| API-Dokumentation | `/api/docs` standardmäßig **aus** |

## 7. Firewall, Ports und Routing

| Port | Protokoll | Von | Zweck |
|---|---|---|---|
| 22 (bzw. konfiguriert) | TCP | Internet | SSH-Administration (limitiert auf 20 neue Verbindungen pro Minute) |
| 51820 | UDP | Internet | WireGuard |
| 53 | UDP/TCP | **nur wg0** | Unbound-DNS |
| 8080 | TCP | **nur wg0** | Weboberfläche/API (Bindung zusätzlich nur an 10.8.0.1) |
| 80, 443 | TCP | Internet | **nur** mit `--domain` (Caddy, öffentliche Web-UI) |

- **Forward-Policy DROP.** Erlaubt ist nur `wg0 → WAN` aus dem VPN-Netz. **Client-Isolation**: `wg0 → wg0` wird verworfen.
- **Port 25 (SMTP) aus dem Tunnel gesperrt** (Spam-Schutz; 465/587 bleiben offen).
- **NAT:** `masquerade` auf dem WAN-Interface (IPv4; IPv6 nur mit `--ipv6-egress`).
- **MSS-Clamping** gegen MTU-Probleme.
- **sysctl:** `ip_forward=1`, `rp_filter=1`, keine ICMP-Redirects, SYN-Cookies, `accept_ra=2` auf dem WAN-Interface (die IPv6-Default-Route bleibt erhalten).

## 8. Leckschutz

### DNS-Leaks
- Clients bekommen `DNS = 10.8.0.1` (und die IPv6-ULA des Servers).
- **Erzwungen auf dem Server:** Jede unverschlüsselte DNS-Anfrage (Port 53) aus dem Tunnel, egal an welche Adresse, wird per DNAT auf Unbound umgeleitet. Getestet mit Anfragen an den Provider-DNS und an `9.9.9.9`: Der „Provider“ sieht nur die Server-IP.
- Grenzen: DNS-over-HTTPS (z. B. im Browser) und DNS-over-TLS (Android „Privates DNS“) laufen zwar **durch den Tunnel** (kein Leck zum Internetanbieter), umgehen aber den eigenen Resolver.

### IPv6-Leaks
- Client-Konfigurationen enthalten **immer** `AllowedIPs = 0.0.0.0/0, ::/0`. Damit wird IPv6 in den Tunnel gezogen, auch wenn der Server kein IPv6 ins Internet leitet.
- **Standard:** Der Tunnel hat eine ULA-Adresse (`fdxx::/64`). IPv6-Verkehr aus dem Tunnel wird am Server mit ICMP „admin-prohibited“ **sofort abgelehnt**, Apps fallen ohne Wartezeit auf IPv4 zurück.
- **Optional** `--ipv6-egress`: IPv6 geht per NAT66 über die IPv6 des Servers ins Internet.
- Hinweis: Die IPv6-Tests (`test_05`, `test_14`) konnten in der Entwicklungsumgebung nicht laufen (Kernel mit `ipv6.disable=1`). Sie müssen auf dem echten Server ausgeführt werden, siehe [tests.md](tests.md).

### Leaks bei Verbindungsabbruch (Kill-Switch)
WireGuard ist zustandslos: Fällt der Server aus, bleibt der Tunnel auf dem Gerät „aktiv“ und der Verkehr läuft **nicht** ungeschützt am Tunnel vorbei, solange das Interface besteht. Leaks entstehen vor allem, wenn der Tunnel deaktiviert ist oder das Betriebssystem ihn umgeht:

| Plattform | Maßnahme |
|---|---|
| Android | „Durchgehend aktives VPN“ **und** „Verbindungen ohne VPN blockieren“ (Systemeinstellungen) |
| iOS | „Bei Bedarf aktivieren“. iOS kann bereits bestehende Verbindungen beim Einschalten am Tunnel vorbeiführen, daher Apps nach dem Verbinden neu starten |
| Windows | Kill-Switch-Option der WireGuard-App („Block untunneled traffic“), bei `0.0.0.0/0` standardmäßig aktiv |
| macOS | „Bei Bedarf aktivieren“ |
| Linux | `wg-quick` mit Policy-Routing. Für einen harten Kill-Switch eine nftables-Regel, die nur wg0 und den Endpunkt erlaubt (siehe unten) |

Beispiel für einen harten Kill-Switch unter Linux (Client, optional):
```bash
# Erlaubt nur Verkehr über das Tunnel-Interface und zum WireGuard-Server selbst.
sudo nft add table inet killswitch
sudo nft add chain inet killswitch out '{ type filter hook output priority 0; policy drop; }'
sudo nft add rule inet killswitch out oifname "lo" accept
sudo nft add rule inet killswitch out oifname "dvpn" accept
sudo nft add rule inet killswitch out ip daddr <SERVER_IPV4> udp dport 51820 accept
# Aufheben: sudo nft delete table inet killswitch
```

## 9. Wiederherstellung nach Neustart

Die Boot-Reihenfolge per systemd: `dvpn-firewall` → `wg-quick@wg0` → `unbound` → `dvpn-agent` (stellt Peers aus `/var/lib/dvpn-agent/peers.json` wieder her, **auch ohne Backend**) → `dvpn-backend` (gleicht beim Start und alle 60 s mit der Datenbank ab). Bei einem Neustart von `wg-quick@wg0` startet der Agent automatisch mit (`PartOf=`). Getestet: echter systemd-Neustart im Container, Namespace-Szenarien mit verlorenem Interface und verlorenem Agent-Zustand.

## 10. Grenzen und Restrisiken

- **Ein VPN anonymisiert nicht.** Der Betreiber, also Sie, und der Hoster könnten Verkehr technisch beobachten. Webseiten erkennen Nutzer weiterhin über Cookies und Fingerprinting.
- **Ein einzelner Server** ist ein Single Point of Failure.
- **Geteilte IP:** Missbrauch durch einen Nutzer fällt auf alle zurück.
- **HTTP im Tunnel:** Die Weboberfläche nutzt im privaten Modus HTTP. Der Transport ist durch WireGuard verschlüsselt, der Browser behandelt die Seite aber nicht als „sicheren Kontext“. Deshalb ist das Cookie dort nicht `Secure`. Wer das nicht möchte, nutzt `--domain` (HTTPS).
- **Agent ohne root:** Der Agent läuft produktiv als eigener Benutzer mit nur `CAP_NET_ADMIN` (Kernel-WireGuard). Dieser Betrieb ohne root konnte in der Entwicklungsumgebung nicht getestet werden, weil kein WireGuard-Kernelmodul vorhanden war. Siehe [tests.md](tests.md).
- **In-Memory-Rate-Limiter:** gilt nur für einen Prozess. Das Backend muss daher mit genau einem Worker laufen (so konfiguriert).
- **SQLite:** Nicht für viele parallele Schreibzugriffe gedacht. Für das MVP ist das ausreichend; danach steht PostgreSQL an.
