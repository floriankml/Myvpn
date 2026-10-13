import { Card } from "../components/ui";

export function Installation() {
  return (
    <>
      <h1>Installation</h1>
      <p>
        Die Verbindung wird über die <strong>offizielle WireGuard-App</strong> hergestellt – nicht über diese Webseite.
        Legen Sie zuerst unter <a href="#/geraete">Geräte</a> eine Konfiguration an.
      </p>

      <Card title="Android">
        <ol>
          <li>„WireGuard“ (Herausgeber: WireGuard Development Team) aus dem Google Play Store oder F-Droid installieren.</li>
          <li>Hier im Browser des Computers unter <a href="#/geraete">Geräte</a> „Gerät hinzufügen“ wählen.</li>
          <li>In der App auf <strong>+</strong> → <strong>QR-Code scannen</strong> tippen und den Code scannen. Einen Namen vergeben.</li>
          <li>Den Schalter neben dem Tunnel aktivieren und die Android-Anfrage zur VPN-Verbindung bestätigen.</li>
          <li>
            <strong>Leckschutz (empfohlen):</strong> Einstellungen → Netzwerk &amp; Internet → VPN → Zahnrad bei WireGuard →
            „Durchgehend aktives VPN“ <em>und</em> „Verbindungen ohne VPN blockieren“ einschalten.
          </li>
          <li>Prüfen: Dashboard dieser Seite über <code>http://10.8.0.1:8080</code> öffnen – es sollte „über das VPN verbunden“ anzeigen.</li>
        </ol>
      </Card>

      <Card title="iPhone / iPad (iOS)">
        <ol>
          <li>„WireGuard“ aus dem App Store installieren.</li>
          <li><strong>+</strong> → „Aus QR-Code erstellen“ und den Code scannen, oder die .conf-Datei über „Aus Datei oder Archiv erstellen“ importieren.</li>
          <li>VPN-Konfiguration erlauben und den Tunnel einschalten.</li>
          <li>Leckschutz: Tunnel bearbeiten → „Bei Bedarf aktivieren“ für WLAN und Mobilfunk einschalten. iOS kann in seltenen Fällen bestehende Verbindungen außerhalb des Tunnels weiterführen; nach dem Einschalten Apps neu starten.</li>
        </ol>
      </Card>

      <Card title="Windows">
        <ol>
          <li>WireGuard von <code>wireguard.com/install</code> herunterladen und installieren.</li>
          <li>Unter <a href="#/geraete">Geräte</a> die Konfigurationsdatei herunterladen.</li>
          <li>In WireGuard: „Tunnel aus Datei importieren“ → Datei wählen → „Aktivieren“.</li>
          <li>Leckschutz: Beim Bearbeiten des Tunnels die Kill-Switch-Option („Block untunneled traffic“) aktiviert lassen.
            Sie ist bei <code>AllowedIPs = 0.0.0.0/0, ::/0</code> standardmäßig aktiv.</li>
          <li>Konfigurationsdatei danach löschen – sie enthält Ihren privaten Schlüssel.</li>
        </ol>
      </Card>

      <Card title="macOS">
        <ol>
          <li>„WireGuard“ aus dem Mac App Store installieren.</li>
          <li>„Tunnel aus Datei importieren“ → heruntergeladene .conf wählen → „Aktivieren“.</li>
          <li>Optional: „Bei Bedarf aktivieren“ für dauerhafte Nutzung.</li>
        </ol>
      </Card>

      <Card title="Linux">
        <ol>
          <li>Pakete installieren: <code>sudo apt install wireguard-tools resolvconf</code> (Debian/Ubuntu).</li>
          <li>Datei sicher ablegen:
            <pre>sudo install -m 600 dvpn-laptop.conf /etc/wireguard/dvpn.conf</pre>
          </li>
          <li>Verbinden: <code>sudo wg-quick up dvpn</code> · Trennen: <code>sudo wg-quick down dvpn</code></li>
          <li>Autostart: <code>sudo systemctl enable --now wg-quick@dvpn</code></li>
          <li>Status: <code>sudo wg show</code></li>
          <li>Alternativ: NetworkManager-Import mit <code>nmcli connection import type wireguard file dvpn.conf</code>.</li>
        </ol>
        <p className="small muted">
          wg-quick leitet bei <code>0.0.0.0/0, ::/0</code> den gesamten Verkehr per Policy-Routing durch den Tunnel.
          Ein vollständiger Kill-Switch bei manuellem Abschalten ist damit nicht gegeben – siehe Dokumentation (docs/sicherheit.md).
        </p>
      </Card>

      <Card title="Verbindung prüfen">
        <ul>
          <li>Öffentliche IP: Eine beliebige „Wie ist meine IP“-Seite muss die IPv4-Adresse des deutschen Servers zeigen.</li>
          <li>DNS-Leak: Ein DNS-Leak-Test darf nur den Resolver des VPN-Servers zeigen, nicht den Ihres Providers.</li>
          <li>IPv6: Ohne IPv6-Freigabe dürfen IPv6-Tests <em>keine</em> Adresse Ihres Heimanschlusses zeigen.</li>
        </ul>
      </Card>
    </>
  );
}
