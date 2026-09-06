from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from parking import __version__
from parking.api import admin, anpr_review, customer, ops, payment_gateway, sessions, tariffs
from parking.config import database_url
from parking.db import make_session_factory
from parking.domain.errors import ErrorCode, ParkingError
from parking.services.auth import fetch_core_user

API_PREFIX = "/parking/api"


def create_app(database_url_value: str | None = None):
    url = database_url_value or database_url()
    engine, factory = make_session_factory(url)

    app = FastAPI(title="BotConnector Parking API", version=__version__)
    app.state.engine = engine
    app.state.session_factory = factory

    app.include_router(admin.router, prefix=API_PREFIX, tags=["admin"])
    app.include_router(tariffs.router, prefix=API_PREFIX, tags=["tariffs"])
    app.include_router(sessions.router, prefix=API_PREFIX, tags=["sessions"])
    app.include_router(ops.router, prefix=API_PREFIX, tags=["ops"])
    app.include_router(anpr_review.router, prefix=API_PREFIX, tags=["anpr"])
    app.include_router(customer.router, prefix=API_PREFIX, tags=["customer"])
    app.include_router(payment_gateway.router, prefix=API_PREFIX, tags=["payment_gateway"])

    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
    index_file = os.path.join(static_dir, "index.html")

    @app.api_route("/parking", methods=["GET", "HEAD"])
    @app.api_route("/parking/", methods=["GET", "HEAD"])
    async def parking_root(request: Request):
        token = request.cookies.get("bc_session")
        if not token:
            return RedirectResponse(url="/login?next=/parking/", status_code=302)
        user = fetch_core_user(token)
        if not user:
            return RedirectResponse(url="/login?next=/parking/", status_code=302)
        return FileResponse(index_file)

    @app.api_route("/parking/console", methods=["GET", "HEAD"])
    @app.api_route("/parking/console/", methods=["GET", "HEAD"])
    async def parking_console_root(request: Request):
        return FileResponse(index_file)

    if os.path.isdir(static_dir):
        app.mount("/parking/console", StaticFiles(directory=static_dir, html=True), name="console")
        app.mount("/parking/static", StaticFiles(directory=static_dir), name="static")

    @app.get(f"{API_PREFIX}/health")
    def health() -> dict:
        return {"status": "ok", "service": "botconnector-parking", "version": __version__}

    @app.get(f"{API_PREFIX}/liveness")
    def liveness() -> dict:
        return {"status": "alive", "service": "botconnector-parking"}

    @app.get(f"{API_PREFIX}/readiness")
    def readiness() -> dict:
        # Validate DB connectivity + migration state without exposing secrets.
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "database_unavailable"})
        return {"status": "ready", "service": "botconnector-parking"}

    @app.exception_handler(ParkingError)
    async def parking_error_handler(request: Request, exc: ParkingError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.exception_handler(SQLAlchemyError)
    async def sql_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Never leak SQL details to callers.
        return JSONResponse(
            status_code=500,
            content={"error": {"code": ErrorCode.INTERNAL_ERROR, "message": "internal database error"}},
        )

    return app


app = create_app()
