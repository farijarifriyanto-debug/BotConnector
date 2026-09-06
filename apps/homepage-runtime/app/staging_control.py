from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response


DEFAULT_STATE = {"document": False}


def _admin_emails(settings: Any) -> set[str]:
    return {
        value.strip().lower()
        for value in str(settings.platform_admin_emails or "").split(",")
        if value.strip()
    }


def is_platform_admin(request: Request, settings: Any, current_user: Callable) -> bool:
    user = current_user(request)
    if not isinstance(user, dict):
        return False
    return str(user.get("email", "")).strip().lower() in _admin_emails(settings)


def _state_path(settings: Any) -> Path:
    return Path(settings.staging_control_file)


def load_state(settings: Any) -> dict[str, bool]:
    path = _state_path(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return dict(DEFAULT_STATE)
    result = dict(DEFAULT_STATE)
    if isinstance(raw, dict):
        for slug in result:
            if slug in raw:
                result[slug] = bool(raw[slug])
    return result


def save_state(settings: Any, state: dict[str, bool]) -> None:
    path = _state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _csrf_token(request: Request) -> str:
    value = request.session.get("staging_admin_csrf")
    if not isinstance(value, str) or not value:
        value = secrets.token_urlsafe(32)
        request.session["staging_admin_csrf"] = value
    return value


def register_staging_control(
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable,
    base_context: Callable,
) -> None:
    @app.get("/admin/staging", response_class=HTMLResponse)
    def staging_admin(request: Request):
        if not current_user(request):
            return RedirectResponse("/login", status_code=303)
        if not is_platform_admin(request, settings, current_user):
            raise HTTPException(status_code=403, detail="Akses admin diperlukan.")
        context = base_context(request)
        context.update({
            "staging_state": load_state(settings),
            "staging_csrf": _csrf_token(request),
        })
        return templates.TemplateResponse(
            request=request,
            name="admin_staging.html",
            context=context,
        )

    @app.post("/admin/staging/document")
    async def staging_admin_document(request: Request):
        if not is_platform_admin(request, settings, current_user):
            raise HTTPException(status_code=403, detail="Akses admin diperlukan.")
        form = await request.form()
        supplied = str(form.get("csrf_token", ""))
        expected = str(request.session.get("staging_admin_csrf", ""))
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail="Token keamanan tidak valid.")
        action = str(form.get("action", "closed"))
        if action not in {"open", "closed"}:
            raise HTTPException(status_code=422, detail="Status staging tidak valid.")
        state = load_state(settings)
        state["document"] = action == "open"
        save_state(settings, state)
        return RedirectResponse("/admin/staging", status_code=303)

    @app.get("/api/staging/access/{slug}", include_in_schema=False)
    def staging_access(slug: str, request: Request):
        if slug not in DEFAULT_STATE:
            return Response(status_code=404)
        if load_state(settings).get(slug, False):
            return Response(status_code=204)
        if is_platform_admin(request, settings, current_user):
            return Response(status_code=204)
        if not current_user(request):
            return Response(status_code=401)
        return Response(status_code=403)

    @app.get("/staging-closed", response_class=HTMLResponse)
    def staging_closed(request: Request):
        context = base_context(request)
        return templates.TemplateResponse(
            request=request,
            name="staging_closed.html",
            context=context,
            status_code=200,
        )
