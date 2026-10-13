"""Konfiguration ausschließlich über Umgebungsvariablen (Präfix DVPN_).

Es gibt bewusst KEINE Standardwerte für Geheimnisse; Geheimnisse liegen nicht
im Quellcode. Produktiv wird /etc/dvpn/dvpn.env (Rechte 0640) per systemd
EnvironmentFile geladen.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DVPN_", env_file=None, extra="ignore")

    # --- Datenbank ---
    database_url: str = "sqlite:///./dvpn.db"

    # --- Agent ---
    agent_socket: str = "/run/dvpn-agent/agent.sock"
    agent_timeout: float = 5.0

    # --- Server (MVP: genau ein Server) ---
    server_id: str = "de-1"
    server_name: str = "Deutschland 1"
    server_location: str = "Deutschland"
    server_provider: str = ""
    endpoint_host: str = Field(default="vpn.example.invalid", description="Öffentlicher DNS-Name oder IP")
    endpoint_port: int = Field(default=51820, ge=1, le=65535)
    public_ipv4: str = ""
    public_ipv6: str = ""

    # --- VPN-Netz ---
    subnet_v4: str = "10.8.0.0/24"
    subnet_v6: str = ""  # z. B. fd12:3456:789a::/64 (ULA); leer = kein IPv6 im Tunnel
    ipv6_egress: bool = False  # True: IPv6-Verkehr wird per NAT66 ins Internet geleitet
    client_dns: str = ""  # leer = Server-Adresse(n) im Tunnel (eigener Unbound)
    client_mtu: int | None = Field(default=None, ge=1280, le=1500)
    persistent_keepalive: int = Field(default=25, ge=0, le=600)

    # --- Web/Sicherheit ---
    cookie_secure: bool = True
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 30)
    allowed_origins: str = ""  # zusätzliche erlaubte Origins, kommagetrennt
    admin_allowed_nets: str = ""  # leer = localhost + VPN-Netze
    max_devices_per_user: int = Field(default=5, ge=1, le=250)
    revoked_retention_days: int = Field(default=30, ge=0, le=3650)
    reconcile_interval: int = Field(default=60, ge=0)  # 0 = aus (Tests)
    static_dir: str = ""  # Pfad zu frontend/dist; leer = keine Auslieferung
    enable_docs: bool = False

    @field_validator("subnet_v4")
    @classmethod
    def _v4(cls, v: str) -> str:
        net = ipaddress.ip_network(v, strict=True)
        if net.version != 4 or not net.is_private or net.prefixlen > 29:
            raise ValueError("subnet_v4 muss ein privates IPv4-Netz (≤ /29) sein")
        return v

    @field_validator("subnet_v6")
    @classmethod
    def _v6(cls, v: str) -> str:
        if not v:
            return v
        net = ipaddress.ip_network(v, strict=True)
        if net.version != 6 or net.prefixlen > 120:
            raise ValueError("subnet_v6 muss ein IPv6-Netz (≤ /120) sein")
        return v

    @model_validator(mode="after")
    def _ipv6_consistent(self) -> "Settings":
        if self.ipv6_egress and not self.subnet_v6:
            raise ValueError("ipv6_egress erfordert subnet_v6")
        return self

    # ---------- abgeleitete Werte ----------
    @property
    def net_v4(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(self.subnet_v4)

    @property
    def net_v6(self) -> ipaddress.IPv6Network | None:
        return ipaddress.IPv6Network(self.subnet_v6) if self.subnet_v6 else None

    @property
    def server_v4(self) -> ipaddress.IPv4Address:
        return self.net_v4.network_address + 1

    @property
    def server_v6(self) -> ipaddress.IPv6Address | None:
        return self.net_v6.network_address + 1 if self.net_v6 else None

    @property
    def dns_servers(self) -> list[str]:
        if self.client_dns:
            return [str(ipaddress.ip_address(x.strip())) for x in self.client_dns.split(",") if x.strip()]
        out = [str(self.server_v4)]
        if self.server_v6:
            out.append(str(self.server_v6))
        return out

    @property
    def admin_nets(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        if self.admin_allowed_nets:
            return [ipaddress.ip_network(x.strip()) for x in self.admin_allowed_nets.split(",") if x.strip()]
        nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("::1/128"),
            self.net_v4,
        ]
        if self.net_v6:
            nets.append(self.net_v6)
        return nets

    @property
    def origins(self) -> set[str]:
        return {o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()}

    @property
    def static_path(self) -> Path | None:
        return Path(self.static_dir) if self.static_dir else None


@lru_cache
def get_settings() -> Settings:
    # DVPN_ENV_FILE: optionale .env-Datei (z. B. für dvpn-admin); Umgebungsvariablen haben Vorrang.
    env_file = os.environ.get("DVPN_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()  # type: ignore[call-arg]
