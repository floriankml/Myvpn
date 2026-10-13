import { api, type User } from "../lib/api";
import { Card } from "../components/ui";
import { ChangePassword } from "./ChangePassword";

export function Settings({ user, onLogout }: { user: User; onLogout: () => void }) {
  const exportData = async () => {
    const data = await api.get<unknown>("/api/auth/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `dvpn-datenauskunft-${user.username}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const logoutAll = async () => {
    if (!window.confirm("Alle Sitzungen (auch diese) abmelden?")) return;
    await api.post("/api/auth/logout-all");
    onLogout();
  };

  return (
    <>
      <h1>Einstellungen</h1>
      <div className="grid">
        <ChangePassword onDone={() => undefined} />
        <Card title="Sitzungen & Daten">
          <p>Konto: <strong>{user.username}</strong>{user.is_admin && " (Administrator)"}</p>
          <div className="stack">
            <button type="button" className="btn" onClick={logoutAll}>Überall abmelden</button>
            <button type="button" className="btn" onClick={exportData}>Meine gespeicherten Daten herunterladen (Art. 15 DSGVO)</button>
          </div>
          <p className="small muted">Eine Sitzung läuft nach spätestens 12 Stunden automatisch ab.</p>
        </Card>
      </div>

      <Card title="Datenschutz – was wir speichern und was nicht">
        <h3>Dauerhaft gespeichert (Datenbank)</h3>
        <ul>
          <li>Benutzername, Passwort-Hash (argon2id), Rolle, Anlagedatum</li>
          <li>Je Gerät: Name, öffentlicher Schlüssel, Pre-Shared-Key, VPN-Adresse, Anlage- und Widerrufsdatum</li>
          <li>Login-Sitzungen (nur als Hash, bis zum Ablauf)</li>
          <li>Widerrufene Geräte werden nach 30 Tagen automatisch gelöscht.</li>
        </ul>
        <h3>Technisch vorhanden, aber nicht gespeichert</h3>
        <ul>
          <li>Ihre reale IP-Adresse und der Zeitpunkt des letzten Handshakes liegen im Arbeitsspeicher des WireGuard-Kernels, solange der Tunnel besteht.
            Die IP-Adresse wird von uns weder ausgelesen noch protokolliert; Handshake-Zeit und Datenvolumen werden nur live angezeigt.</li>
          <li>NAT-Verbindungstabellen (conntrack) des Servers enthalten aktive Verbindungen für wenige Minuten im RAM.</li>
          <li>Rate-Limiting hält Anfrage-IP-Adressen maximal 15 Minuten im RAM.</li>
        </ul>
        <h3>Nicht erfasst</h3>
        <ul>
          <li>Keine Surfverläufe, keine aufgerufenen Ziele, keine DNS-Anfrageprotokolle, keine Webserver-Zugriffslogs, kein Tracking, keine Analyse-Cookies.</li>
        </ul>
        <p className="small muted">
          Hinweis: Ihr Hosting-Anbieter und Internetknoten können Metadaten (z. B. Verkehrsmengen zum Server) sehen.
          Wir geben bewusst kein pauschales „No-Logs“-Versprechen ab, sondern beschreiben die tatsächliche Datenlage.
        </p>
      </Card>

      <Card title="Sicherheitshinweise">
        <ul>
          <li>Widerrufen Sie verlorene oder verkaufte Geräte sofort unter <a href="#/geraete">Geräte</a>.</li>
          <li>Löschen Sie heruntergeladene Konfigurationsdateien nach dem Import – sie enthalten Ihren privaten Schlüssel.</li>
          <li>Aktivieren Sie „Durchgehend aktives VPN“ bzw. den Kill-Switch Ihrer WireGuard-App (siehe <a href="#/installation">Installation</a>).</li>
        </ul>
      </Card>
    </>
  );
}
