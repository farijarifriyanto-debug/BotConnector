"""FastAPI dependencies: DB session + server-derived authorization scope."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, Request

from parking.domain.errors import ErrorCode, ParkingError
from parking.services.auth import Scope, resolve_core_operator, resolve_operator, scope_from_operator


def get_session_factory(request: Request):
    return request.app.state.session_factory


def get_db(request: Request) -> Iterator:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_scope(request: Request, authorization: str | None = Header(default=None)) -> Scope:
    token = ""
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-API-Key", "").strip()

    factory = request.app.state.session_factory
    with factory() as session:
        if token:
            operator = resolve_operator(session, token)
            return scope_from_operator(operator)

        # Fallback to customer bc_session cookie
        bc_session = request.cookies.get("bc_session")
        if bc_session:
            operator = resolve_core_operator(session, bc_session)
            if operator:
                return scope_from_operator(operator)

        raise ParkingError(ErrorCode.UNAUTHORIZED, "missing authorization credentials or valid session", status=401)
