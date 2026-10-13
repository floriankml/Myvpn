# Kosten und VPS-Vergleich

> **Wichtig:** Die folgenden Angaben stammen aus einer Web-Recherche vom **13.10.2026** über **Drittquellen** (Vergleichsportale, Reviews). Die offiziellen Preisseiten der Anbieter waren aus der Entwicklungsumgebung **nicht abrufbar**, und die Quellen widersprechen sich teilweise, weil mehrere Anbieter 2026 die Preise angehoben haben. **Alle Werte sind daher unverifiziert.** Prüfen Sie Preis, Standort und Konditionen vor einer Bestellung im Bestellprozess des Anbieters. Es wird nichts ohne Ihre ausdrückliche Bestätigung bestellt.

> **Nur für Sie und Ihre Familie?** Kostenlose Varianten (zu Hause oder Oracle Free Tier) stehen in [kostenlos.md](kostenlos.md).

## 1. Was der Dienst braucht

| Ressource | Bedarf (privates MVP, < 20 Geräte) |
|---|---|
| CPU | 1 vCPU (WireGuard im Kernel ist sehr effizient) |
| RAM | 1 GB genügt (Backend ~70 MB, Unbound ~50 MB, OS); 2 GB komfortabel |
| Speicher | 10 GB+ SSD |
| Öffentliche IPv4 | **zwingend** (deutsche Ausgangs-IP) |
| IPv6 | optional (`--ipv6-egress`) |
| Traffic | **Hauptkostentreiber.** Beispiel: 5 Geräte × 50 GB = 250 GB/Monat. Gezählt wird Ein- und Ausgang des Servers, also etwa das Doppelte des Nutzerverkehrs |
| Bandbreite | 1 Gbit/s Port ist üblich und reicht |

## 2. Vergleich (Stand Recherche, unverifiziert)

| Anbieter / Tarif | Monatlich (ca.) | Traffic | IPv4 | Standort | Laufzeit | Hinweise |
|---|---|---|---|---|---|---|
| **Hetzner Cloud**, kleinster Shared-vCPU-Tarif (CX23, Nachfolger von CX22) | ca. **4–5,50 €** + ggf. 0,50 € IPv4 | 20 TB/Monat inklusive (EU), danach ca. 1 €/TB | ca. 0,50 €/Monat **oder** bereits im Preis enthalten (Quellen widersprechen sich) | Nürnberg, Falkenstein (eigene Rechenzentren) | **stundengenau, keine Mindestlaufzeit** | Preiserhöhungen April und Juni 2026. Kleine Tarife zeitweise „nicht verfügbar“ gemeldet. AV-Vertrag online abschließbar |
| **netcup** VPS „piko/nano“ (G11s) | ca. **1,05–2,09 €** (+ ggf. 0,50 € IPv4) | Flatrate mit Fair-Use-Drosselung | Angaben uneinheitlich | Nürnberg | **12 Monate Mindestlaufzeit** | Sehr günstig, aber feste Bindung. Preiserhöhung 2026 gemeldet |
| **IONOS** VPS Linux XS | ca. **1–2 €** (Aktionspreis) + Einrichtungsgebühr | „unbegrenzt“ bis 1 Gbit/s | inklusive | Deutschland (Rechenzentrum je nach Tarif prüfen) | oft 12 Monate | Aktionspreise erhöhen sich nach der Laufzeit. Sehr wenig RAM bei XS |
| **Contabo** Cloud VPS (kleinster Tarif) | ca. **4,50–5,40 €** | 32 TB bzw. Fair Use | inklusive | Deutschland (Nürnberg/Düsseldorf u. a.) | monatlich, längere Laufzeiten günstiger | Viel RAM fürs Geld. Netzqualität und Overselling werden in Reviews kritisch bewertet |

