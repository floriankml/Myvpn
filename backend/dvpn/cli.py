"""dvpn-admin – Verwaltung über die Kommandozeile auf dem Server.

Für die Ersteinrichtung (erstes Admin-Konto, erstes Gerät), bevor die
Weboberfläche über den VPN-Tunnel erreichbar ist.

Beispiele:
  dvpn-admin create-admin alice
  dvpn-admin create-device alice "Pixel 8" --qr   # zeigt QR-Code im Terminal
  (umask 077; dvpn-admin create-device alice "Laptop" > laptop.conf)   # als Datei
  dvpn-admin list-devices
  dvpn-admin revoke-device 3
  dvpn-admin sync
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys

from sqlalchemy import select

from .agent_client import AgentClient, AgentError
from .config import get_settings
from .db import Database
from .models import Device, Server, User
from .schemas import AdminUserCreateIn, DeviceCreateIn
from .security import PASSWORD_MIN, generate_password, hash_password
from .services import DeviceError, config_template, create_device, ensure_server, render_config, revoke_device, \
    server_public_key, sync_agent


def _wg(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["wg", *args], input=stdin, capture_output=True, text=True, check=True).stdout.strip()


def _ctx():
    s = get_settings()
    db = Database(s.database_url)
    db.create_all()
    session = db.sessionmaker()
    ensure_server(session, s)
    return s, session, AgentClient(s.agent_socket, s.agent_timeout)


def _user(session, name: str) -> User:
    u = session.scalar(select(User).where(User.username == name.lower()))
    if u is None:
        sys.exit(f"Benutzer '{name}' nicht gefunden")
    return u


def cmd_create_user(args: argparse.Namespace, admin: bool) -> None:
    s, session, _ = _ctx()
    name = AdminUserCreateIn(username=args.username, is_admin=admin).username
    if session.scalar(select(User.id).where(User.username == name)):
        sys.exit("Benutzer existiert bereits")
    if args.generate:
        password, must_change = generate_password(), True
    else:
        password = getpass.getpass("Passwort: ")
        if len(password) < PASSWORD_MIN or password != getpass.getpass("Wiederholen: "):
            sys.exit(f"Passwörter stimmen nicht überein oder sind kürzer als {PASSWORD_MIN} Zeichen")
        must_change = False
    session.add(User(username=name, password_hash=hash_password(password), is_admin=admin,
                     must_change_password=must_change))
    session.commit()
    print(f"Benutzer '{name}' angelegt{' (Administrator)' if admin else ''}.")
    if args.generate:
        print(f"Initialpasswort (wird nicht gespeichert, muss bei Erstanmeldung geändert werden): {password}")


def cmd_reset_password(args: argparse.Namespace) -> None:
    _, session, _ = _ctx()
    u = _user(session, args.username)
    password = generate_password()
    u.password_hash, u.must_change_password = hash_password(password), True
    for sess in list(u.sessions):
        session.delete(sess)
    session.commit()
    print(f"Neues Initialpasswort für '{u.username}': {password}")


def _info(msg: str) -> None:
    """Hinweise nach stderr – stdout enthält nur die Konfiguration (umleitbar in eine Datei)."""
    print(msg, file=sys.stderr)


def cmd_create_device(args: argparse.Namespace) -> None:
    s, session, agent = _ctx()
    u = _user(session, args.username)
    # Ausgabedatei ZUERST öffnen: Scheitert das (Rechte), wird kein Gerät angelegt,
    # dessen privater Schlüssel sonst verloren wäre.
    out_fh = None
    if args.output:
        try:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            sys.exit(f"{args.output} existiert bereits – bitte anderen Dateinamen wählen.")
        except OSError as exc:
            sys.exit(f"{args.output} kann nicht geschrieben werden ({exc.strerror}); "
                     f"dvpn-admin läuft als Benutzer 'dvpn'.\n"
                     f"Tipp: Ausgabe umleiten, z. B.: (umask 077; dvpn-admin create-device {args.username} "
                     f"\"{args.name}\" > geraet.conf)")
        out_fh = os.fdopen(fd, "w")
    server_pub = server_public_key(agent)
    if server_pub is None:
        sys.exit("Agent nicht erreichbar – läuft dvpn-agent?")
    # Schlüssel mit dem offiziellen Werkzeug erzeugen; der private Schlüssel
    # bleibt nur im Speicher dieses Prozesses.
    private_key = _wg("genkey")
    public_key = _wg("pubkey", stdin=private_key + "\n")
    body = DeviceCreateIn(name=args.name, public_key=public_key)
    try:
        dev, applied = create_device(session, s, agent, u, body.name, public_key)
    except DeviceError as exc:
        sys.exit(exc.message)
    conf = render_config(config_template(s, session.get(Server, dev.server_id), dev, server_pub), private_key)
    if out_fh is not None:
        with out_fh:
            out_fh.write(conf)
        _info(f"Konfiguration gespeichert: {args.output} (Rechte 0600) – nach dem Import löschen!")
    elif not args.qr or not sys.stdout.isatty():
        sys.stdout.write(conf)
    if args.qr:
        if shutil.which("qrencode"):
            subprocess.run(["qrencode", "-t", "ansiutf8"], input=conf, text=True, check=False,
                           stdout=sys.stderr if not sys.stdout.isatty() else None)
        else:
            _info("(qrencode nicht installiert – kein QR-Code)")
    _info(f"Gerät #{dev.id} '{dev.name}' für {u.username}: {dev.ipv4}"
          f"{' / ' + dev.ipv6 if dev.ipv6 else ''} – {'aktiv' if applied else 'wird beim nächsten Abgleich aktiv'}")
    _info("Hinweis: Der private Schlüssel wurde NICHT gespeichert.")


def cmd_list_devices(_: argparse.Namespace) -> None:
    _, session, _ = _ctx()
    for d in session.scalars(select(Device).order_by(Device.id)):
        state = "widerrufen" if d.revoked_at else "aktiv"
        print(f"#{d.id:<4} {d.user.username:<16} {d.name:<24} {d.ipv4:<15} {state}")


def cmd_revoke_device(args: argparse.Namespace) -> None:
    _, session, agent = _ctx()
    dev = session.get(Device, args.device_id)
    if dev is None:
        sys.exit("Gerät nicht gefunden")
    applied = revoke_device(session, agent, dev)
    print(f"Gerät #{dev.id} widerrufen{'' if applied else ' (Agent nicht erreichbar – Abgleich folgt)'}.")


def cmd_sync(_: argparse.Namespace) -> None:
    s, session, agent = _ctx()
    try:
        print(sync_agent(session, s, agent))
    except AgentError as exc:
        sys.exit(str(exc))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dvpn-admin", description="DeutschlandVPN Verwaltung")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("create-admin", "create-user"):
        sp = sub.add_parser(name)
        sp.add_argument("username")
        sp.add_argument("--generate", action="store_true", help="zufälliges Initialpasswort erzeugen")
    sp = sub.add_parser("reset-password")
    sp.add_argument("username")
    sp = sub.add_parser("create-device")
    sp.add_argument("username")
    sp.add_argument("name")
    sp.add_argument("--qr", action="store_true", help="QR-Code im Terminal anzeigen")
    sp.add_argument("-o", "--output", help="Konfiguration in Datei schreiben (0600)")
    sub.add_parser("list-devices")
    sp = sub.add_parser("revoke-device")
    sp.add_argument("device_id", type=int)
    sub.add_parser("sync")
    args = p.parse_args(argv)
    match args.cmd:
        case "create-admin":
            cmd_create_user(args, admin=True)
        case "create-user":
            cmd_create_user(args, admin=False)
        case "reset-password":
            cmd_reset_password(args)
        case "create-device":
            cmd_create_device(args)
        case "list-devices":
            cmd_list_devices(args)
        case "revoke-device":
            cmd_revoke_device(args)
        case "sync":
            cmd_sync(args)


if __name__ == "__main__":
    main()
