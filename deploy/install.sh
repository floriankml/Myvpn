#!/usr/bin/env bash
# DeutschlandVPN – Installation auf einem frischen Debian-12/13- oder Ubuntu-24.04-VPS.
#
#   sudo ./deploy/install.sh --endpoint vpn.example.de [--location "Nürnberg"] [--provider "…"]
#                            [--ipv6-egress | --no-ipv6] [--ssh-port 22] [--wg-port 51820]
#                            [--domain web.example.de] [--yes]
#
# Das Skript ist idempotent: Erneutes Ausführen aktualisiert Code und Regeln,
# behält aber Schlüssel, Datenbank und bestehende .env-Dateien.
# Es verändert NUR den Rechner, auf dem es ausgeführt wird.
set -euo pipefail
umask 077

die() { echo "FEHLER: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ $EUID -eq 0 ]] || die "Bitte als root ausführen (sudo)."
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR=/opt/dvpn
STATE_DIR=/var/lib/dvpn
CONF_DIR=/etc/dvpn

ENDPOINT="" LOCATION="Deutschland" PROVIDER="" SSH_PORT="" WG_PORT=51820 WEB_PORT=8080
IPV6=auto IPV6_EGRESS=no DOMAIN="" ASSUME_YES=no WAN_IF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint) ENDPOINT="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --ssh-port) SSH_PORT="$2"; shift 2 ;;
    --wg-port) WG_PORT="$2"; shift 2 ;;
    --wan-if) WAN_IF="$2"; shift 2 ;;
    --ipv6) IPV6=yes; shift ;;
    --no-ipv6) IPV6=no; shift ;;
    --ipv6-egress) IPV6=yes; IPV6_EGRESS=yes; shift ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=yes; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
done
[[ -n "$ENDPOINT" ]] || die "--endpoint (öffentlicher DNS-Name oder IPv4 des Servers) fehlt."

# --- Betriebssystem prüfen ---
# shellcheck disable=SC1091
. /etc/os-release
case "${ID}:${VERSION_ID}" in
  debian:12|debian:13|ubuntu:24.04) ;;
  *) die "Nicht unterstütztes System: ${PRETTY_NAME}. Unterstützt: Debian 12/13, Ubuntu 24.04 (Python ≥ 3.11)." ;;
esac

# --- Netzwerk erkennen (nur lokale Routingtabelle, keine externe Abfrage) ---
if [[ -z "$WAN_IF" ]]; then
  WAN_IF="$(ip -4 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
fi
[[ -n "$WAN_IF" ]] || die "WAN-Interface nicht erkannt, bitte --wan-if angeben."
PUBLIC_IPV4="$(ip -4 -o addr show dev "$WAN_IF" scope global | awk '{split($4,a,"/"); print a[1]; exit}')"
PUBLIC_IPV6="$(ip -6 -o addr show dev "$WAN_IF" scope global | awk '{split($4,a,"/"); print a[1]; exit}')"
SERVER_HAS_IPV6=no; [[ -n "$PUBLIC_IPV6" ]] && SERVER_HAS_IPV6=yes
# Standard: IPv6 im Tunnel (ULA) aktivieren und am Server ABLEHNEN, sofern der Kernel IPv6 kann.
# Clients fallen so sofort auf IPv4 zurück; nichts läuft am Tunnel vorbei.
if [[ "$IPV6" == auto ]]; then
  if [[ -d /proc/sys/net/ipv6 ]]; then IPV6=yes; else IPV6=no; fi
fi
if [[ "$IPV6_EGRESS" == yes && "$SERVER_HAS_IPV6" == no ]]; then
  die "--ipv6-egress gewählt, aber $WAN_IF hat keine globale IPv6-Adresse."
fi
if [[ -z "$SSH_PORT" ]]; then
  SSH_PORT="$( (sshd -T 2>/dev/null || true) | awk '/^port /{print $2; exit}')"
  SSH_PORT="${SSH_PORT:-22}"
fi

cat <<INFO

DeutschlandVPN wird mit folgenden Werten installiert:
  WAN-Interface:     $WAN_IF (IPv4: ${PUBLIC_IPV4:-–}, IPv6: ${PUBLIC_IPV6:-–})
  Endpunkt:          $ENDPOINT:$WG_PORT/udp
  SSH-Port:          $SSH_PORT/tcp (bleibt offen – bitte prüfen!)
  IPv6 im Tunnel:    $IPV6 (Ausgang ins Internet: $IPV6_EGRESS)
  Öffentliche Web-UI: ${DOMAIN:-nein (nur über VPN)}

ACHTUNG: Die Firewall verwirft danach allen nicht erlaubten eingehenden Verkehr.
Stellen Sie sicher, dass der SSH-Port korrekt ist, sonst sperren Sie sich aus.
INFO
if [[ "$ASSUME_YES" != yes ]]; then
  read -r -p "Fortfahren? [j/N] " ans
  [[ "$ans" =~ ^[jJyY]$ ]] || die "Abgebrochen."
fi

