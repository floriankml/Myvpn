#!/usr/bin/env bash
# DeutschlandVPN – sicheres Abschalten.
#
#   sudo ./deploy/uninstall.sh            # Dienst stoppen, alle Peers entfernen, Daten behalten
#   sudo ./deploy/uninstall.sh --purge    # zusätzlich Schlüssel, Datenbank und Programme löschen
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen."; exit 1; }
PURGE=no; [[ "${1:-}" == "--purge" ]] && PURGE=yes

echo "==> Dienste stoppen (alle VPN-Verbindungen werden sofort getrennt)"
systemctl disable --now dvpn-backend.service dvpn-agent.service 2>/dev/null || true
systemctl disable --now wg-quick@wg0.service 2>/dev/null || true
ip link del wg0 2>/dev/null || true
systemctl disable --now dvpn-firewall.service 2>/dev/null || true   # entfernt NAT- und Filterregeln
rm -f /etc/sysctl.d/99-dvpn.conf /etc/unbound/unbound.conf.d/dvpn.conf
sysctl -qw net.ipv4.ip_forward=0
systemctl restart unbound.service 2>/dev/null || true

if [[ "$PURGE" == yes ]]; then
  read -r -p "Wirklich ALLE Schlüssel, Konten und Gerätedaten unwiderruflich löschen? Tippen Sie LÖSCHEN: " a
  [[ "$a" == "LÖSCHEN" ]] || { echo "Abgebrochen (Dienste sind bereits gestoppt)."; exit 1; }
  # shred ist auf Journaling-Dateisystemen/SSDs nur eingeschränkt wirksam – die
  # Dateien sind aber danach nicht mehr über das Dateisystem erreichbar.
  shred -u /etc/wireguard/wg0.key /etc/wireguard/wg0.conf 2>/dev/null || rm -f /etc/wireguard/wg0.key /etc/wireguard/wg0.conf
  find /var/lib/dvpn /var/lib/dvpn-agent -type f -exec shred -u {} + 2>/dev/null || true
  rm -rf /var/lib/dvpn /var/lib/dvpn-agent /etc/dvpn /opt/dvpn /usr/local/sbin/dvpn-admin
  rm -f /etc/systemd/system/dvpn-*.service
  systemctl daemon-reload
  userdel dvpn 2>/dev/null || true
  userdel dvpn-agent 2>/dev/null || true
  echo "==> Alle Daten gelöscht. Beim Anbieter abschließend den VPS samt Snapshots/Backups löschen."
else
  echo "==> Gestoppt. Daten unter /var/lib/dvpn und Schlüssel unter /etc/wireguard bleiben erhalten."
fi
