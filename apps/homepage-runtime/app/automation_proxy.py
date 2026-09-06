import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from typing import Any, Callable, Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError


PROXY_VERSION = "0.1.0"
BRAIN_URL = os.getenv(
    "AUTOMATION_BRAIN_URL",
    "http://botconnector-automation-brain-shadow:8000",
).rstrip("/")

MAX_BODY_BYTES = 65536
MAX_CONTEXT_KEYS = 50
RATE_LIMIT_REQUESTS = 8
RATE_LIMIT_WINDOW_SECONDS = 60
UPSTREAM_TIMEOUT_SECONDS = 300

_execution_lock = asyncio.Semaphore(1)
_rate_lock = asyncio.Lock()
_rate_hits: dict[str, deque[float]] = defaultdict(deque)


class AutomationAssistPayload(BaseModel):
    message: str = Field(
        min_length=8,
        max_length=6000,
    )

    selected_product: Literal[
        "personal_automation",
        "business_automation",
    ]

    context: dict[str, Any] = Field(
        default_factory=dict,
    )

    confirm_draft_only: bool = True


def _model_validate(
    model_class: type[BaseModel],
    value: Any,
) -> BaseModel:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(value)

    return model_class.parse_obj(value)


def _model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(
            mode="json",
            exclude_none=True,
        )

    return model.dict(
        exclude_none=True,
    )


def _existing_internal_token() -> str:
    values = [
        os.getenv(
            "CREATOR_AI_TOKEN",
            "",
        ).strip(),
        os.getenv(
            "FREELANCER_AI_TOKEN",
            "",
        ).strip(),
        os.getenv(
            "BUSINESS_AI_TOKEN",
            "",
        ).strip(),
    ]

    nonempty = [
        value
        for value in values
        if value
    ]

    if len(nonempty) != 3:
        return ""

    if len(set(nonempty)) != 1:
        return ""

    return nonempty[0]


def _same_origin_request(
    request: Request,
) -> bool:
    marker = request.headers.get(
        "x-botconnector-request",
        "",
    ).strip().lower()

    if marker != "draft-assist":
        return False

    fetch_site = request.headers.get(
        "sec-fetch-site",
        "",
    ).strip().lower()

    if fetch_site not in {
        "",
        "same-origin",
        "same-site",
        "none",
    }:
        return False

    expected_host = request.headers.get(
        "host",
        "",
    ).strip().lower()

    origin = request.headers.get(
        "origin",
        "",
    ).strip()

    referer = request.headers.get(
        "referer",
        "",
    ).strip()

    supplied = origin or referer

    if not supplied:
        return True

    try:
        parsed = urllib.parse.urlsplit(
            supplied
        )
    except Exception:
        return False

    supplied_host = parsed.netloc.lower()

    return bool(
        expected_host
        and supplied_host == expected_host
    )


def _user_key(
    request: Request,
    user: Any,
) -> str:
    session_candidates = (
        "user_id",
        "account_id",
        "email",
    )

    try:
        for key in session_candidates:
            value = request.session.get(key)

            if value:
                return "session:" + str(value)
    except Exception:
        pass

    if isinstance(user, dict):
        for key in (
            "id",
            "user_id",
            "email",
        ):
            value = user.get(key)

            if value:
                return "user:" + str(value)

    client = (
        request.client.host
        if request.client
        else "unknown"
    )

    return "client:" + client


async def _check_rate_limit(
    key: str,
) -> None:
    now = time.monotonic()
    cutoff = (
        now
        - RATE_LIMIT_WINDOW_SECONDS
    )

    async with _rate_lock:
        hits = _rate_hits[key]

        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Terlalu banyak permintaan. "
                    "Coba kembali sebentar lagi."
                ),
            )

        hits.append(now)


