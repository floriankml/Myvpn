# Kostenlos betreiben (privat, für Familie)

Kurzantwort: **Ja, das geht. Für Sie und Ihre Familie gibt es zwei praktisch kostenlose Wege.** Ganz ohne Kosten ist keiner davon, aber die laufenden Kosten liegen bei etwa 0–1 € pro Monat statt bei 4–9 €.

| Weg | Laufende Kosten | Ausgangs-IP | Eignung |
|---|---|---|---|
| **A. Zu Hause** (Raspberry Pi / Mini-PC / NAS) | nur Strom, ca. 1 €/Monat | **Ihr eigener Heimanschluss** (deutsch, wenn Sie in Deutschland wohnen) | **Empfohlen für Familie**, wenn Ihr Anschluss eine öffentliche IPv4 hat |
| **A'. Nur FRITZ!Box** (eingebautes WireGuard) | 0 € | Heimanschluss | Am einfachsten, aber ohne diese Weboberfläche und ohne DNS-Zwangsumleitung |
| **B. Oracle Cloud „Always Free“** (Rechenzentrum Frankfurt) | 0 € (Kreditkarte zur Verifizierung nötig) | Rechenzentrums-IP in Deutschland | Möglich, aber unsichere Verfügbarkeit, siehe unten |
| Zum Vergleich: kleiner VPS | ca. 4–9 € | Rechenzentrum DE | zuverlässigste Variante ([kosten.md](kosten.md)) |

Andere bekannte Gratis-Angebote passen nicht: Google Cloud bietet die kostenlose e2-micro nur in US-Regionen an, und AWS hat sein Free Tier auf zeitlich begrenzte Startguthaben umgestellt. Beide fallen damit als dauerhaft kostenlos in Deutschland weg.

---

## A. Betrieb zu Hause

### Voraussetzungen prüfen (wichtig!)

1. **Öffentliche IPv4-Adresse am Anschluss?** Viele Kabel- und Glasfaseranschlüsse nutzen **DS-Lite**. Dann haben Sie keine eigene öffentliche IPv4, und von außen ist Ihr Anschluss per IPv4 nicht erreichbar.
   - FRITZ!Box: *Internet → Online-Monitor*. Steht dort „DS-Lite“ oder eine IPv4 wie `100.64.x.x` bzw. `192.0.0.x`, haben Sie **keine** öffentliche IPv4.
   - Bei DS-Lite: Beim Anbieter eine öffentliche IPv4 bzw. „Dual Stack“ anfragen. Das ist oft kostenlos oder kostet wenige Euro. Andernfalls ist Weg B oder ein VPS sinnvoller (Clients in reinen IPv4-Netzen könnten sich sonst nicht verbinden).
2. **Gerät, das dauerhaft läuft:** z. B. Raspberry Pi 4/5 mit **Raspberry Pi OS (64 Bit, Debian 12 „Bookworm“)** oder **Ubuntu 24.04**, ein alter Mini-PC oder eine VM auf einem NAS. 1 GB RAM genügt.
3. **Dynamische IP:** Heimanschlüsse wechseln ihre IP. Dafür brauchen Sie einen **kostenlosen DynDNS-Namen**, z. B. MyFRITZ! (in der FRITZ!Box eingebaut) oder DuckDNS. Diesen Namen verwenden Sie als `--endpoint`.

### Einrichtung

1. **Router:** Dem Server eine feste lokale IP geben (DHCP-Reservierung) und **UDP 51820** an diese IP weiterleiten. Bei der FRITZ!Box: *Internet → Freigaben → Portfreigaben*. Keine weiteren Ports freigeben, auch nicht 8080 oder 22.
2. **Server installieren** wie in [deployment.md](deployment.md) ab Schritt 3. Statt der VPS-IP den DynDNS-Namen angeben:
   ```bash
   ./deploy/install.sh --endpoint <IHR-NAME>.myfritz.net --location "Zuhause" --provider "Eigenbetrieb"
   ```
   Die Weboberfläche bauen Sie auf Ihrem PC (`npm run build`) und kopieren sie mit, so wie in der Anleitung beschrieben. Node.js wird auf dem Pi nicht benötigt.
3. **Firewall:** `install.sh` richtet die Firewall auf dem Server ein. Der Router schützt zusätzlich, weil nur UDP 51820 freigegeben ist.
4. Admin, Geräte und Android: wie in [deployment.md](deployment.md) und [android.md](android.md).

### Was Sie wissen sollten

- **Ausgangs-IP ist Ihr Heimanschluss.** Alles, was die Familie über das VPN macht, erscheint im Internet mit **Ihrer** IP. Sie sind dafür als Anschlussinhaber verantwortlich. Für Familie ist das in der Regel unproblematisch. Geben Sie den Zugang aber nicht an Fremde weiter.
- **Upload-Geschwindigkeit begrenzt:** Unterwegs surft man mit höchstens der **Upload-Rate** Ihres Anschlusses (z. B. 40 Mbit/s bei Kabel, oft weniger bei DSL).
- **Stromausfall oder Router-Neustart:** Danach ist der Dienst kurz weg. Die automatische Wiederherstellung nach einem Neustart ist eingebaut und getestet.
- **Hinweis zur Prüfung:** `install.sh` ist auf Ubuntu 24.04 getestet. Raspberry Pi OS (Debian 12) wird vom Skript unterstützt, wurde aber **nicht** auf echter Hardware getestet.

