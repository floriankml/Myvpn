import { useEffect, useState } from "react";
import { api, type Server } from "../lib/api";
import { Alert, Badge, Card, KeyValue, Loading } from "../components/ui";

export function Servers() {
  const [servers, setServers] = useState<Server[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<Server[]>("/api/servers").then(setServers).catch((e) => setError(e.message));
  }, []);
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!servers) return <Loading />;
  return (
    <>
      <h1>Server</h1>
      <p className="muted">Verfügbare VPN-Server in Deutschland. Im MVP gibt es genau einen Server.</p>
      <div className="grid">
        {servers.map((s) => (
          <Card key={s.id} title={`🇩🇪 ${s.name}`}>
            <KeyValue items={[
              ["Status", s.online ? <Badge tone="ok">Online</Badge> : <Badge tone="bad">Nicht erreichbar</Badge>],
              ["Standort", s.location],
              ["Anbieter", s.provider || "–"],
              ["WireGuard-Endpunkt", <code key="e">{s.endpoint}</code>],
              ["Öffentliche IPv4", s.public_ipv4 ?? "–"],
              ["Öffentliche IPv6", s.ipv6_egress ? (s.public_ipv6 ?? "aktiv") : "nicht freigegeben"],
              ["Protokoll", "WireGuard (Curve25519, ChaCha20-Poly1305, BLAKE2s) + Pre-Shared-Key"],
            ]} />
          </Card>
        ))}
      </div>
    </>
  );
}
