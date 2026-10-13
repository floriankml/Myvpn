import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { Alert, Card } from "../components/ui";

export function ChangePassword({ forced, onDone, onLogout }: {
  forced?: boolean; onDone: () => void; onLogout?: () => void;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [msg, setMsg] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== repeat) {
      setMsg({ tone: "error", text: "Die neuen Passwörter stimmen nicht überein." });
      return;
    }
    try {
      await api.post("/api/auth/change-password", { current_password: current, new_password: next });
      setMsg({ tone: "success", text: "Passwort geändert. Andere Sitzungen wurden abgemeldet." });
      setCurrent(""); setNext(""); setRepeat("");
      onDone();
    } catch (err) {
      setMsg({ tone: "error", text: (err as Error).message });
    }
  };

  const form = (
    <form onSubmit={submit} className="form">
      {forced && <Alert tone="info">Bitte vergeben Sie ein eigenes Passwort, bevor Sie fortfahren.</Alert>}
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <label htmlFor="pw-current">Aktuelles Passwort</label>
      <input id="pw-current" type="password" autoComplete="current-password" required
             value={current} onChange={(e) => setCurrent(e.target.value)} />
      <label htmlFor="pw-new">Neues Passwort (mind. 12 Zeichen)</label>
      <input id="pw-new" type="password" autoComplete="new-password" required minLength={12} maxLength={256}
             value={next} onChange={(e) => setNext(e.target.value)} aria-describedby="pw-hint" />
      <p id="pw-hint" className="small muted">Tipp: Eine Passphrase aus mehreren Wörtern ist sicher und gut merkbar.</p>
      <label htmlFor="pw-repeat">Neues Passwort wiederholen</label>
      <input id="pw-repeat" type="password" autoComplete="new-password" required minLength={12}
             value={repeat} onChange={(e) => setRepeat(e.target.value)} />
      <div className="row">
        <button className="btn btn-primary" type="submit">Passwort ändern</button>
        {forced && onLogout && <button type="button" className="btn" onClick={onLogout}>Abmelden</button>}
      </div>
    </form>
  );
  if (forced) {
    return <main className="login" id="main"><div className="card login-card"><h1>Passwort festlegen</h1>{form}</div></main>;
  }
  return <Card title="Passwort ändern">{form}</Card>;
}