### A'. Noch einfacher: nur die FRITZ!Box

Neuere FRITZ!Boxen (FRITZ!OS ab 7.50) haben **WireGuard eingebaut**: *Internet → Freigaben → VPN (WireGuard) → Verbindung hinzufügen*. Dort einen QR-Code für jedes Familiengerät erzeugen. Das kostet nichts extra und braucht keinen eigenen Server.

Was Sie damit **nicht** bekommen: diese Weboberfläche mit Geräteverwaltung durch jedes Familienmitglied, die DNS-Zwangsumleitung über einen eigenen Resolver ohne Logs, Client-Isolation und Statusanzeige. Für eine Familie mit wenigen Geräten reicht die FRITZ!Box-Lösung oft trotzdem.

---

## B. Oracle Cloud „Always Free“ (Frankfurt)

Oracle bietet dauerhaft kostenlose VMs an. Frankfurt (`eu-frankfurt-1`) ist als Heimatregion wählbar, die ARM-VMs (Ampere A1) eignen sich gut.

**Vorbehalte (unbedingt lesen):**
- **Kreditkarte** zur Identitätsprüfung nötig. Es gibt Berichte über abgelehnte Anmeldungen.
- **Kontingent unklar:** Offiziell waren es 4 OCPU / 24 GB RAM. Mehrere Berichte aus 2026 sprechen von einer stillen Halbierung auf 2 OCPU / 12 GB. Für dieses VPN reicht beides bei Weitem.
- **„Out of Capacity“:** Kostenlose ARM-VMs sind in beliebten Regionen oft nicht verfügbar, man muss es wiederholt versuchen. Die **Heimatregion lässt sich später nicht ändern**, also beim Anlegen des Kontos Frankfurt wählen.
- **Inaktive Free-Instanzen** können von Oracle zurückgefordert werden. Oracle-Konten wurden in Einzelfällen ohne Vorwarnung gesperrt. Halten Sie deshalb Backups bereit ([wartung.md](wartung.md)).
- Das Traffic-Freikontingent (bisher 10 TB/Monat) ist für die Familie mehr als genug, aber nicht aktuell verifiziert.

**Einrichtung (Kurzfassung):**
1. Instanz *Ubuntu 24.04 (aarch64)*, Shape *VM.Standard.A1.Flex*, mit öffentlicher IPv4 und eigenem SSH-Schlüssel anlegen.
2. In der **Security List** des VCN **UDP 51820** eingehend erlauben (SSH 22 ist dort standardmäßig offen).
3. Oracles Ubuntu-Images bringen eigene `iptables`-Regeln mit, die alles außer SSH abweisen. Diese würden WireGuard blockieren. Vor der Installation entfernen:
   ```bash
   sudo apt remove -y iptables-persistent netfilter-persistent || true
   sudo iptables -F && sudo iptables -X     # Regeln leeren; danach übernimmt dvpn-firewall (nftables)
   ```
   Die Firewall von DeutschlandVPN schützt den Server danach selbst (Standard: alles verwerfen).
4. Weiter mit [deployment.md](deployment.md) ab Schritt 2.
5. Geo-IP der zugewiesenen Adresse prüfen ([kosten.md](kosten.md), Abschnitt 5).

Nicht getestet: Die Installation wurde nicht auf einer echten Oracle-Instanz ausgeführt (ARM und Oracle-Image).

Quellen (Stand Recherche 13.10.2026, teils widersprüchlich):
[Oracle Docs: Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) ·
[TerminalBytes: Oracle Free Tier Changes 2026](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026) ·
[space-node: Oracle Cloud Free VPS 2026](https://space-node.net/blog/oracle-cloud-free-vps-guide-2026) ·
[Medium: Always Free VPS Guide](https://medium.com/@imvinojanv/setup-always-free-vps-with-4-ocpu-24gb-ram-and-200gb-storage-the-ultimate-oracle-cloud-guide-bed5cbf73d34)

---

## Empfehlung

- **Familie, Anschluss mit öffentlicher IPv4:** **Weg A** (Raspberry Pi oder Mini-PC zu Hause) mit dieser Software. Wem die Weboberfläche nicht wichtig ist, nimmt **A'** (nur FRITZ!Box).
- **DS-Lite zu Hause oder Wunsch nach Rechenzentrums-IP:** **Weg B** ausprobieren. Klappt die Anmeldung oder die Kapazität nicht, ist ein VPS für ca. 4 €/Monat die verlässliche Alternative.
- **Rechtlich** ist der rein private Betrieb für die eigene Familie deutlich unkritischer als ein öffentliches Angebot. Die Pflichten aus [produktivbetrieb.md](produktivbetrieb.md), Teil A (TKG-Meldepflicht, AGB usw.), betreffen vor allem Angebote an die Öffentlichkeit. Im Zweifel fachkundig prüfen lassen.
