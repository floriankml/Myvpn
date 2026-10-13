"""FastAPI-Anwendung (App-Factory)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .agent_client import AgentClient, AgentError
from .config import Settings, get_settings
from .db import Database
from .deps import client_ip
from .ratelimit import RateLimiter
from .routers import admin, auth, devices, info
from .services import ensure_server, housekeeping, sync_agent

log = logging.getLogger("dvpn")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def reconcile_once(app: FastAPI) -> None:
    s: Settings = app.state.settings
    with app.state.db.sessionmaker() as db:
        housekeeping(db, s)
        try:
            stats = sync_agent(db, s, app.state.agent)
            if any(stats.get(k) for k in ("added", "updated", "removed")):
                log.info("Abgleich mit WireGuard: %s", {k: stats[k] for k in ("added", "updated", "removed")})
        except AgentError as exc:
            log.warning("Abgleich fehlgeschlagen: %s", exc)


async def _reconcile_loop(app: FastAPI, interval: int) -> None:
    while True:
        try:
            await asyncio.to_thread(reconcile_once, app)
        except Exception:  # noqa: BLE001
            log.exception("Fehler im Abgleich")
        await asyncio.sleep(interval)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    db = Database(s.database_url)
    db.create_all()
    with db.sessionmaker() as session:
        ensure_server(session, s)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        if s.reconcile_interval > 0:
            task = asyncio.create_task(_reconcile_loop(app, s.reconcile_interval))
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="DeutschlandVPN",
        lifespan=lifespan,
        docs_url="/api/docs" if s.enable_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if s.enable_docs else None,
    )
    app.state.settings = s
    app.state.db = db
    app.state.agent = AgentClient(s.agent_socket, s.agent_timeout)
    app.state.limits = {
        "global": RateLimiter(300, 60),            # pro IP: 300 API-Anfragen/Minute
        "login_ip": RateLimiter(10, 300),          # pro IP: 10 Logins/5 Min.
        "login_user": RateLimiter(10, 900),        # pro Konto: 10 Fehlversuche/15 Min.
        "device_create": RateLimiter(10, 3600),    # pro Konto: 10 neue Geräte/Stunde
    }

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/"):
            if not app.state.limits["global"].hit(client_ip(request)):
                return JSONResponse({"detail": "Zu viele Anfragen"}, status_code=429)
            if request.method in UNSAFE_METHODS:
                # CSRF-Schutz zusätzlich zu SameSite=Strict:
                # 1) Origin muss zum Host passen (oder explizit erlaubt sein)
                origin = request.headers.get("origin")
                if origin is not None:
                    host = request.headers.get("host", "")
                    if urlsplit(origin).netloc != host and origin.rstrip("/") not in s.origins:
                        return JSONResponse({"detail": "Ungültige Herkunft"}, status_code=403)
                if request.headers.get("sec-fetch-site") == "cross-site":
                    return JSONResponse({"detail": "Ungültige Herkunft"}, status_code=403)
                # 2) Nur JSON-Bodies (Formular-POSTs von Fremdseiten unmöglich)
                ctype = request.headers.get("content-type", "")
                has_body = request.headers.get("content-length", "0") not in ("", "0")
                if has_body and not ctype.startswith("application/json"):
                    return JSONResponse({"detail": "Nur application/json erlaubt"}, status_code=415)
        response: Response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Nur Feldnamen + Meldung zurückgeben, keine Eingabewerte (könnten Passwörter sein)
        errors = [{"field": ".".join(str(x) for x in e.get("loc", [])[1:]),
                   "message": str(e.get("msg", "")).removeprefix("Value error, ")} for e in exc.errors()]
        return JSONResponse({"detail": "Ungültige Eingabe", "errors": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unbehandelter Fehler")
        return JSONResponse({"detail": "Interner Fehler"}, status_code=500)

    for r in (auth.router, devices.router, admin.router, info.router):
        app.include_router(r)

    static = s.static_path
    if static is not None and (static / "index.html").is_file():
        root = static.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)
            candidate = (root / full_path).resolve()
            # Schutz vor Path-Traversal: nur Dateien unterhalb von root
            if full_path and candidate.is_file() and candidate.is_relative_to(root):
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} \
                    if full_path.startswith("assets/") else {"Cache-Control": "no-cache"}
                return FileResponse(candidate, headers=headers)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def app_from_env() -> FastAPI:
    """Für uvicorn: `uvicorn --factory dvpn.main:app_from_env`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return create_app()


__all__ = ["create_app", "app_from_env", "reconcile_once"]
