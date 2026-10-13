# Android-Smartphone verbinden

Dauer: ca. 5 Minuten. Sie brauchen ein Benutzerkonto bei DeutschlandVPN und **einen zweiten Bildschirm** (Computer) für den QR-Code. Alternativ geht es mit einer Konfigurationsdatei.

## 1. WireGuard-App installieren

Installieren Sie **„WireGuard“** vom Herausgeber **„WireGuard Development Team“** aus dem Google Play Store (oder F-Droid). Andere Apps mit ähnlichem Namen sind nicht offiziell.

## 2. Konfiguration erzeugen

**Variante A – Weboberfläche (empfohlen):**
1. Öffnen Sie auf dem Computer die Weboberfläche: über ein bereits verbundenes Gerät unter `http://10.8.0.1:8080` oder über den SSH-Tunnel (siehe [deployment.md](deployment.md)).
2. Melden Sie sich an. Beim ersten Login müssen Sie Ihr Initialpasswort ändern.
3. **Geräte** → **„+ Gerät hinzufügen“** → Namen eingeben (z. B. „Pixel 8“) → **„Gerät erstellen“**.
4. Ein QR-Code erscheint. **Er ist nur jetzt sichtbar.** Der private Schlüssel wurde in Ihrem Browser erzeugt und nicht an den Server übertragen.

**Variante B – durch die Administration (erste Einrichtung):**
Die Administration führt auf dem Server `dvpn-admin create-device <benutzer> "Pixel 8" --qr` aus und zeigt Ihnen den QR-Code im Terminal.

## 3. In der App importieren

1. WireGuard-App öffnen → unten rechts **„+“** → **„QR-Code scannen“**.
2. Kamerazugriff erlauben und den QR-Code scannen.
3. Einen Tunnelnamen vergeben, z. B. `dvpn`.
4. Den **Schalter** neben dem Tunnel einschalten.
5. Android fragt **„Verbindungsanfrage“** → **„OK“**. Oben erscheint ein Schlüssel-Symbol.

*(Mit Konfigurationsdatei: „+“ → „Aus Datei oder Archiv importieren“. Löschen Sie die Datei danach aus dem Download-Ordner.)*

## 4. Leckschutz aktivieren (dringend empfohlen)

Damit kein Verkehr ungeschützt läuft, z. B. nach einem Neustart oder wenn die App beendet wird:

1. **Einstellungen** → **Netzwerk & Internet** → **VPN**. Je nach Hersteller z. B. auch unter „Verbindungen → Weitere Verbindungseinstellungen → VPN“.
2. Auf das **Zahnrad** neben **WireGuard** tippen.
3. **„Durchgehend aktives VPN“** (Always-on VPN) einschalten.
4. **„Verbindungen ohne VPN blockieren“** einschalten.

Zusätzlich, für DNS über den VPN-Server:
- **Einstellungen** → **Netzwerk & Internet** → **Privates DNS** → **„Aus“** oder **„Automatisch“**. Mit einem fest eingetragenen Anbieter (z. B. dns.google) laufen DNS-Anfragen zwar verschlüsselt durch den Tunnel, aber an diesen Anbieter statt an den VPN-Server.

## 5. Verbindung prüfen

1. Im Browser des Smartphones `http://10.8.0.1:8080` öffnen und anmelden. Das **Dashboard** muss zeigen: **„Dieser Browser ist über das VPN verbunden“** mit Ihrem Gerätenamen.
2. Eine Seite wie „Wie ist meine IP?“ öffnen. Angezeigt werden muss die **IPv4 des deutschen Servers** und nicht die Ihres Mobilfunk- oder WLAN-Anbieters.
3. DNS-Leak-Test (z. B. dnsleaktest.com → „Standard test“). Angezeigt werden dürfen nur der VPN-Server bzw. dessen Netz.
4. In der WireGuard-App auf den Tunnel tippen. **„Letzter Handshake“** sollte wenige Sekunden bis 2 Minuten alt sein.

## 6. Häufige Probleme

| Problem | Lösung |
|---|---|
| „Handshake did not complete“ | Mobilfunk/WLAN blockiert UDP? Anderes Netz testen. Serveradresse und Port in der Konfiguration prüfen |
| Verbunden, aber Seiten laden nicht | Tunnel bearbeiten → **MTU = 1280** eintragen → speichern → neu verbinden |
| Akku | `PersistentKeepalive = 25` hält die Verbindung hinter NAT aktiv. Wenn der Status „verbunden“ nicht wichtig ist, kann der Wert in der App auf leer gesetzt werden |
| Gerät verloren/verkauft | Sofort in der Weboberfläche unter **Geräte** → **„Widerrufen“**. Der Zugang ist damit sofort gesperrt |
| Neues Handy | Neues Gerät anlegen, altes widerrufen. Konfigurationen werden nicht kopiert |