# --- Pakete ---
info "Pakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
PKGS=(wireguard-tools nftables unbound python3 python3-venv qrencode unattended-upgrades ca-certificates)
[[ -n "$DOMAIN" ]] && PKGS+=(caddy)
apt-get install -y -q "${PKGS[@]}"

# --- Systembenutzer (ohne Login-Shell) ---
info "Systembenutzer anlegen"
getent group dvpn >/dev/null || groupadd --system dvpn
id dvpn >/dev/null 2>&1 || useradd --system --gid dvpn --home-dir "$STATE_DIR" --shell /usr/sbin/nologin dvpn
getent group dvpn-agent >/dev/null || groupadd --system dvpn-agent
id dvpn-agent >/dev/null 2>&1 || useradd --system --gid dvpn-agent --home-dir /var/lib/dvpn-agent --shell /usr/sbin/nologin dvpn-agent

# --- Dauerhafte Installationsparameter (z. B. zufälliges ULA-Präfix) ---
install -d -m 0750 -o root -g dvpn "$CONF_DIR"
if [[ ! -f "$CONF_DIR/install.conf" ]]; then
  ULA="fd$(od -An -N5 -tx1 /dev/urandom | tr -d ' \n' | sed -E 's/^(..)(....)(....)$/\1:\2:\3/')::/64"
  echo "ULA_PREFIX=$ULA" > "$CONF_DIR/install.conf"
fi
# shellcheck disable=SC1091
. "$CONF_DIR/install.conf"
SUBNET_V6=""; [[ "$IPV6" == yes ]] && SUBNET_V6="$ULA_PREFIX"

# --- Server-Schlüssel (einmalig, verlässt den Server nie) ---
install -d -m 0700 /etc/wireguard
if [[ ! -f /etc/wireguard/wg0.key ]]; then
  info "WireGuard-Serverschlüssel erzeugen"
  wg genkey > /etc/wireguard/wg0.key
  chmod 600 /etc/wireguard/wg0.key
fi

# --- Code installieren ---
info "Programmcode nach $INSTALL_DIR kopieren"
[[ -f "$SRC_DIR/frontend/dist/index.html" ]] || die "frontend/dist fehlt. Bitte vorher lokal 'cd frontend && npm ci && npm run build' ausführen."
install -d -m 0755 "$INSTALL_DIR" "$INSTALL_DIR/src"
rm -rf "$INSTALL_DIR/src.new"
install -d -m 0755 "$INSTALL_DIR/src.new"
cp -r "$SRC_DIR/backend" "$SRC_DIR/agent" "$SRC_DIR/deploy" "$INSTALL_DIR/src.new/"
install -d -m 0755 "$INSTALL_DIR/src.new/frontend"
cp -r "$SRC_DIR/frontend/dist" "$INSTALL_DIR/src.new/frontend/"
find "$INSTALL_DIR/src.new" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$INSTALL_DIR/src.new/backend/tests" "$INSTALL_DIR/src.new/agent/tests"
chown -R root:root "$INSTALL_DIR/src.new"
chmod -R u=rwX,go=rX "$INSTALL_DIR/src.new"
rm -rf "$INSTALL_DIR/src.old"; [[ -d "$INSTALL_DIR/src" ]] && mv "$INSTALL_DIR/src" "$INSTALL_DIR/src.old"
mv "$INSTALL_DIR/src.new" "$INSTALL_DIR/src"

info "Python-Umgebung einrichten"
[[ -x "$INSTALL_DIR/venv/bin/python" ]] || python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/src/backend/requirements.lock"
"$INSTALL_DIR/venv/bin/pip" install -q --no-deps "$INSTALL_DIR/src/backend"
chmod -R u=rwX,go=rX "$INSTALL_DIR/venv"
cat > /usr/local/sbin/dvpn-admin <<WRAP
#!/bin/sh
# Führt dvpn-admin als unprivilegierter Benutzer dvpn mit der Backend-Konfiguration aus.
cd $STATE_DIR && exec runuser -u dvpn -- env DVPN_ENV_FILE=$CONF_DIR/dvpn.env $INSTALL_DIR/venv/bin/dvpn-admin "\$@"
WRAP
chmod 0750 /usr/local/sbin/dvpn-admin

# --- Konfiguration rendern ---
info "Konfigurationsdateien erzeugen"
RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT
RARGS=(--out "$RENDER_DIR" --wan-if "$WAN_IF" --endpoint "$ENDPOINT" --wg-port "$WG_PORT"
       --ssh-port "$SSH_PORT" --web-port "$WEB_PORT" --location "$LOCATION" --provider "$PROVIDER"
       --server-private-key "$(cat /etc/wireguard/wg0.key)" --install-dir "$INSTALL_DIR" --state-dir "$STATE_DIR")