Quellen (Drittanbieter, Stand 08–10/2026):
[Hetzner-Preiserhöhung 2026 (findstack)](https://findstack.com/resources/hetzner-price-increase-2026) ·
[Cloud Pricing Comparison 2026-08](https://kimmo.suominen.com/stuff/cpc-2026-08.txt) ·
[Hetzner Pricing nach den Anpassungen 2026 (agentdeals)](https://agentdeals.dev/hetzner-pricing-2026) ·
[Hetzner Docs: IP pricing](https://docs.hetzner.com/general/infrastructure-and-availability/ipv4-pricing/) ·
[Hetzner Cloud Kosten (cloudtally)](https://cloudtally.eu/blog/hetzner-cloud-costs-youre-probably-missing) ·
[netcup piko/nano (mydealz, abgelaufener Deal)](https://www.mydealz.de/deals/netcup-vps-minis-piko-nano-mikro-2359193) ·
[netcup Preisänderung April 2026 (elest.io)](https://docs.elest.io/books/announcement/page/netcup-price-change-notice-effective-april-1st) ·
[netcup vServer Vergleich (hosttest)](https://www.hosttest.de/vergleich/netcup-vserver.html) ·
[IONOS VPS XS (whtop)](https://www.whtop.com/plans/ionos.de/137383) ·
[Contabo Cloud VPS 10 (whtop)](https://www.whtop.com/plans/contabo.com/133001) ·
[Contabo Preise 2026 (onedollarvps)](https://onedollarvps.com/de/pricing/contabo-pricing)

## 3. Empfehlung für das MVP

**Hetzner Cloud, kleinster verfügbarer Tarif, Standort Nürnberg oder Falkenstein.** Begründung:
- **Keine Mindestlaufzeit** (stundengenaue Abrechnung). Ideal zum Ausprobieren, jederzeit löschbar.
- 20 TB Traffic sind für den privaten Gebrauch praktisch unbegrenzt.
- Eigene Rechenzentren in Deutschland, deutscher Vertragspartner, AV-Vertrag nach Art. 28 DSGVO online.
- Debian 12 und Ubuntu 24.04 als Standard-Images, IPv6 inklusive.

**Günstigste Alternative bei langfristiger Nutzung:** netcup piko/nano (Nürnberg). Wegen der Mindestlaufzeit lohnt sich das erst, wenn das Projekt sicher weiterläuft.

## 4. Laufende Kosten (MVP)

| Posten | €/Monat |
|---|---|
| VPS (Empfehlung) | ca. 4,00–6,00 |
| Domain (optional) | ca. 0,50–1,50 |
| Let's-Encrypt-Zertifikat (nur bei `--domain`) | 0 |
| Backups: Anbieter-Snapshots (optional, ca. 20 % des Serverpreises) **oder** eigenes verschlüsseltes Backup auf vorhandenen Speicher | 0–1,20 |
| **Summe** | **ca. 4–9 €** |

## 5. Vor der Bestellung prüfen (Checkliste)

1. **Standort**: Im Bestellprozess ein Rechenzentrum in Deutschland (z. B. „Nürnberg“, „Falkenstein“) auswählen.
2. **Tatsächlicher Netzwerk-Austrittspunkt und Geo-IP:** Nach der Erstellung prüfen,
   - in der RIPE-Datenbank, ob das Netz der IPv4 als `country: DE` registriert ist (`whois <IP>`),
   - bei mehreren Geo-IP-Diensten (z. B. ipinfo.io, MaxMind-Demo, ip-api), wo die IP verortet wird. **Viele Streaming- und Banking-Dienste verwenden eigene Datenbanken.** Eine deutsche RIPE-Registrierung garantiert keine deutsche Einordnung überall.
   - Bei falscher Verortung den Server innerhalb der ersten Stunde löschen und neu erstellen (andere IP). Das geht bei stundengenauer Abrechnung ohne Mehrkosten.
3. **Latenz** von Ihrem Standort: `ping <IP>`, typischerweise 5–30 ms innerhalb Deutschlands.
4. **IPv4 inklusive?** Den Aufpreis im Bestellprozess prüfen.
5. **AV-Vertrag** (Art. 28 DSGVO) im Kundenportal abschließen.
6. **AGB zu VPN-/Proxy-Nutzung:** Manche Anbieter schränken das Weiterleiten fremden Verkehrs ein oder verlangen Abuse-Bearbeitung. Für die private Nutzung ist das in der Regel unkritisch, vor einem öffentlichen Angebot aber unbedingt prüfen.
