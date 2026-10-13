# Phase 5 – Wartung, Backups, Schlüsselrotation, Abschaltung

## 1. Updates

| Was | Wie | Wann |
|---|---|---|
| Betriebssystem (Sicherheitsupdates) | automatisch per `unattended-upgrades` (von `install.sh` aktiviert) | täglich |
| Kernel-Updates | `needrestart` bzw. `/var/run/reboot-required` prüfen → `reboot` | monatlich bzw. nach Meldung |
| Alle Pakete | `apt update && apt full-upgrade` | monatlich |
| DeutschlandVPN selbst | lokal: `git pull`, Tests ausführen, `cd frontend && npm ci && npm run build`; dann `rsync` auf den Server und `./deploy/install.sh --endpoint <…> --yes` (idempotent, behält Schlüssel, Datenbank und `.env`) | bei neuen Versionen |
| Python-Abhängigkeiten | `backend/requirements.lock` aktualisieren (neue venv, `pip install ./backend`, `pip freeze`), Tests ausführen, dann deployen. Sicherheitsprüfung: `pip install pip-audit && pip-audit -r backend/requirements.lock` | monatlich |
| Frontend-Abhängigkeiten | `npm audit`, `npm outdated`, nach Updates `npm test && npm run build` | monatlich |

Vor jedem Update ein Backup anlegen (siehe unten). Nach jedem Update `./deploy/check.sh` ausführen.

## 2. Backups

**Was gesichert werden muss:**

| Datei | Inhalt | Sensibel? |
|---|---|---|
| `/var/lib/dvpn/dvpn.db` | Konten, Geräte, PSKs | **ja** |
| `/etc/wireguard/wg0.key` | Server-Privatschlüssel | **sehr** (ohne ihn müssen alle Geräte neu eingerichtet werden) |
| `/etc/dvpn/` | Konfiguration, ULA-Präfix | gering |

Nicht nötig: `/var/lib/dvpn-agent/peers.json` (wird aus der Datenbank wiederhergestellt) und `/opt/dvpn` (wird von `install.sh` neu erstellt).

**Backup erstellen (verschlüsselt mit `age`):**
```bash
apt install -y age sqlite3
install -d -m 700 /root/backup
TS=$(date +%F)
sqlite3 /var/lib/dvpn/dvpn.db ".backup '/root/backup/dvpn-$TS.db'"     # konsistente Kopie im laufenden Betrieb
tar -C / -czf - root/backup/dvpn-$TS.db etc/wireguard/wg0.key etc/dvpn \
  | age -r <IHR_AGE_PUBLIC_KEY> > /root/backup/dvpn-$TS.tar.gz.age
shred -u /root/backup/dvpn-$TS.db
# Danach die .age-Datei vom Server herunterladen (scp) und auf dem Server löschen.
```
Den privaten `age`-Schlüssel nur offline aufbewahren, nicht auf dem Server. Empfehlung: wöchentlich und vor jedem Update, Aufbewahrung 4 Wochen (Datensparsamkeit: alte Backups löschen).

**Wiederherstellung (neuer Server):**
```bash
age -d -i <AGE_PRIVATE_KEY_DATEI> dvpn-<DATUM>.tar.gz.age | tar -C /tmp/restore -xzf -
install -d -m 700 /etc/wireguard && install -m 600 /tmp/restore/etc/wireguard/wg0.key /etc/wireguard/wg0.key
cp -r /tmp/restore/etc/dvpn /etc/            # ULA-Präfix und .env übernehmen
./deploy/install.sh --endpoint <NEUE_IP_ODER_DNS> --yes   # nutzt vorhandenen Schlüssel
systemctl stop dvpn-backend
install -m 600 -o dvpn -g dvpn /tmp/restore/root/backup/dvpn-<DATUM>.db /var/lib/dvpn/dvpn.db
systemctl start dvpn-backend                 # Abgleich setzt alle Peers in WireGuard
rm -rf /tmp/restore
```
Wenn sich die Server-IP ändert und Clients die IP statt eines DNS-Namens nutzen, müssen sie den **Endpunkt** in ihrer App anpassen. Ein DNS-Name als Endpunkt vermeidet das.

## 3. Schlüsselrotation

