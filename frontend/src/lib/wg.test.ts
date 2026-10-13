import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { clamp, configFileName, fromBase64, generateKeyPair, isValidKey, publicKeyFromPrivate, renderConfig, toBase64 } from "./wg";

function hasWg(): boolean {
  try { execFileSync("wg", ["--version"]); return true; } catch { return false; }
}

describe("WireGuard-Schlüssel", () => {
  it("RFC 7748 Testvektor (X25519 Basispunkt-Multiplikation)", () => {
    // RFC 7748, Abschnitt 6.1 (Alice)
    const priv = Uint8Array.from(Buffer.from("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a", "hex"));
    const pub = Buffer.from(fromBase64(publicKeyFromPrivate(toBase64(priv)))).toString("hex");
    expect(pub).toBe("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a");
  });

  it("erzeugt gültige, geklemmte, zufällige Schlüssel", () => {
    const seen = new Set<string>();
    for (let i = 0; i < 50; i++) {
      const { privateKey, publicKey } = generateKeyPair();
      expect(isValidKey(privateKey)).toBe(true);
      expect(isValidKey(publicKey)).toBe(true);
      const raw = fromBase64(privateKey);
      expect(raw[0] & 7).toBe(0);
      expect(raw[31] & 128).toBe(0);
      expect(raw[31] & 64).toBe(64);
      seen.add(privateKey);
    }
    expect(seen.size).toBe(50);
  });

  it.skipIf(!hasWg())("öffentlicher Schlüssel stimmt mit dem offiziellen `wg pubkey` überein", () => {
    for (let i = 0; i < 10; i++) {
      const { privateKey, publicKey } = generateKeyPair();
      const official = execFileSync("wg", ["pubkey"], { input: privateKey + "\n" }).toString().trim();
      expect(publicKey).toBe(official);
    }
  });

  it.skipIf(!hasWg())("akzeptiert Schlüssel von `wg genkey`", () => {
    const priv = execFileSync("wg", ["genkey"]).toString().trim();
    const official = execFileSync("wg", ["pubkey"], { input: priv + "\n" }).toString().trim();
    expect(publicKeyFromPrivate(priv)).toBe(official);
    expect(toBase64(clamp(fromBase64(priv)))).toBe(priv); // wg genkey klemmt bereits
  });
});

describe("Konfiguration", () => {
  const tpl = {
    interface: { addresses: ["10.8.0.2/32", "fd42:4242:4242::2/128"], dns: ["10.8.0.1", "fd42:4242:4242::1"], mtu: null },
    peer: {
      public_key: "U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1M=",
      preshared_key: "UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFA=",
      endpoint: "vpn.example.de:51820",
      allowed_ips: ["0.0.0.0/0", "::/0"],
      persistent_keepalive: 25,
    },
  };

  it("ist identisch mit der Backend-Ausgabe (render_config)", () => {
    expect(renderConfig(tpl, "PRIV")).toBe(
      "[Interface]\nPrivateKey = PRIV\nAddress = 10.8.0.2/32, fd42:4242:4242::2/128\n" +
      "DNS = 10.8.0.1, fd42:4242:4242::1\n\n[Peer]\n" +
      "PublicKey = U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1M=\n" +
      "PresharedKey = UFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFA=\n" +
      "AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = vpn.example.de:51820\nPersistentKeepalive = 25\n",
    );
  });

  it("erzeugt sichere Dateinamen (≤ 15 Zeichen Tunnelname)", () => {
    expect(configFileName("Pixel 8 (Arbeit)")).toBe("dvpn-Pixel-8-Ar.conf");
    expect(configFileName("../../etc/passwd")).toMatch(/^dvpn-[A-Za-z0-9_=+.-]*\.conf$/);
    expect(configFileName("ÄÖÜ")).toBe("dvpn-AOU.conf");
    expect(configFileName("!!!")).toBe("dvpn-geraet.conf");
    expect(configFileName("x".repeat(40)).replace(".conf", "").length).toBeLessThanOrEqual(15);
  });
});