[[ -n "$SUBNET_V6" ]] && RARGS+=(--subnet-v6 "$SUBNET_V6")
[[ "$IPV6_EGRESS" == yes ]] && RARGS+=(--ipv6-egress)
[[ "$SERVER_HAS_IPV6" == yes ]] && RARGS+=(--server-has-ipv6)
[[ -n "$PUBLIC_IPV4" ]] && RARGS+=(--public-ipv4 "$PUBLIC_IPV4")
[[ -n "$PUBLIC_IPV6" && "$IPV6_EGRESS" == yes ]] && RARGS+=(--public-ipv6 "$PUBLIC_IPV6")
[[ -n "$DOMAIN" ]] && RARGS+=(--public-web --domain "$DOMAIN")
python3 -I "$INSTALL_DIR/src/deploy/render.py" "${RARGS[@]}" >/dev/null

nft -c -f "$RENDER_DIR/nftables.nft" || die "Firewall-Regeln ungültig – nichts geändert."
install -m 0600 -o root -g root "$RENDER_DIR/wg0.conf" /etc/wireguard/wg0.conf
install -m 0600 -o root -g root "$RENDER_DIR/nftables.nft" "$CONF_DIR/nftables.nft"
install -m 0644 "$RENDER_DIR/unbound-dvpn.conf" /etc/unbound/unbound.conf.d/dvpn.conf
install -m 0644 "$RENDER_DIR/sysctl-dvpn.conf" /etc/sysctl.d/99-dvpn.conf
for unit in dvpn-agent dvpn-backend dvpn-firewall; do
  install -m 0644 "$RENDER_DIR/$unit.service" "/etc/systemd/system/$unit.service"
done
# .env-Dateien nur beim ersten Mal anlegen (manuelle Änderungen bleiben erhalten)
[[ -f "$CONF_DIR/dvpn.env" ]] || install -m 0640 -o root -g dvpn "$RENDER_DIR/dvpn.env" "$CONF_DIR/dvpn.env"
[[ -f "$CONF_DIR/agent.env" ]] || install -m 0640 -o root -g dvpn-agent "$RENDER_DIR/agent.env" "$CONF_DIR/agent.env"
# Rechte bei jedem Lauf erzwingen (z. B. nach Wiederherstellung aus einem Backup)
chown root:dvpn "$CONF_DIR" "$CONF_DIR/dvpn.env" && chmod 0750 "$CONF_DIR" && chmod 0640 "$CONF_DIR/dvpn.env"
chown root:dvpn-agent "$CONF_DIR/agent.env" && chmod 0640 "$CONF_DIR/agent.env"
chown root:root "$CONF_DIR/install.conf" "$CONF_DIR/nftables.nft" && chmod 0600 "$CONF_DIR/install.conf" "$CONF_DIR/nftables.nft"
if [[ -n "$DOMAIN" ]]; then
  install -m 0644 "$RENDER_DIR/Caddyfile" /etc/caddy/Caddyfile
fi
install -d -m 0700 -o dvpn -g dvpn "$STATE_DIR"

# --- Journald: Protokolle höchstens 7 Tage aufbewahren (Datensparsamkeit) ---
install -d -m 0755 /etc/systemd/journald.conf.d
printf '[Journal]\nMaxRetentionSec=7day\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/dvpn.conf
chmod 0644 /etc/systemd/journald.conf.d/dvpn.conf
systemctl restart systemd-journald.service || true

# --- Automatische Sicherheitsupdates ---
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
chmod 0644 /etc/apt/apt.conf.d/20auto-upgrades

# --- Dienste starten ---
info "Dienste aktivieren und starten"
# Einzelne Schlüssel (z. B. IPv6 auf Kerneln ohne IPv6) dürfen fehlen; entscheidend ist das Forwarding.
sysctl -q --system || true
[[ "$(sysctl -n net.ipv4.ip_forward)" == 1 ]] || die "IPv4-Forwarding konnte nicht aktiviert werden."
systemctl daemon-reload
systemctl enable --now dvpn-firewall.service
systemctl reload dvpn-firewall.service
systemctl enable wg-quick@wg0.service
systemctl restart wg-quick@wg0.service
systemctl enable unbound.service
systemctl restart unbound.service
systemctl enable dvpn-agent.service dvpn-backend.service
systemctl restart dvpn-agent.service dvpn-backend.service
[[ -n "$DOMAIN" ]] && systemctl restart caddy.service

sleep 2
for svc in dvpn-firewall wg-quick@wg0 unbound dvpn-agent dvpn-backend; do
  systemctl is-active --quiet "$svc" || die "Dienst $svc läuft nicht: journalctl -u $svc"
done

cat <<DONE

==> Installation abgeschlossen.

Nächste Schritte:
  1. Admin-Konto anlegen:     dvpn-admin create-admin <name>
  2. Erstes Gerät anlegen:    dvpn-admin create-device <name> "Pixel 8" --qr
     (QR-Code mit der WireGuard-App scannen)
  3. Weboberfläche über VPN:  http://$(sed -n 's/^DVPN_WEB_HOST=//p' "$CONF_DIR/dvpn.env"):$WEB_PORT
     oder per SSH-Tunnel:      ssh -L 8080:$(sed -n 's/^DVPN_WEB_HOST=//p' "$CONF_DIR/dvpn.env"):$WEB_PORT root@$ENDPOINT
                               -> http://localhost:8080
  4. Prüfen:                  ./deploy/check.sh
DONE