| Schlüssel | Vorgehen | Auswirkung |
|---|---|---|
| **Geräteschlüssel + PSK** | Neues Gerät anlegen, altes widerrufen | nur dieses Gerät |
| **Server-Schlüssel** (bei Verdacht auf Kompromittierung, sonst z. B. jährlich) | siehe unten | **alle** Geräte brauchen den neuen Server-Schlüssel |
| **Admin-Passwörter** | Einstellungen → Passwort ändern (beendet andere Sitzungen) | – |
| **SSH-Schlüssel** | neuen Schlüssel in `authorized_keys`, alten entfernen | – |

**Server-Schlüssel rotieren:**
```bash
umask 077
cp /etc/wireguard/wg0.key /root/wg0.key.alt          # nur bis zur Umstellung aufbewahren
wg genkey > /etc/wireguard/wg0.key
./deploy/install.sh --endpoint <ENDPUNKT> --yes       # schreibt wg0.conf mit neuem Schlüssel, startet neu
wg show wg0 public-key                                  # neuen öffentlichen Schlüssel notieren
shred -u /root/wg0.key.alt
```
Danach müssen alle Nutzer entweder **ein neues Gerät anlegen** (empfohlen, erneuert auch ihren eigenen Schlüssel) oder in der App unter Peer den **öffentlichen Schlüssel** durch den neuen ersetzen. Der Server kennt die privaten Geräteschlüssel nicht und kann deshalb keine fertigen Konfigurationen verteilen. Das ist eine bewusste Sicherheitseigenschaft.

## 4. Sicheres Abschalten

**Vorübergehend** (alle Verbindungen sofort trennen, Daten bleiben):
```bash
./deploy/uninstall.sh
```
Das stoppt Backend, Agent und WireGuard, entfernt Firewall- und NAT-Regeln sowie die Unbound-Konfiguration und schaltet IP-Forwarding ab. Wieder einschalten: `./deploy/install.sh …`.

**Endgültig:**
1. Nutzer rechtzeitig informieren und Daten auf Wunsch herausgeben (Datenauskunft in der Weboberfläche).
2. `./deploy/uninstall.sh --purge` (fragt nach Bestätigung „LÖSCHEN“). Löscht Schlüssel, Datenbank, Konfiguration, Programme und Systembenutzer.
3. Beim Hoster: **Server löschen**, ebenso **alle Snapshots und Backups**. Danach den Vertrag kündigen.
4. Eigene Offline-Backups nach Ablauf eventueller Aufbewahrungspflichten löschen.
5. DNS-Einträge (falls vorhanden) entfernen.

Getestet: Beide Varianten wurden in einem Ubuntu-24.04-Container mit systemd ausgeführt, siehe [tests.md](tests.md).

## 5. Checkliste für regelmäßige Sicherheitsprüfungen

**Wöchentlich (5 Minuten)**
- [ ] `./deploy/check.sh` ohne Fehler
- [ ] `wg show`: keine unbekannten Peers (Anzahl = aktive Geräte in der UI)
- [ ] `journalctl -p warning --since "-7d"`: keine auffälligen Fehler

**Monatlich**
- [ ] Updates (Abschnitt 1), ggf. Neustart, danach `check.sh`
- [ ] `pip-audit` und `npm audit` ohne offene Sicherheitslücken
- [ ] Benutzerliste prüfen: Wer braucht keinen Zugang mehr? → sperren oder löschen
- [ ] Geräteliste (alle Benutzer) prüfen: Alte, lange inaktive Geräte widerrufen
- [ ] Backup erstellen und **Wiederherstellbarkeit stichprobenartig testen**
- [ ] Offene Ports von außen prüfen (von einem anderen Rechner): `nmap -sU -p 51820 <IP>`; `nmap -p- <IP>` → nur SSH (und ggf. 80/443) offen
- [ ] Leak-Tests mit einem Client (IP, DNS, IPv6)

**Jährlich bzw. anlassbezogen**
- [ ] Server-Schlüssel rotieren (Abschnitt 3)
- [ ] SSH-Schlüssel der Administration prüfen und rotieren
- [ ] Diese Dokumentation und die Datenschutzerklärung mit dem tatsächlichen Stand abgleichen
- [ ] Rechtslage (TKG, Speicherpflichten) neu prüfen, siehe [produktivbetrieb.md](produktivbetrieb.md)
- [ ] Hoster-Vertrag, AV-Vertrag und Kosten prüfen
