import { useEffect, useState } from "react";
import { api, type Connection, type Device, type Server } from "../lib/api";
import { Alert, Badge, Card, KeyValue, Loading } from "../components/ui";
import { formatAgo, formatBytes } from "../lib/format";

export function Dashboard() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [servers, setServers] = useState<Server[] | null>(null);
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    Promise.all([
      api.get<Connection>("/api/connection"),
      api.get<Server[]>("/api/servers"),
      api.get<Device[]>("/api/devices"),
    ])
      .then(([c, s, d]) => { setConn(c); setServers(s); setDevices(d); setError(""); })
      .catch((e) => setError((e as Error).message));
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!conn || !servers || !devices) return <Loading />;
  const server = servers[0];
  const active = devices.filter((d) => !d.revoked_at);
  const connected = active.filter((d) => d.connected);

  return (
    <>
      <h1>Dashboard</h1>
      <div className={`hero ${conn.via_vpn ? "hero-ok" : "hero-warn"}`} role="status" aria-live="polite">
        <div className="hero-icon" aria-hidden="true">{conn.via_vpn ? "🛡️" : "⚠️"}</div>
        <div>
          <h2>{conn.via_vpn ? "Dieser Browser ist über das VPN verbunden" : "Dieser Browser nutzt das VPN nicht"}</h2>
          <p>
            {conn.via_vpn
              ? <>Ihre Anfrage kam durch den WireGuard-Tunnel{conn.device ? <> von Gerät <strong>{conn.device.name}</strong> ({conn.device.ipv4})</> : null}. Ihr Internetverkehr verlässt das Netz über den Server in {server?.location ?? "Deutschland"}.</>
              : <>Der Server sieht Ihre Anfrage von <strong>{conn.client_ip}</strong>. Aktivieren Sie den Tunnel in der WireGuard-App, um eine deutsche IP-Adresse zu nutzen.</>}
          </p>
        </div>
      </div>

      <div className="grid">
        <Card title="Server">
          {server ? (
            <KeyValue items={[
              ["Name", server.name],
              ["Standort", server.location],
              ["Status", server.online ? <Badge tone="ok">Online</Badge> : <Badge tone="bad">Nicht erreichbar</Badge>],
              ["Öffentliche IPv4 (Ausgang)", server.public_ipv4 ?? "nicht hinterlegt"],
              ["IPv6", server.ipv6_egress ? "über den Tunnel ins Internet" : "im Tunnel blockiert (kein Leck)"],
            ]} />
          ) : <p>Kein Server konfiguriert.</p>}
        </Card>
        <Card title="Meine Geräte" actions={<a className="btn" href="#/geraete">Verwalten</a>}>
          <p className="big-number">{connected.length}<span> / {active.length} verbunden</span></p>
          <ul className="plain">
            {active.slice(0, 5).map((d) => (
              <li key={d.id}>
                <Badge tone={d.connected ? "ok" : "neutral"}>{d.connected ? "verbunden" : "inaktiv"}</Badge>{" "}
                <strong>{d.name}</strong> <span className="muted">· {d.ipv4} · {formatAgo(d.latest_handshake)} · ↓{formatBytes(d.tx_bytes)} ↑{formatBytes(d.rx_bytes)}</span>
              </li>
            ))}
          </ul>
          {active.length === 0 && <p>Noch keine Geräte. <a href="#/geraete">Jetzt ein Gerät hinzufügen.</a></p>}
        </Card>
      </div>
      <p className="small muted">
        „Verbunden“ bedeutet: In den letzten 3 Minuten fand ein WireGuard-Handshake statt. Diese Live-Werte
        werden direkt aus dem Server-Kernel gelesen und nicht gespeichert.
      </p>
    </>
  );
}
