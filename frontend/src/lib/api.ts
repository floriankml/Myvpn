/** Schlanker API-Client. Cookies sind HttpOnly + SameSite=Strict. */

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* keine JSON-Antwort */
  }
  if (!res.ok) {
    const d = data as { detail?: string; errors?: { field: string; message: string }[] } | null;
    const detail = d?.errors?.length ? d.errors.map((e) => e.message).join(" ") : d?.detail;
    throw new ApiError(res.status, detail || `Fehler ${res.status}`);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b: unknown) => request<T>("PATCH", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
};

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
}

export interface Device {
  id: number;
  name: string;
  public_key: string;
  ipv4: string;
  ipv6: string | null;
  server_id: string;
  created_at: string;
  revoked_at: string | null;
  owner: string | null;
  connected: boolean | null;
  latest_handshake: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
}

export interface Server {
  id: string;
  name: string;
  location: string;
  provider: string;
  endpoint: string;
  public_ipv4: string | null;
  public_ipv6: string | null;
  ipv6_egress: boolean;
  online: boolean;
}

export interface Status {
  agent: boolean;
  interface_up: boolean;
  listen_port: number | null;
  server_public_key: string | null;
  peers_configured: number | null;
  peers_active: number | null;
  ipv6_tunnel: boolean;
  ipv6_egress: boolean;
  dns_servers: string[];
  subnet_v4: string;
  subnet_v6: string | null;
  server_time: number;
}

export interface Connection {
  via_vpn: boolean;
  client_ip: string | null;
  device: { id: number; name: string; ipv4: string; ipv6: string | null } | null;
}