def _call_brain(
    token: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        BRAIN_URL + "/v1/assist",
        data=body,
        method="POST",
        headers={
            "Authorization":
                "Bearer " + token,
            "Content-Type":
                "application/json",
            "X-BotConnector-Source":
                "platform-home",
        },
    )

    status = 0
    response_body = b""

    try:
        with urllib.request.urlopen(
            request,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        ) as response:
            status = response.status
            response_body = response.read(
                1048577
            )

    except urllib.error.HTTPError as exc:
        status = exc.code
        response_body = exc.read(
            1048577
        )

    if len(response_body) > 1048576:
        raise RuntimeError(
            "Respons Automation Brain terlalu besar."
        )

    try:
        data = json.loads(
            response_body.decode(
                "utf-8",
                errors="strict",
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "Respons Automation Brain bukan JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Respons Automation Brain bukan object."
        )

    return status, data


def _validate_draft_response(
    data: dict[str, Any],
) -> None:
    if data.get("mode") != "draft-only":
        raise RuntimeError(
            "Respons bukan draft-only."
        )

    effects = data.get(
        "external_effects"
    ) or {}

    if not isinstance(effects, dict):
        raise RuntimeError(
            "external_effects tidak valid."
        )

    if any(bool(value) for value in effects.values()):
        raise RuntimeError(
            "External effect terdeteksi."
        )

    for item in data.get(
        "tool_results",
        [],
    ):
        item_effects = (
            item.get("external_effects")
            if isinstance(item, dict)
            else {}
        ) or {}

        if any(
            bool(value)
            for value in item_effects.values()
        ):
            raise RuntimeError(
                "External effect tool terdeteksi."
            )


def install_automation_proxy(
    app: Any,
    *,
    current_user: Callable[[Request], Any],
    require_product_access: Callable[
        [Request, str],
        Any,
    ],
) -> None:
    existing_paths = {
        getattr(route, "path", "")
        for route in app.routes
    }

    if (
        "/api/automation/draft-assist"
        in existing_paths
    ):
        raise RuntimeError(
            "Automation proxy route sudah ada."
        )

    @app.get(
        "/api/automation/proxy/health",
        include_in_schema=True,
    )
    async def automation_proxy_health():
        return {
            "ok": True,
            "service":
                "botconnector-website-automation-proxy",
            "version": PROXY_VERSION,
            "mode": "draft-only",
            "external_effects": False,
        }

    @app.post(
        "/api/automation/draft-assist",
        include_in_schema=True,
    )
    async def automation_draft_assist(
        request: Request,
    ):
        user = current_user(request)

        if not user:
            return JSONResponse(
                status_code=401,
                content={
                    "detail":
                        "Login diperlukan.",
                },
            )

        if not _same_origin_request(request):
            return JSONResponse(
                status_code=403,
                content={
                    "detail":
                        "Permintaan same-origin diperlukan.",
                },
            )

        content_length = request.headers.get(
            "content-length",
            "",
        )

        if content_length:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Request terlalu besar.",
                    )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Content-Length tidak valid."
                    ),
                )

        body = await request.body()

        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Request terlalu besar.",
            )

        try:
            raw = json.loads(
                body.decode("utf-8")
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="JSON tidak valid.",
            ) from exc

        try:
            parsed = _model_validate(
                AutomationAssistPayload,
                raw,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(),
            ) from exc

        payload = _model_dump(parsed)

        if (
            payload.get(
                "confirm_draft_only"
            )
            is not True
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "confirm_draft_only=true "
                    "diperlukan."
                ),
            )

        context = payload.get(
            "context"
        ) or {}

        if len(context) > MAX_CONTEXT_KEYS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Terlalu banyak field context."
                ),
            )

        slug = (
            "personal"
            if payload[
                "selected_product"
            ] == "personal_automation"
            else "business"
        )

        denied = require_product_access(
            request,
            slug,
        )

        if denied:
            return JSONResponse(
                status_code=403,
                content={
                    "detail":
                        "Akses produk diperlukan.",
                },
            )

        key = _user_key(
            request,
            user,
        )

        await _check_rate_limit(key)

        token = _existing_internal_token()

        if not token:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Token internal yang sudah ada "
                    "tidak kompatibel."
                ),
            )

        payload["confirm_draft_only"] = True

        try:
            async with _execution_lock:
                status, data = await asyncio.wait_for(
                    asyncio.to_thread(
                        _call_brain,
                        token,
                        payload,
                    ),
                    timeout=(
                        UPSTREAM_TIMEOUT_SECONDS
                        + 10
                    ),
                )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Automation Brain timeout.",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc

        if status >= 500:
            raise HTTPException(
                status_code=502,
                detail={
                    "message":
                        "Automation Brain gagal.",
                    "upstream_status":
                        status,
                },
            )

        if status >= 400:
            return JSONResponse(
                status_code=status,
                content=data,
                headers={
                    "X-BotConnector-Execution":
                        "draft-only",
                },
            )

        _validate_draft_response(data)

        return JSONResponse(
            status_code=200,
            content=data,
            headers={
                "X-BotConnector-Execution":
                    "draft-only",
                "Cache-Control":
                    "no-store",
            },
        )
