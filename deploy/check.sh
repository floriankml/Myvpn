#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok() schlägt nie fehl
# DeutschlandVPN – Selbsttest auf dem Server (nur lesend).
#   sudo ./deploy/check.sh
set -uo pipefail
fail=0
ok()   { printf '  [OK]    %s\n' "$*"; }
bad()  { printf '  [FEHLER] %s\n' "$*"; fail=1; }
warn() { printf '  [WARN]  %s\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen."; exit 2; }
envval() { sed -n "s/^$1=//p" /etc/dvpn/dvpn.env 2>/dev/null | head -n1; }
SERVER_V4="$(envval DVPN_WEB_HOST)"; SERVER_V4="${SERVER_V4:-10.8.0.1}"
WEB_PORT="$(envval DVPN_WEB_PORT)"; WEB_PORT="${WEB_PORT:-8080}"

echo "Dienste:"
for svc in dvpn-firewall wg-quick@wg0 unbound dvpn-agent dvpn-backend; do
  systemctl is-active --quiet "$svc" && ok "$svc aktiv" || bad "$svc nicht aktiv"
  systemctl is-enabled --quiet "$svc" 2>/dev/null && ok "$svc startet beim Booten" || bad "$svc nicht aktiviert (Reboot!)"
done

echo "Routing:"
[[ "$(sysctl -n net.ipv4.ip_forward)" == 1 ]] && ok "IPv4-Forwarding an" || bad "IPv4-Forwarding aus"

echo "Firewall:"
nft list table inet dvpn >/dev/null 2>&1 && ok "Tabelle inet dvpn geladen" || bad "Firewall-Tabelle fehlt"
# Ausgaben erst einlesen: "grep -q" in einer Pipe mit pipefail kann sonst durch SIGPIPE fehlschlagen.
in_chain="$(nft list chain inet dvpn input 2>/dev/null)"
fw_chain="$(nft list chain inet dvpn forward 2>/dev/null)"
nat_table="$(nft list table ip dvpn_nat 2>/dev/null)"
[[ "$in_chain" == *"policy drop"* ]] && ok "Eingehend: Standard verwerfen" || bad "input-Policy nicht drop"
[[ "$fw_chain" == *"policy drop"* ]] && ok "Weiterleitung: Standard verwerfen" || bad "forward-Policy nicht drop"
[[ "$fw_chain" == *'iifname "wg0" oifname "wg0" drop'* ]] && ok "Client-Isolation aktiv" || bad "Client-Isolation fehlt"
[[ "$nat_table" == *masquerade* ]] && ok "NAT (masquerade) aktiv" || bad "NAT fehlt"

echo "WireGuard:"
if wg show wg0 >/dev/null 2>&1; then
  ok "wg0 aktiv, Port $(wg show wg0 listen-port), Peers: $(wg show wg0 peers | wc -l)"
else
  bad "wg0 fehlt"
fi
[[ "$(stat -c %a /etc/wireguard/wg0.conf 2>/dev/null)" == 600 ]] && ok "wg0.conf Rechte 600" || bad "wg0.conf Rechte falsch"

echo "DNS:"
if command -v dig >/dev/null; then
  # Nur eine echte Antwort (NOERROR + Adresse) zählt – SERVFAIL heißt: keine Rekursion möglich.
  dns_out="$(dig +time=3 +tries=2 @"$SERVER_V4" example.com A 2>&1)"
  if [[ "$dns_out" == *"status: NOERROR"* ]] && grep -qE '^example\.com\.\s+[0-9]+\s+IN\s+A\s' <<<"$dns_out"; then
    ok "Unbound löst Namen auf ($SERVER_V4)"
    # Nur aussagekräftig, wenn normale Auflösung funktioniert (sonst wäre SERVFAIL ein Scheinerfolg)
    dnssec_out="$(dig +time=3 +tries=2 @"$SERVER_V4" dnssec-failed.org A 2>&1)"
    [[ "$dnssec_out" == *"status: SERVFAIL"* ]] && ok "DNSSEC-Validierung aktiv (dnssec-failed.org wird abgelehnt)" \
      || bad "DNSSEC-Validierung inaktiv (gefälschte Signatur wird akzeptiert)"
  else
    bad "Unbound liefert keine gültige Antwort ($(grep -o 'status: [A-Z]*' <<<"$dns_out" || echo 'keine Antwort'))"
  fi
else
  warn "dig nicht installiert (apt install dnsutils) – DNS-Test übersprungen"
fi

echo "Backend:"
curl -fsS --max-time 3 "http://$SERVER_V4:$WEB_PORT/api/health" >/dev/null && ok "API erreichbar (nur Tunnel-Adresse)" || bad "API nicht erreichbar"
# Nur die Spalte "lokale Adresse" (4) betrachten
listen_addrs="$(ss -ltnH "( sport = :$WEB_PORT )" | awk '{print $4}')"
if [[ -z "$listen_addrs" ]] || grep -qE '^(0\.0\.0\.0|\[::\]|\*):' <<<"$listen_addrs"; then
  bad "Backend lauscht nicht oder auf allen Adressen"
else
  ok "Backend lauscht nicht öffentlich"
fi

echo "Datenschutz:"
[[ "$(stat -c %a /var/lib/dvpn 2>/dev/null)" == 700 ]] && ok "Datenverzeichnis 700" || bad "Rechte /var/lib/dvpn"
grep -qE '^\s*log-queries:\s*no' /etc/unbound/unbound.conf.d/dvpn.conf && ok "DNS-Anfragen werden nicht protokolliert" || bad "Unbound-Logging prüfen"

echo
[[ $fail -eq 0 ]] && echo "Alle Prüfungen bestanden." || echo "Es gibt Fehler (siehe oben)."
exit $fail
