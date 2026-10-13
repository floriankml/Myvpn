import { useEffect, useState, type FormEvent } from "react";
import { api, type User } from "../lib/api";
import { Alert, Badge, Card, Loading } from "../components/ui";
import { formatDate } from "../lib/format";

export function Admin({ user }: { user: User }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState("");
  const [secret, setSecret] = useState<{ username: string; password: string } | null>(null);
  const [name, setName] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  const load = () => api.get<User[]>("/api/admin/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const act = async (fn: () => Promise<unknown>) => {
    setError("");
    try { await fn(); load(); } catch (e) { setError((e as Error).message); }
  };

  const create = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      const r = await api.post<{ user: User; initial_password: string }>("/api/admin/users", { username: name, is_admin: isAdmin });
      setSecret({ username: r.user.username, password: r.initial_password });
      setName(""); setIsAdmin(false);
    });
  };

  return (
    <>
      <h1>Benutzerverwaltung</h1>
      <p className="muted">Nur aus dem VPN-Tunnel oder lokal (SSH-Tunnel) erreichbar.</p>
      {error && <Alert tone="error">{error}</Alert>}
      {secret && (
        <Alert tone="warn">
          Initialpasswort für <strong>{secret.username}</strong>: <code className="select-all">{secret.password}</code><br />
          Wird nur jetzt angezeigt. Übermitteln Sie es auf sicherem Weg; es muss bei der ersten Anmeldung geändert werden.
        </Alert>
      )}
      <Card title="Neuen Benutzer anlegen">
        <form className="row form-inline" onSubmit={create}>
          <label htmlFor="new-user" className="sr-only">Benutzername</label>
          <input id="new-user" required minLength={3} maxLength={32} pattern="[a-z0-9][a-z0-9\._\-]{2,31}"
                 placeholder="benutzername" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} />
          <label className="check">
            <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> Administrator
          </label>
          <button className="btn btn-primary" type="submit">Anlegen</button>
        </form>
      </Card>
      {!users ? <Loading /> : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Benutzer</caption>
            <thead><tr><th scope="col">Benutzer</th><th scope="col">Rolle</th><th scope="col">Status</th><th scope="col">Angelegt</th><th scope="col"><span className="sr-only">Aktionen</span></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <th scope="row">{u.username}</th>
                  <td>{u.is_admin ? "Administrator" : "Benutzer"}</td>
                  <td>{u.is_active ? <Badge tone="ok">aktiv</Badge> : <Badge tone="bad">gesperrt</Badge>}
                      {u.must_change_password && <> <Badge tone="warn">Initialpasswort</Badge></>}</td>
                  <td>{formatDate(u.created_at)}</td>
                  <td className="actions">
                    {u.id !== user.id && (
                      <>
                        <button type="button" className="btn btn-small" onClick={() => act(() =>
                          api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }))}>
                          {u.is_active ? "Sperren" : "Entsperren"}
                        </button>
                        <button type="button" className="btn btn-small" onClick={() => act(async () => {
                          const r = await api.post<{ initial_password: string }>(`/api/admin/users/${u.id}/reset-password`);
                          setSecret({ username: u.username, password: r.initial_password });
                        })}>Passwort zurücksetzen</button>
                        <button type="button" className="btn btn-small btn-danger" onClick={() => {
                          if (window.confirm(`Benutzer „${u.username}“ und alle Geräte endgültig löschen?`))
                            act(() => api.del(`/api/admin/users/${u.id}`));
                        }}>Löschen</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted">Gesperrte Benutzer verlieren sofort den VPN-Zugang aller ihrer Geräte.</p>
    </>
  );
}
