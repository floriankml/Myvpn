# Testumgebung für deploy/install.sh: Ubuntu 24.04 mit systemd als PID 1.
# NUR für Tests – produktiv wird direkt auf dem VPS installiert (siehe docs/deployment.md).
ARG BASE=ubuntu:24.04
FROM ${BASE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -q && apt-get install -y -q systemd systemd-sysv wireguard-tools wireguard-go nftables unbound \
    python3 python3-venv qrencode unattended-upgrades ca-certificates iproute2 dnsutils curl procps \
    && systemctl mask getty.target console-getty.service systemd-logind.service
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
