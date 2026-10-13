// Browser-Test der Weboberfläche (Playwright/Chromium), gestartet von ui_browser_e2e.py
// innerhalb des Client-Namespace – der Browser spricht also ECHT durch den WireGuard-Tunnel.
//   node ui_browser_e2e.mjs <basis-url> <benutzer> <passwort> <screenshot-verzeichnis> <arbeitsverzeichnis>
const pwModule = process.env.PLAYWRIGHT_MODULE || "playwright";
const { chromium } = await import(pwModule);
const fs = await import("node:fs");
const [, , base, user, pw, out, work] = process.argv;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const problems = [];
// Erwartbare Browser-Meldungen: 401 beim ersten /api/auth/me (noch nicht angemeldet) und der
// COOP-Hinweis bei HTTP innerhalb des Tunnels (privater Modus ohne TLS).
const BENIGN = [/status of 401/, /Cross-Origin-Opener-Policy header has been ignored/];

async function run(ctxOpts, prefix) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && !BENIGN.some((re) => re.test(m.text()))
    && problems.push(`${prefix} Konsole: ${m.text()}`));
  page.on("pageerror", (e) => problems.push(`${prefix} JS-Fehler: ${e.message}`));
  await page.goto(base);
  await page.fill("#username", user);
  await page.fill("#password", pw);
  await page.click("button[type=submit]");
  await page.waitForSelector("h1");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/${prefix}dashboard.png`, fullPage: true });
  for (const r of ["geraete", "server", "status", "installation", "einstellungen", "admin"]) {
    await page.goto(`${base}#/${r}`);
    await page.waitForTimeout(600);
    if (["geraete", "status"].includes(r)) await page.screenshot({ path: `${out}/${prefix}${r}.png`, fullPage: true });
    // Kein horizontales Scrollen (mobilfreundlich)
    const [sw, vw] = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    if (sw > vw) problems.push(`${prefix}${r}: Seite breiter als Bildschirm (${sw} > ${vw})`);
  }
  await page.goto(`${base}#/geraete`);
  await page.click("text=+ Gerät hinzufügen");
  await page.fill("#dev-name", `Browser ${prefix.replace("-", "")}`);
  await page.click("text=Gerät erstellen");
  await page.waitForSelector("img.qr");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${prefix}geraet-qr.png` });
  await page.click("text=Als Text anzeigen");
  fs.writeFileSync(`${work}/${prefix}browser.conf`, await page.textContent("pre.config"), { mode: 0o600 });
  const qr = await page.getAttribute("img.qr", "src");
  fs.writeFileSync(`${work}/${prefix}qr.png`, Buffer.from(qr.split(",")[1], "base64"));
  await ctx.close();
}

await run({ viewport: { width: 1280, height: 800 } }, "desktop-");
await run({ viewport: { width: 390, height: 844 }, isMobile: true, colorScheme: "dark" }, "mobil-");
await browser.close();
console.log(JSON.stringify({ problems }));
process.exit(problems.length ? 1 : 0);
