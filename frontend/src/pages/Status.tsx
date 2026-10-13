import { useEffect, useState } from "react";
import { api, type Status, type User } from "../lib/api";
import { Alert, Badge, Card, KeyValue, Loading } from "../components/ui";

export function StatusPage({ user }: { user: User }) {
  const [st, setSt] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Date | null>(null);
  const load = () =>
    api.get<Status>("/api/status")
      .then((s) => { setSt(s); setChecked(new Date()); setError(""); })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!st) return <Loading />;
  const ok = st.agent && st.interface_up;
  return (
    <>
      <div className="page-head">
        <h1>Status</h1>
        <button type="button" className="btn" onClick={load}>Aktualisieren</button>
      </div>
      <div className={`hero ${ok ? "hero-ok" : "hero-bad"}`} role="status" aria-live="polite">
        <div className="hero-icon" aria-hidden="true">{ok ? "✅" : "❌"}</div>
        <div>
          <h2>{ok ? "VPN-Dienst betriebsbereit" : "Störung"}</h2>
          <p>Zuletzt geprüft: {checked?.toLocaleTimeString("de-DE")}</p>
        </div>
      </div>
      <div className="grid">
        <Card title="Komponenten">
          <KeyValue items={[
            ["Verwaltungs-Backend", <Badge key="b" tone="ok">läuft</Badge>],
            ["WireGuard-Agent", st.agent ? <Badge tone="ok">erreichbar</Badge> : <Badge tone="bad">nicht erreichbar</Badge>],
            ["WireGuard-Interface", st.interface_up ? <Badge tone="ok">aktiv</Badge> : <Badge tone="bad">inaktiv</Badge>],
            ...(user.is_admin ? [
              ["Konfigurierte Peers", st.peers_configured ?? "–"],
              ["Aktive Peers (≤ 3 min)", st.peers_active ?? "–"],
            ] as [string, string | number][] : []),
          ]} />
        </Card>
        <Card title="Technische Details">
          <KeyValue items={[
            ["UDP-Port", st.listen_port ?? "–"],
            ["Server-Schlüssel", st.server_public_key ? <code key="k" className="small break">{st.server_public_key}</code> : "–"],
            ["VPN-Netz IPv4", <code key="4">{st.subnet_v4}</code>],
            ["VPN-Netz IPv6", st.subnet_v6 ? <code key="6">{st.subnet_v6}</code> : "–"],
            ["DNS im Tunnel", st.dns_servers.join(", ")],
            ["IPv6-Strategie", st.ipv6_egress ? "IPv6 wird über den Server ins Internet geleitet"
              : "IPv6 wird in den Tunnel gezogen und dort blockiert (Leckschutz)"],
          ]} />
        </Card>
      </div>
    </>
  );
}
