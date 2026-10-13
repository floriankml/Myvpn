# Noch erforderliche Schritte für einen öffentlichen Produktivbetrieb

Das MVP ist für den **privaten Betrieb** (Sie und eingeladene Personen) ausgelegt. Vor einem **öffentlichen oder kostenpflichtigen** Angebot sind mindestens die folgenden Punkte zu erledigen. Die rechtlichen Punkte sind **Hinweise, keine Rechtsberatung**. Bitte von einer Fachanwältin bzw. einem Fachanwalt (IT-/Telekommunikationsrecht) und ggf. einer Steuerberatung prüfen lassen.

## A. Rechtliches (vor dem Start prüfen)

| # | Thema | Was zu prüfen ist |
|---|---|---|
| A1 | **Einordnung als Telekommunikationsdienst (TKG)** | Ob ein öffentlich angebotener VPN-Dienst als (öffentlich zugänglicher) Telekommunikationsdienst gilt und welche Pflichten folgen: **Meldepflicht bei der Bundesnetzagentur (§ 5 TKG)**, Kundenschutzvorschriften, Sicherheitskonzept (§ 165 ff. TKG) |
| A2 | **Fernmeldegeheimnis** (§ 3 TDDDG) | Verpflichtung aller Personen mit Serverzugriff, Organisation der Zugriffe |
| A3 | **Speicherpflichten / IP-Adressen-Speicherung** | Die frühere Vorratsdatenspeicherung (§§ 175 ff. TKG) wird nach EuGH- und BVerwG-Urteilen nicht angewendet. **Zum aktuellen Stand neuer Regelungen (z. B. geplante IP-Adressen-Speicherpflicht) gibt es hier keine verlässliche Information. Vor dem Start unbedingt prüfen.** Eine solche Pflicht würde die Datenschutzzusagen ([datenschutz.md](datenschutz.md)) direkt ändern |
| A4 | **Auskunftsersuchen und Überwachung** | Pflichten bei Bestands- und Verkehrsdatenauskünften (§§ 172 ff. TKG). TKÜV-Pflichten hängen von der Teilnehmerzahl ab. Internen Prozess für Behördenanfragen festlegen |
| A5 | **Haftung für Nutzerverhalten** | Haftungsprivileg für reine Durchleitung (§ 8 DDG), Umgang mit Abmahnungen (z. B. Filesharing), Sperranspruch (§ 8 Abs. 4/§ 7 DDG) |
| A6 | **DSGVO** | Datenschutzerklärung (Art. 13), Verzeichnis von Verarbeitungstätigkeiten (Art. 30), TOMs (Art. 32), **AV-Vertrag mit dem Hoster** (Art. 28), Prozess für Betroffenenanfragen und Datenpannen (Art. 33/34), ggf. Datenschutz-Folgenabschätzung |
| A7 | **Impressum** | § 5 DDG (Digitale-Dienste-Gesetz) |
| A8 | **Verträge** | AGB/Nutzungsbedingungen (verbotene Nutzung, Abuse, Sperrung), bei Verbrauchern: Widerrufsbelehrung, Button-Lösung, Kündigungsbutton (§ 312k BGB) |
| A9 | **Werbeaussagen** | Keine irreführenden Versprechen („anonym“, „No-Logs“, „100 % sicher“), UWG. Aussagen müssen [datenschutz.md](datenschutz.md) entsprechen |
| A10 | **Steuern/Gewerbe** | Gewerbeanmeldung, Umsatzsteuer (ggf. Kleinunternehmerregelung), Buchhaltung, Aufbewahrungspflichten für Rechnungen. **Diese stehen in Konflikt mit Datensparsamkeit und sind getrennt zu speichern** |
| A11 | **Hoster-AGB** | Erlaubt der Hoster öffentliche VPN-Dienste? Wie läuft die Abuse-Bearbeitung? |

## B. Technik

| # | Schritt | Grund |
|---|---|---|
| B1 | **Kernel-WireGuard und Agent ohne root auf dem Zielsystem verifizieren** (`systemctl status dvpn-agent`, Gerät anlegen und widerrufen) | In der Entwicklungsumgebung nur mit `wireguard-go` und Agent als root getestet |
| B2 | **IPv6-Tests auf dem echten Server ausführen** (`test_05`, `test_14`) | Entwicklungsumgebung ohne IPv6 |
| B3 | **Echte Endgeräte testen**: Android, iOS, Windows, macOS, Linux, inkl. Leak-Tests und Kill-Switch | Nur mit Linux-Clients (wg-quick) getestet |
| B4 | Öffentliche Weboberfläche über HTTPS (`--domain`) inkl. Sicherheitsheadern, HSTS, ggf. **2-Faktor-Anmeldung (TOTP/WebAuthn)** für Admins | Admin-Zugang schützen |
| B5 | **Selbstregistrierung** mit E-Mail-Verifikation, Passwort-Reset, Captcha bzw. Missbrauchsschutz | MVP: nur Einladung durch Admin |
| B6 | **Zahlungsanbindung** (z. B. Stripe, Mollie, PayPal) mit minimaler Datenübernahme | Geschäftsmodell |
| B7 | **PostgreSQL + Alembic-Migrationen** | Mehrere Prozesse/Server, kontrollierte Schemaänderungen. SQLite und `create_all` reichen nur für das MVP |
| B8 | **Mehrere Server**: Agent je Server (z. B. über WireGuard-Management-Netz oder mTLS statt Unix-Socket), Server-Auswahl in der UI, Lastverteilung | MVP: ein Server (bewusst, Kosten) |
| B9 | **Monitoring/Alarmierung** ohne personenbezogene Daten (z. B. Uptime-Check auf `/api/health` über das VPN, Prometheus-Node-Exporter nur lokal, Plattenplatz, Zertifikatsablauf) | Ausfälle bemerken |
| B10 | **Rate-Limiter mit gemeinsamem Speicher** (z. B. Redis) bei mehr als einem Backend-Prozess | Rate-Limiter derzeit im Speicher eines Prozesses |
| B11 | **Abuse-Schutz**: Port 25 ist bereits gesperrt. Ergänzend ggf. Bandbreitenbegrenzung pro Nutzer (`tc`) und ein Prozess für Abuse-Meldungen | Schutz der IP-Reputation |
| B12 | **Externer Penetrationstest** bzw. Code-Review durch Dritte | Unabhängige Prüfung |
| B13 | **Reproduzierbare Builds/CI**: Tests bei jedem Commit, `requirements.lock` mit Hashes (`pip-compile --generate-hashes`), signierte Releases, Dependabot o. ä. | Lieferkettensicherheit |
| B14 | **Backups automatisieren** (systemd-Timer, verschlüsselt, extern) und Wiederherstellung regelmäßig testen | Betriebssicherheit |
| B15 | **Hochverfügbarkeit** nach Bedarf (zweiter Server, DNS-Failover) | Single Point of Failure |
| B16 | **Barrierefreiheit** durch Nutzertests mit Screenreadern (NVDA, TalkBack, VoiceOver) und ggf. BITV/WCAG-Audit prüfen lassen | Bisher nur technisch umgesetzt (Semantik, Fokus, Kontraste) |

## C. Organisation

- Verantwortliche Person für Betrieb und Sicherheit, Vertretungsregelung
- Notfallplan: Kompromittierung, Datenpanne (72-Stunden-Meldepflicht), Beschlagnahme
- Supportkanal und Statusseite
- Transparenzbericht (optional, vertrauensbildend)
