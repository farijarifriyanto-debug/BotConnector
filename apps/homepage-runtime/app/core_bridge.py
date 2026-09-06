from __future__ import annotations

from http.cookies import SimpleCookie
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response


CANDIDATE_TO_CORE: dict[str, str] = {
    "webhook": "webhook-connector",
    "connect": "webhook-connector",
    "business_suite": "business-suite",
    "business-suite": "business-suite",
    "parking": "parking",
    "langkah": "langkah",
    "business": "business-automation",
    "personal": "personal-automation",
    "monitor": "monitor-resolve",
}
CORE_TO_CANDIDATE: dict[str, str] = {
    "webhook-connector": "connect",
    "business-suite": "business_suite",
    "parking": "parking",
    "langkah": "langkah",
    "business-automation": "business",
    "personal-automation": "personal",
    "monitor-resolve": "monitor",
}


class CoreAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def core_slug(candidate_slug: str) -> str:
    try:
        return CANDIDATE_TO_CORE[candidate_slug]
    except KeyError as exc:
        raise CoreAPIError(404, "Produk belum terhubung ke Core API.") from exc


def candidate_slug(core_product_slug: str) -> str | None:
    return CORE_TO_CANDIDATE.get(core_product_slug)


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "Layanan akun mengembalikan respons yang tidak valid."

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                message = item.get("msg")
                if isinstance(message, str):
                    messages.append(message.replace("Value error, ", ""))
        if messages:
            return " ".join(messages)
    message = payload.get("message") if isinstance(payload, dict) else None
    if isinstance(message, str):
        return message
    return "Permintaan ke layanan akun tidak berhasil."


