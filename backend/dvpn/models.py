"""Datenmodell – bewusst minimal (Datensparsamkeit).

Gespeichert werden NICHT: Client-Endpunkte (reale IP-Adressen), Verbindungs-
zeitpunkte, übertragene Datenmengen, aufgerufene Ziele, User-Agents.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    devices: Mapped[list[Device]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class AuthSession(Base):
    """Login-Sitzung. Gespeichert wird nur der SHA-256-Hash des Tokens."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    location: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64), default="")
    endpoint_host: Mapped[str] = mapped_column(String(255))
    endpoint_port: Mapped[int] = mapped_column(Integer)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[str] = mapped_column(ForeignKey("servers.id"))
    name: Mapped[str] = mapped_column(String(40))
    public_key: Mapped[str] = mapped_column(String(44))
    # Der PSK ist für den Betrieb nötig (Server muss ihn kennen). Er ist allein
    # wertlos, erhöht aber in Kombination die Sicherheit (Post-Quanten-Schicht).
    preshared_key: Mapped[str | None] = mapped_column(String(44), nullable=True)
    ipv4: Mapped[str] = mapped_column(String(45))
    ipv6: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="devices")

    __table_args__ = (
        # Eindeutigkeit nur unter aktiven Geräten (widerrufene Adressen werden frei).
        Index("uq_active_pubkey", "public_key", unique=True,
              sqlite_where=revoked_at.is_(None), postgresql_where=revoked_at.is_(None)),
        Index("uq_active_ipv4", "server_id", "ipv4", unique=True,
              sqlite_where=revoked_at.is_(None), postgresql_where=revoked_at.is_(None)),
    )

    @property
    def active(self) -> bool:
        return self.revoked_at is None
