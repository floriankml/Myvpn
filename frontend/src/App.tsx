import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type User } from "./lib/api";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Servers } from "./pages/Servers";
import { Devices } from "./pages/Devices";
import { Installation } from "./pages/Installation";
import { Settings } from "./pages/Settings";
import { StatusPage } from "./pages/Status";
import { Admin } from "./pages/Admin";
import { ChangePassword } from "./pages/ChangePassword";

const ROUTES = [
  { id: "dashboard", label: "Dashboard" },
  { id: "server", label: "Server" },
  { id: "geraete", label: "Geräte" },
  { id: "installation", label: "Installation" },
  { id: "einstellungen", label: "Einstellungen" },
  { id: "status", label: "Status" },
] as const;

function currentRoute(): string {
  return window.location.hash.replace(/^#\/?/, "") || "dashboard";
}

export function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [route, setRoute] = useState(currentRoute());
  const [menuOpen, setMenuOpen] = useState(false);

  const loadMe = useCallback(() => {
    api.get<User>("/api/auth/me").then(setUser).catch((e) => {
      if (e instanceof ApiError && e.status === 401) setUser(null);
      else setUser(null);
    });
  }, []);

  useEffect(() => {
    loadMe();
    const onHash = () => {
      setRoute(currentRoute());
      setMenuOpen(false);
      document.getElementById("main")?.focus();
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [loadMe]);

  useEffect(() => {
    const label = [...ROUTES, { id: "admin", label: "Benutzerverwaltung" }].find((r) => r.id === route)?.label;
    document.title = label ? `${label} · DeutschlandVPN` : "DeutschlandVPN";
  }, [route]);

  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => undefined);
    setUser(null);
    window.location.hash = "#/dashboard";
  };

  if (user === undefined) return <div className="center muted">Lädt …</div>;
  if (user === null) return <Login onLogin={setUser} />;
  if (user.must_change_password) return <ChangePassword forced onDone={loadMe} onLogout={logout} />;

  const routes = user.is_admin ? [...ROUTES, { id: "admin", label: "Benutzer" }] : ROUTES;
  let page;
  switch (route) {
    case "server": page = <Servers />; break;
    case "geraete": page = <Devices user={user} />; break;
    case "installation": page = <Installation />; break;
    case "einstellungen": page = <Settings user={user} onLogout={logout} />; break;
    case "status": page = <StatusPage user={user} />; break;
    case "admin": page = user.is_admin ? <Admin user={user} /> : <Dashboard />; break;
    default: page = <Dashboard />;
  }

  return (
    <>
      <a className="skip-link" href="#main">Zum Inhalt springen</a>
      <header className="topbar">
        <a className="brand" href="#/dashboard" aria-label="DeutschlandVPN – zum Dashboard">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <path d="M16 4l10 4.5v6.5c0 6.5-4.3 11-10 13-5.7-2-10-6.5-10-13V8.5z" fill="none"
                  stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          </svg>
          <span>DeutschlandVPN</span>
        </a>
        <button type="button" className="btn btn-ghost menu-btn" aria-expanded={menuOpen}
                aria-controls="hauptnavigation" onClick={() => setMenuOpen(!menuOpen)}>
          Menü
        </button>
        <nav id="hauptnavigation" aria-label="Hauptnavigation" className={menuOpen ? "open" : ""}>
          <ul>
            {routes.map((r) => (
              <li key={r.id}>
                <a href={`#/${r.id}`} aria-current={route === r.id ? "page" : undefined}>{r.label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="user-box">
          <span className="muted" title="Angemeldet als">{user.username}</span>
          <button type="button" className="btn btn-ghost" onClick={logout}>Abmelden</button>
        </div>
      </header>
      <main id="main" tabIndex={-1}>{page}</main>
      <footer className="footer muted">
        DeutschlandVPN · privates MVP · WireGuard® ist eine eingetragene Marke von Jason A. Donenfeld.
      </footer>
    </>
  );
}
