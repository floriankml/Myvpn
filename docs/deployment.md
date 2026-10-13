# Phase 4 – Deployment auf einem deutschen VPS (Schritt für Schritt)

> **Bevor Sie beginnen:** Schritt 1 erzeugt **Kosten** bei einem Hoster. Diese Anleitung führt niemand automatisch aus. Sie entscheiden und bestellen selbst. Platzhalter stehen in `<SPITZEN_KLAMMERN>`.

## 0. Voraussetzungen auf Ihrem Rechner

- Git, ein SSH-Client und **Node.js ≥ 20.19** (für den einmaligen Build der Weboberfläche)
- Ein SSH-Schlüsselpaar: `ssh-keygen -t ed25519 -C "dvpn-admin"`

```bash
git clone <REPO_URL> Myvpn
cd Myvpn/frontend && npm ci && npm run build && cd ..   # erzeugt frontend/dist
```

## 1. VPS bestellen (kostenpflichtig, Ihre Entscheidung)

1. Anbieter und Tarif wählen, siehe [kosten.md](kosten.md).
2. Standort **Deutschland** (z. B. Nürnberg/Falkenstein), Image **Debian 12** oder **Ubuntu 24.04**.
3. Ihren **öffentlichen SSH-Schlüssel** hinterlegen. Kein Passwort-Login.
4. Öffentliche **IPv4** aktivieren. IPv6 kann aktiv bleiben.
5. Optional: In der Firewall des Anbieters nur TCP 22 und UDP 51820 (und ggf. 80/443) erlauben, als zusätzliche Schutzschicht.
6. Geo-IP-Prüfung durchführen, siehe [kosten.md](kosten.md), Abschnitt 5.

## 2. Server grundlegend absichern

```bash
ssh root@<SERVER_IP>
apt update && apt full-upgrade -y
# Optional: eigener Admin-Benutzer statt root
adduser <ADMIN_NAME> && usermod -aG sudo <ADMIN_NAME>
install -d -m 700 -o <ADMIN_NAME> -g <ADMIN_NAME> /home/<ADMIN_NAME>/.ssh
cp ~/.ssh/authorized_keys /home/<ADMIN_NAME>/.ssh/ && chown <ADMIN_NAME>: /home/<ADMIN_NAME>/.ssh/authorized_keys
# SSH härten (ERST testen, dass der Schlüssel-Login mit dem neuen Benutzer funktioniert!)
cat > /etc/ssh/sshd_config.d/10-dvpn.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
systemctl reload ssh
```

## 3. Code übertragen

Von Ihrem Rechner aus (mit gebautem `frontend/dist`):
```bash
rsync -a --exclude node_modules --exclude .git ./ root@<SERVER_IP>:/root/Myvpn/
```

## 4. Installation

```bash
ssh root@<SERVER_IP>
cd /root/Myvpn
./deploy/install.sh --endpoint <SERVER_IP_ODER_DNS_NAME> --location "<STADT>" --provider "<ANBIETER>"
```

Optionen:

