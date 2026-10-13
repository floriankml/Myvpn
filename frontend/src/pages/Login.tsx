import { useState, type FormEvent } from "react";
import { api, type User } from "../lib/api";
import { Alert } from "../components/ui";

export function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await api.post<User>("/api/auth/login", { username, password }));
    } catch (err) {
      setError((err as Error).message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login" id="main">
      <form className="card login-card" onSubmit={submit} aria-describedby={error ? "login-error" : undefined}>
        <h1>DeutschlandVPN</h1>
        <p className="muted">Bitte melden Sie sich an, um Ihre VPN-Geräte zu verwalten.</p>
        {error && <div id="login-error"><Alert tone="error">{error}</Alert></div>}
        <label htmlFor="username">Benutzername</label>
        <input id="username" name="username" autoComplete="username" required autoFocus
               value={username} onChange={(e) => setUsername(e.target.value)} maxLength={64} />
        <label htmlFor="password">Passwort</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required
               value={password} onChange={(e) => setPassword(e.target.value)} maxLength={256} />
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? "Anmelden …" : "Anmelden"}
        </button>
        <p className="small muted">
          Konten werden von der Administration angelegt. Es gibt keine öffentliche Registrierung.
        </p>
      </form>
    </main>
  );
}
