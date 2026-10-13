/**
 * WireGuard-Schlüssel und Konfiguration – vollständig im Browser.
 *
 * Der private Schlüssel wird hier erzeugt und verlässt den Browser NIE in
 * Richtung Server. An den Server geht nur der öffentliche Schlüssel.
 * Kryptografie: X25519 aus @noble/curves (auditiert), Zufall aus
 * crypto.getRandomValues (CSPRNG des Betriebssystems). Keine Eigenbau-Krypto.
 */
import { x25519 } from "@noble/curves/ed25519.js";

export interface ConfigTemplate {
  interface: { addresses: string[]; dns: string[]; mtu: number | null };
  peer: {
    public_key: string;
    preshared_key: string | null;
    endpoint: string;
    allowed_ips: string[];
    persistent_keepalive: number | null;
  };
}

export function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export function fromBase64(b64: string): Uint8Array {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

/** Klemmen wie `wg genkey` (RFC 7748), damit Schlüssel identisch formatiert sind. */
export function clamp(key: Uint8Array): Uint8Array {
  const k = new Uint8Array(key);
  k[0] &= 248;
  k[31] &= 127;
  k[31] |= 64;
  return k;
}

export function publicKeyFromPrivate(privateKeyB64: string): string {
  const priv = fromBase64(privateKeyB64);
  if (priv.length !== 32) throw new Error("Ungültiger privater Schlüssel");
  return toBase64(x25519.getPublicKey(priv));
}

export function generateKeyPair(): { privateKey: string; publicKey: string } {
  const raw = new Uint8Array(32);
  crypto.getRandomValues(raw);
  const priv = clamp(raw);
  const privateKey = toBase64(priv);
  raw.fill(0);
  return { privateKey, publicKey: publicKeyFromPrivate(privateKey) };
}

const KEY_RE = /^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$/;
export function isValidKey(k: string): boolean {
  return KEY_RE.test(k);
}

/** Erzeugt eine wg-quick-kompatible Konfiguration (identisch zu render_config im Backend). */
export function renderConfig(t: ConfigTemplate, privateKey: string): string {
  const lines = [
    "[Interface]",
    `PrivateKey = ${privateKey}`,
    `Address = ${t.interface.addresses.join(", ")}`,
  ];
  if (t.interface.dns.length) lines.push(`DNS = ${t.interface.dns.join(", ")}`);
  if (t.interface.mtu) lines.push(`MTU = ${t.interface.mtu}`);
  lines.push("", "[Peer]", `PublicKey = ${t.peer.public_key}`);
  if (t.peer.preshared_key) lines.push(`PresharedKey = ${t.peer.preshared_key}`);
  lines.push(`AllowedIPs = ${t.peer.allowed_ips.join(", ")}`, `Endpoint = ${t.peer.endpoint}`);
  if (t.peer.persistent_keepalive) lines.push(`PersistentKeepalive = ${t.peer.persistent_keepalive}`);
  return lines.join("\n") + "\n";
}

/** Dateiname, den die WireGuard-Apps als Tunnelnamen übernehmen (max. 15 Zeichen, sicher). */
export function configFileName(deviceName: string): string {
  const base = deviceName
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9_=+.-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 10);
  return `dvpn-${base || "geraet"}.conf`;
}