def api_request(
    request: Request,
    settings: Any,
    method: str,
    path: str,
    *,
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    csrf: bool = False,
    session_token: str | None = None,
) -> httpx.Response:
    headers = {
        "Accept": "application/json",
        "User-Agent": request.headers.get("user-agent", "BotConnector Candidate"),
        "X-Forwarded-For": request.headers.get(
            "x-forwarded-for",
            request.client.host if request.client else "127.0.0.1",
        ),
    }
    if json_data is not None:
        headers["Content-Type"] = "application/json"

    if csrf:
        token = request.session.get("core_csrf_token")
        if not isinstance(token, str) or not token:
            raise CoreAPIError(401, "Sesi keamanan tidak tersedia. Silakan masuk ulang.")
        headers["X-CSRF-Token"] = token

    cookie_token = session_token or request.cookies.get(settings.core_cookie_name)
    cookies = (
        {settings.core_cookie_name: cookie_token}
        if cookie_token
        else None
    )

    try:
        response = httpx.request(
            method=method,
            url=f"{settings.core_api_url.rstrip('/')}/{path.lstrip('/')}",
            headers=headers,
            cookies=cookies,
            json=json_data,
            params=params,
            timeout=httpx.Timeout(settings.core_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )
    except httpx.RequestError as exc:
        raise CoreAPIError(
            502,
            "Layanan akun BotConnector sedang tidak dapat dihubungi.",
        ) from exc

    if response.status_code >= 400:
        raise CoreAPIError(response.status_code, _detail(response))
    return response


def response_session_token(response: httpx.Response, cookie_name: str) -> str | None:
    token = response.cookies.get(cookie_name)
    if token:
        return token
    for header in response.headers.get_list("set-cookie"):
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            continue
        morsel = parsed.get(cookie_name)
        if morsel and morsel.value:
            return morsel.value
    return None


def set_browser_session(response: Response, settings: Any, token: str) -> None:
    response.set_cookie(
        key=settings.core_cookie_name,
        value=token,
        max_age=settings.core_session_ttl_seconds,
        httponly=True,
        secure=settings.core_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_browser_session(response: Response, settings: Any) -> None:
    response.delete_cookie(
        key=settings.core_cookie_name,
        httponly=True,
        secure=settings.core_cookie_secure,
        samesite="lax",
        path="/",
    )


def current_user(request: Request, settings: Any) -> dict[str, Any] | None:
    cached = getattr(request.state, "core_user", None)
    if cached is not None:
        return cached or None
    if not request.cookies.get(settings.core_cookie_name):
        request.state.core_user = {}
        return None
    try:
        response = api_request(request, settings, "GET", "/v1/me")
    except CoreAPIError as exc:
        if exc.status_code in {401, 403}:
            request.session.pop("core_csrf_token", None)
            request.state.core_user = {}
            return None
        request.state.core_error = exc.detail
        request.state.core_user = {}
        return None
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    if isinstance(csrf_token, str) and csrf_token:
        request.session["core_csrf_token"] = csrf_token
    raw = payload.get("user", {})
    user = {
        "id": str(raw.get("id", "")),
        "email": str(raw.get("email", "")),
        "name": str(raw.get("display_name") or raw.get("email", "Pengguna")),
        "status": str(raw.get("status", "active")),
        "locale": str(raw.get("locale", "id-ID")),
        "timezone": str(raw.get("timezone", "Asia/Jakarta")),
    }
    request.state.core_user = user
    return user


def active_candidate_products(request: Request, settings: Any) -> list[str]:
    cached = getattr(request.state, "core_products", None)
    if isinstance(cached, list):
        return cached
    if not current_user(request, settings):
        request.state.core_products = []
        return []
    try:
        response = api_request(request, settings, "GET", "/v1/me/products")
    except CoreAPIError as exc:
        request.state.core_error = exc.detail
        request.state.core_products = []
        return []
    result: list[str] = []
    for item in response.json():
        if item.get("product_status") != "active":
            continue
        if item.get("access_status") not in {"active", "trial"}:
            continue
        mapped = candidate_slug(str(item.get("slug", "")))
        if mapped:
            result.append(mapped)
    request.state.core_products = result
    return result


def invalidate_request_cache(request: Request) -> None:
    for name in ("core_user", "core_products"):
        if hasattr(request.state, name):
            delattr(request.state, name)


def get_onboarding(request: Request, settings: Any, candidate_product: str) -> dict[str, Any] | None:
    try:
        response = api_request(
            request,
            settings,
            "GET",
            f"/v1/onboarding/{core_slug(candidate_product)}",
        )
    except CoreAPIError as exc:
        if exc.status_code in {403, 404}:
            return None
        raise
    return response.json()


def activate_product(request: Request, settings: Any, candidate_product: str) -> dict[str, Any]:
    response = api_request(
        request,
        settings,
        "POST",
        f"/v1/me/products/{core_slug(candidate_product)}/activate",
        csrf=True,
    )
    invalidate_request_cache(request)
    return response.json()


def update_onboarding(
    request: Request,
    settings: Any,
    candidate_product: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = api_request(
        request,
        settings,
        "PUT",
        f"/v1/onboarding/{core_slug(candidate_product)}",
        json_data=payload,
        csrf=True,
    )
    return response.json()


def list_projects(request: Request, settings: Any, candidate_product: str) -> list[dict[str, Any]]:
    response = api_request(
        request,
        settings,
        "GET",
        "/v1/projects",
        params={"product_slug": core_slug(candidate_product)},
    )
    return response.json()


def get_project(request: Request, settings: Any, project_id: str) -> dict[str, Any]:
    response = api_request(
        request,
        settings,
        "GET",
        f"/v1/projects/{project_id}",
    )
    return response.json()


def create_project(
    request: Request,
    settings: Any,
    candidate_product: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = dict(payload)
    body["product_slug"] = core_slug(candidate_product)
    response = api_request(
        request,
        settings,
        "POST",
        "/v1/projects",
        json_data=body,
        csrf=True,
    )
    return response.json()


def update_project(
    request: Request,
    settings: Any,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = api_request(
        request,
        settings,
        "PATCH",
        f"/v1/projects/{project_id}",
        json_data=payload,
        csrf=True,
    )
    return response.json()
