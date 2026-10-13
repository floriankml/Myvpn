import { useEffect, useState, type FormEvent } from "react";
import { api, type Device, type User } from "../lib/api";
import { Alert, Badge, Card, Loading, Modal } from "../components/ui";
import { QrCode } from "../components/QrCode";
import { configFileName, generateKeyPair, isValidKey, renderConfig, type ConfigTemplate } from "../lib/wg";
import { formatAgo, formatBytes, formatDate } from "../lib/format";

const PLACEHOLDER = "<HIER_IHREN_PRIVATEN_SCHLÜSSEL_EINTRAGEN>";

interface Created { name: string; config: string; ownKey: boolean; applied: boolean }

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Devices({ user }: { user: User }) {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);

  const load = () =>
    api.get<Device[]>(`/api/devices${showAll ? "?all=true" : ""}`)
      .then((d) => { setDevices(d); setError(""); })
      .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [showAll]); // eslint-disable-line react-hooks/exhaustive-deps

  const revoke = async (d: Device) => {
    if (!window.confirm(`Gerät „${d.name}“ wirklich widerrufen? Der Zugang wird sofort gesperrt und kann nicht wiederhergestellt werden.`)) return;
    try {
      const r = await api.post<{ applied: boolean }>(`/api/devices/${d.id}/revoke`);
      setInfo(r.applied ? `„${d.name}“ wurde widerrufen und sofort gesperrt.`
        : `„${d.name}“ wurde widerrufen. Der Server war kurz nicht erreichbar – die Sperre wird innerhalb einer Minute wirksam.`);
      load();
    } catch (e) { setError((e as Error).message); }
  };

  const template = async (d: Device) => {
    try {
      const t = await api.get<ConfigTemplate>(`/api/devices/${d.id}/config`);
      download(configFileName(d.name), renderConfig(t, PLACEHOLDER));
    } catch (e) { setError((e as Error).message); }
  };

  const closeCreated = () => {
    setCreated(null);
    setOpen(false);
    load();
  };

  return (
    <>
      <div className="page-head">
        <h1>Geräte</h1>
        <button className="btn btn-primary" type="button" onClick={() => { setCreated(null); setOpen(true); }}>
          + Gerät hinzufügen
        </button>
      </div>
      <p className="muted">
        Jedes Gerät erhält ein eigenes Schlüsselpaar. Widerrufen Sie Geräte, die verloren gingen oder nicht mehr genutzt werden.
      </p>
      {user.is_admin && (
        <label className="check">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Geräte aller Benutzer anzeigen (Administration)
        </label>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      {info && <Alert tone="success">{info}</Alert>}
      {!devices ? <Loading /> : devices.length === 0 ? (
        <Card><p>Noch keine Geräte vorhanden.</p></Card>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Liste der Geräte</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                {showAll && <th scope="col">Benutzer</th>}
                <th scope="col">Status</th>
                <th scope="col">VPN-Adresse</th>
                <th scope="col">Letzter Handshake</th>
                <th scope="col">Daten ↓/↑</th>
                <th scope="col">Angelegt</th>
                <th scope="col"><span className="sr-only">Aktionen</span></th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.id} className={d.revoked_at ? "revoked" : ""}>
                  <th scope="row">{d.name}</th>
                  {showAll && <td>{d.owner}</td>}
                  <td>
                    {d.revoked_at ? <Badge tone="bad">widerrufen</Badge>
                      : d.connected ? <Badge tone="ok">verbunden</Badge> : <Badge tone="neutral">inaktiv</Badge>}
                  </td>
                  <td><code>{d.ipv4}</code>{d.ipv6 && <><br /><code className="small">{d.ipv6}</code></>}</td>
                  <td>{d.revoked_at ? "–" : formatAgo(d.latest_handshake)}</td>
                  <td>{d.revoked_at ? "–" : `${formatBytes(d.tx_bytes)} / ${formatBytes(d.rx_bytes)}`}</td>
                  <td>{formatDate(d.created_at)}</td>
                  <td className="actions">
                    {!d.revoked_at && (
                      <>
                        {(!showAll || d.owner === user.username) && (
                          <button type="button" className="btn btn-small" onClick={() => template(d)}
                                  title="Konfiguration ohne privaten Schlüssel herunterladen">Vorlage</button>
                        )}
                        <button type="button" className="btn btn-small btn-danger" onClick={() => revoke(d)}>
                          Widerrufen
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal title={created ? "Gerät eingerichtet" : "Neues Gerät"} open={open} onClose={closeCreated}>
        {created ? <CreatedView c={created} onClose={closeCreated} /> : <CreateForm onCreated={setCreated} />}
      </Modal>
    </>
  );
}

function CreateForm({ onCreated }: { onCreated: (c: Created) => void }) {
  const [name, setName] = useState("");
  const [ownKey, setOwnKey] = useState(false);
  const [pub, setPub] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (ownKey && !isValidKey(pub.trim())) {
      setError("Der öffentliche Schlüssel hat kein gültiges WireGuard-Format (44 Zeichen Base64).");
      return;
    }
    setBusy(true);
    try {
      // Schlüsselpaar lokal erzeugen – nur der öffentliche Schlüssel geht an den Server.
      const keys = ownKey ? { privateKey: PLACEHOLDER, publicKey: pub.trim() } : generateKeyPair();
      const r = await api.post<{ config: ConfigTemplate; applied: boolean }>("/api/devices", {
        name: name.trim(), public_key: keys.publicKey,
      });
      onCreated({ name: name.trim(), config: renderConfig(r.config, keys.privateKey), ownKey, applied: r.applied });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form" onSubmit={submit}>
      {error && <Alert tone="error">{error}</Alert>}
      <label htmlFor="dev-name">Gerätename</label>
      <input id="dev-name" required maxLength={40} value={name} placeholder="z. B. Pixel 8 oder Laptop"
             pattern="[\w äöüÄÖÜß\(\)\.,\+\-]{1,40}" onChange={(e) => setName(e.target.value)} />
      <details>
        <summary>Erweitert: eigenen Schlüssel verwenden</summary>
        <label className="check">
          <input type="checkbox" checked={ownKey} onChange={(e) => setOwnKey(e.target.checked)} />
          Ich habe in der WireGuard-App selbst ein Schlüsselpaar erzeugt
        </label>
        {ownKey && (
          <>
            <label htmlFor="dev-pub">Öffentlicher Schlüssel des Geräts</label>
            <input id="dev-pub" value={pub} onChange={(e) => setPub(e.target.value)} maxLength={44}
                   spellCheck={false} autoComplete="off" className="mono" />
          </>
        )}
      </details>
      <p className="small muted">
        Standard: Das Schlüsselpaar wird <strong>in Ihrem Browser</strong> erzeugt. Der private Schlüssel wird
        nicht an den Server übertragen und kann später nicht erneut angezeigt werden.
      </p>
      <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Wird erstellt …" : "Gerät erstellen"}</button>
    </form>
  );
}

function CreatedView({ c, onClose }: { c: Created; onClose: () => void }) {
  const [showText, setShowText] = useState(false);
  return (
    <div className="form">
      {!c.applied && <Alert tone="warn">Der VPN-Server war gerade nicht erreichbar. Das Gerät wird innerhalb einer Minute freigeschaltet.</Alert>}
      {c.ownKey ? (
        <Alert tone="info">Tragen Sie in der heruntergeladenen Datei Ihren privaten Schlüssel ein.</Alert>
      ) : (
        <Alert tone="warn">
          <strong>Nur jetzt sichtbar:</strong> Diese Konfiguration enthält den privaten Schlüssel. Sie wird nicht
          gespeichert. Scannen Sie den QR-Code oder laden Sie die Datei herunter und bewahren Sie sie sicher auf.
        </Alert>
      )}
      {!c.ownKey && (
        <div className="qr-wrap">
          <QrCode text={c.config} label={`QR-Code der WireGuard-Konfiguration für ${c.name}`} />
          <p className="small muted">In der WireGuard-App: „+“ → „QR-Code scannen“.</p>
        </div>
      )}
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={() => download(configFileName(c.name), c.config)}>
          Konfigurationsdatei herunterladen
        </button>
        <button type="button" className="btn" onClick={() => setShowText(!showText)} aria-expanded={showText}>
          {showText ? "Text ausblenden" : "Als Text anzeigen"}
        </button>
      </div>
      {showText && <pre className="config" tabIndex={0} aria-label="WireGuard-Konfiguration">{c.config}</pre>}
      <button type="button" className="btn" onClick={onClose}>Fertig</button>
    </div>
  );
}
