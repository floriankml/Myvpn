#!/usr/bin/env bash
# Installationstest: install.sh (2x), check.sh, dvpn-admin, echter systemd-Neustart,
# WireGuard-Client vom Host, Firewall von außen, uninstall.sh (+ --purge).
#
#   sudo tests/install/run.sh            (Voraussetzungen: docker, wg-quick, wireguard-go, curl, dig, ping)
#
# Umgebungsvariablen:
#   BASE_IMAGE  Basis-Image (Standard ubuntu:24.04)
#   EXTRA_CA    optionale CA-Datei für TLS-inspizierende Proxys (nur Testumgebung)
#
# Hinweise zur Testumgebung (gelten NICHT für den Produktivbetrieb):
#   * Ohne WireGuard-Kernelmodul läuft wg0 im Container mit wireguard-go (Drop-in).
#   * Der wireguard-go-Steuersocket gehört root, daher läuft der Agent hier als root (Drop-in).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME=dvpn-install-test
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"; docker rm -f $NAME >/dev/null 2>&1; wg-quick down "$WORK/dvtest.conf" >/dev/null 2>&1' EXIT
export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1
fail=0; step() { echo; echo "### $*"; }; expect() { if eval "$2"; then echo "  [OK] $1"; else echo "  [FEHLER] $1"; fail=1; fi; }

[[ -f "$ROOT/frontend/dist/index.html" ]] || { echo "Bitte zuerst frontend bauen (npm run build)."; exit 2; }
docker build -q --network host --build-arg BASE="${BASE_IMAGE:-ubuntu:24.04}" -t dvpn-install-test "$(dirname "$0")" >/dev/null || exit 2
docker rm -f $NAME >/dev/null 2>&1
docker run -d --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw --tmpfs /run --tmpfs /run/lock \
  --device /dev/net/tun --name $NAME dvpn-install-test >/dev/null
sleep 4
PIPENV=()
if [[ -n "${EXTRA_CA:-}" ]]; then
  docker cp "$EXTRA_CA" $NAME:/usr/local/share/ca-certificates/extra-test-ca.crt
  docker exec $NAME update-ca-certificates >/dev/null
  PIPENV=(-e PIP_CERT=/etc/ssl/certs/ca-certificates.crt)
fi
tar -C "$(dirname "$ROOT")" --exclude=node_modules --exclude=.git --exclude=__pycache__ --exclude='*.db' \
  -czf "$WORK/repo.tgz" "$(basename "$ROOT")"
docker cp "$WORK/repo.tgz" $NAME:/root/repo.tgz
docker exec $NAME sh -c "cd /root && tar xzf repo.tgz"
[[ "$(basename "$ROOT")" == Myvpn ]] || docker exec $NAME mv "/root/$(basename "$ROOT")" /root/Myvpn
docker exec $NAME sh -c 'mkdir -p /etc/systemd/system/wg-quick@wg0.service.d /etc/systemd/system/dvpn-agent.service.d
printf "[Service]\nEnvironment=WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go\nEnvironment=WG_I_PREFER_BUGGY_USERSPACE_TO_POLISHED_KMOD=1\n" > /etc/systemd/system/wg-quick@wg0.service.d/test-userspace.conf
printf "[Service]\nUser=root\n" > /etc/systemd/system/dvpn-agent.service.d/test-root.conf'

step "install.sh (Erstinstallation und Wiederholung)"
for run in 1 2; do
  expect "install.sh Lauf $run" "docker exec ${PIPENV[*]} $NAME bash -c 'cd /root/Myvpn && ./deploy/install.sh --endpoint 203.0.113.1 --yes' >$WORK/install$run.log 2>&1"
done

step "check.sh"
docker exec $NAME /root/Myvpn/deploy/check.sh > "$WORK/check.log"; sed 's/^/  /' "$WORK/check.log" | grep -E "FEHLER|WARN|Alle"
echo "  (Hinweis: Ohne ausgehendes DNS in der Testumgebung meldet check.sh korrekt einen Unbound-Fehler.)"

step "dvpn-admin"
docker exec $NAME bash -c 'dvpn-admin create-admin chef --generate >/dev/null && (umask 077; dvpn-admin create-device chef "Host-Client" > /root/hc.conf) 2>/dev/null'
expect "Konfiguration erzeugt (Rechte 600)" "[[ \$(docker exec $NAME stat -c %a /root/hc.conf) == 600 ]]"
expect "Peer im Kernel" "[[ \$(docker exec $NAME wg show wg0 peers | wc -l) == 1 ]]"

step "Neustart (systemd)"
docker restart $NAME >/dev/null; sleep 10
expect "System läuft" "[[ \$(docker exec $NAME systemctl is-system-running) == running ]]"
expect "Peer nach Neustart wiederhergestellt" "[[ \$(docker exec $NAME wg show wg0 peers | wc -l) == 1 ]]"

step "WireGuard-Client vom Host (nur VPN-Netz geroutet)"
CIP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $NAME)
docker exec $NAME cat /root/hc.conf > "$WORK/dvtest.conf"
sed -i "s/^Endpoint = .*/Endpoint = $CIP:51820/; s/^AllowedIPs = .*/AllowedIPs = 10.8.0.0\/24/; /^DNS/d; s/^Address = \([^,]*\),.*/Address = \1/" "$WORK/dvtest.conf"
chmod 600 "$WORK/dvtest.conf"
wg-quick up "$WORK/dvtest.conf" >/dev/null 2>&1
expect "Ping 10.8.0.1 durch den Tunnel" "ping -c 2 -W 2 10.8.0.1 >/dev/null"
expect "API durch den Tunnel" "[[ \$(curl -sS --max-time 5 http://10.8.0.1:8080/api/health) == '{\"status\":\"ok\"}' ]]"
expect "API von außen gesperrt" "! curl -sS --max-time 4 http://$CIP:8080/api/health >/dev/null 2>&1"
expect "DNS von außen gesperrt" "! dig +time=2 +tries=1 @$CIP example.com >/dev/null 2>&1"
wg-quick down "$WORK/dvtest.conf" >/dev/null 2>&1

step "uninstall.sh / --purge"
docker exec $NAME bash -c 'cd /root/Myvpn && ./deploy/uninstall.sh' >/dev/null
expect "Firewall-Tabellen entfernt" "[[ -z \$(docker exec $NAME nft list tables) ]]"
expect "Forwarding aus" "[[ \$(docker exec $NAME sysctl -n net.ipv4.ip_forward) == 0 ]]"
docker exec $NAME bash -c 'cd /root/Myvpn && echo LÖSCHEN | ./deploy/uninstall.sh --purge' >/dev/null
expect "Daten und Schlüssel gelöscht" "! docker exec $NAME ls /var/lib/dvpn /etc/dvpn /opt/dvpn /etc/wireguard/wg0.key >/dev/null 2>&1"

echo; [[ $fail -eq 0 ]] && echo "ERGEBNIS: alle Prüfungen bestanden" || echo "ERGEBNIS: Fehler"
exit $fail