| Option | Bedeutung |
|---|---|
| `--endpoint` | **Pflicht.** Öffentliche IPv4 oder DNS-Name, wie ihn Clients erreichen |
| `--ipv6-egress` | IPv6 der Clients über die IPv6 des Servers ins Internet leiten (NAT66) |
| `--no-ipv6` | kein IPv6 im Tunnel (IPv6 wird trotzdem in den Tunnel gezogen und verworfen) |
| `--ssh-port N` | falls SSH nicht auf 22 läuft (wird sonst automatisch erkannt) |
| `--wg-port N` | WireGuard-Port (Standard 51820/udp) |
| `--domain <NAME>` | öffentliche Weboberfläche über HTTPS (Caddy, Let's Encrypt). DNS-A-Record muss vorher auf den Server zeigen |
| `--yes` | ohne Rückfrage |

Das Skript:
- installiert `wireguard-tools nftables unbound python3-venv qrencode unattended-upgrades`,
- legt die Systembenutzer `dvpn` und `dvpn-agent` an (ohne Login-Shell),
- erzeugt den Server-Schlüssel (`/etc/wireguard/wg0.key`, 0600) und ein zufälliges IPv6-ULA-Präfix,
- rendert und prüft Firewall (`nft -c`), WireGuard, Unbound, sysctl und systemd-Units,
- installiert Python-Abhängigkeiten aus `backend/requirements.lock` (fixierte Versionen),
- begrenzt das Journal auf 7 Tage und aktiviert automatische Sicherheitsupdates,
- startet alle Dienste und prüft, dass sie laufen.

Die Konfiguration steht in `/etc/dvpn/dvpn.env` (Backend) und `/etc/dvpn/agent.env` (Agent). Diese Dateien werden **nur beim ersten Lauf** angelegt. Nach eigenen Änderungen: `systemctl restart dvpn-backend` bzw. `dvpn-agent`. Um Netzwerkparameter (z. B. IPv6) nachträglich zu ändern, die beiden `.env`-Dateien löschen und `install.sh` mit den neuen Optionen erneut ausführen.

## 5. Erstes Admin-Konto und erstes Gerät

```bash
dvpn-admin create-admin <ADMIN_NAME>          # fragt nach einem Passwort (mind. 12 Zeichen)
dvpn-admin create-device <ADMIN_NAME> "Pixel 8" --qr
```
QR-Code mit der WireGuard-App scannen, siehe [android.md](android.md). Der private Schlüssel wird nicht gespeichert.

Als Datei (z. B. für einen Laptop). `umask 077` sorgt dafür, dass nur Sie die Datei lesen können:
```bash
(umask 077; dvpn-admin create-device <ADMIN_NAME> "Laptop" > /root/laptop.conf)
# übertragen (scp), importieren, danach auf dem Server löschen: shred -u /root/laptop.conf
```

## 6. Weboberfläche

- **Über VPN:** Tunnel aktivieren und `http://10.8.0.1:8080` öffnen.
- **Per SSH-Tunnel** (ohne VPN): `ssh -L 8080:10.8.0.1:8080 root@<SERVER_IP>`, dann `http://localhost:8080`.
- Weitere Nutzer: Weboberfläche → „Benutzer“ → anlegen. Das Initialpasswort wird einmalig angezeigt.

## 7. Prüfen

```bash
./deploy/check.sh                      # Dienste, Firewall, DNS, Rechte, Bindung
wg show                                # Peers und letzte Handshakes
```

Vom Client aus (verbunden):
- Eine „Wie ist meine IP“-Seite muss die Server-IPv4 zeigen.
- DNS-Leak-Test (z. B. dnsleaktest.com): Es darf nur die Server-IP bzw. deren Resolver erscheinen.
- IPv6-Test (z. B. test-ipv6.com): **keine** IPv6 Ihres Heimanschlusses.
- Optional, auf dem Server, die vollständige Testsuite (siehe [tests.md](tests.md)): `apt install wireguard-go dnsutils iputils-ping curl` und dann die Integrationstests. Sie laufen in isolierten Namespaces und verändern den Produktivbetrieb nicht.

## 8. Benötigte Ressourcen, Ports und Dateien (Übersicht)

| Was | Wert |
|---|---|
| Server | 1 vCPU, 1–2 GB RAM, 10+ GB SSD, öffentliche IPv4 |
| Offene Ports (Internet) | TCP 22 (SSH), UDP 51820 (WireGuard), optional TCP 80/443 |
| Nur im Tunnel | UDP/TCP 53 (DNS), TCP 8080 (Web/API) |
| VPN-Netz | 10.8.0.0/24 (Server 10.8.0.1, Geräte ab .2), IPv6-ULA `fdxx:xxxx:xxxx::/64` |
| IP-Forwarding/NAT | `/etc/sysctl.d/99-dvpn.conf`, `/etc/dvpn/nftables.nft` (`dvpn-firewall.service`) |
| DNS | `/etc/unbound/unbound.conf.d/dvpn.conf` |
| Schlüssel | `/etc/wireguard/wg0.key`, `/etc/wireguard/wg0.conf` (root 0600) |
| Daten | `/var/lib/dvpn/dvpn.db` (dvpn 0600), `/var/lib/dvpn-agent/peers.json` (0600) |
| Programme | `/opt/dvpn/src`, `/opt/dvpn/venv` (root, nur lesbar für Dienste) |
| Dienste | `dvpn-firewall`, `wg-quick@wg0`, `unbound`, `dvpn-agent`, `dvpn-backend` |

## 9. Fehlersuche

| Symptom | Prüfen |
|---|---|
| App verbindet, aber kein Internet | `wg show` (Handshake?), `nft list table ip dvpn_nat` (masquerade auf dem richtigen WAN-Interface?), `sysctl net.ipv4.ip_forward` |
| Kein Handshake | UDP 51820 in der Anbieter-Firewall offen? Endpunkt/IP korrekt? Uhrzeit des Geräts korrekt? |
| Webseiten laden nicht, Ping geht | DNS: `dig @10.8.0.1 example.com`, `journalctl -u unbound`. MTU: `MTU = 1280` in der Client-Konfiguration testen |
| Weboberfläche nicht erreichbar | Nur im Tunnel erreichbar! `systemctl status dvpn-backend`, `journalctl -u dvpn-backend` |
| „VPN-Server derzeit nicht erreichbar“ in der UI | `systemctl status dvpn-agent`, `journalctl -u dvpn-agent` |
