import asyncio
import json
import time
import urllib.parse
from collections import defaultdict, deque
from typing import Any, Callable, Literal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.automation_proxy import (
    _call_brain,
    _existing_internal_token,
    _validate_draft_response,
)


PUBLIC_TRIAL_VERSION = "0.1.0"

MAX_BODY_BYTES = 16384
MAX_MESSAGE_LENGTH = 2500
REQUESTS_PER_IP = 5
RATE_WINDOW_SECONDS = 3600
GLOBAL_REQUESTS_PER_HOUR = 100

_request_lock = asyncio.Semaphore(1)
_rate_lock = asyncio.Lock()

_ip_hits: dict[str, deque[float]] = defaultdict(deque)
_global_hits: deque[float] = deque()


class PublicTrialRequest(BaseModel):
    mode: Literal[
        "creator",
        "freelancer",
        "whatsapp",
        "business_operations",
    ]

    message: str = Field(
        min_length=8,
        max_length=MAX_MESSAGE_LENGTH,
    )


def model_validate(
    model_class: type[BaseModel],
    value: Any,
) -> BaseModel:
    if hasattr(model_class, "model_validate"):
        return model_class.model_validate(value)

    return model_class.parse_obj(value)


def same_origin(request: Request) -> bool:
    marker = request.headers.get(
        "x-botconnector-request",
        "",
    ).strip().lower()

    if marker != "public-trial":
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

    supplied = (
        request.headers.get("origin", "").strip()
        or request.headers.get("referer", "").strip()
    )

    if not supplied:
        return True

    try:
        parsed = urllib.parse.urlsplit(supplied)
    except Exception:
        return False

    return bool(
        expected_host
        and parsed.netloc.lower() == expected_host
    )


def client_ip(request: Request) -> str:
    forwarded = request.headers.get(
        "x-forwarded-for",
        "",
    )

    if forwarded:
        values = [
            item.strip()
            for item in forwarded.split(",")
            if item.strip()
        ]

        if values:
            return values[-1][:80]

    if request.client:
        return request.client.host[:80]

    return "unknown"


async def enforce_rate_limit(ip: str) -> None:
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS

    async with _rate_lock:
        hits = _ip_hits[ip]

        while hits and hits[0] < cutoff:
            hits.popleft()

        while _global_hits and _global_hits[0] < cutoff:
            _global_hits.popleft()

        if len(hits) >= REQUESTS_PER_IP:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Batas uji coba tercapai. "
                    "Setiap pengunjung mendapat "
                    "5 percobaan per jam."
                ),
            )

        if len(_global_hits) >= GLOBAL_REQUESTS_PER_HOUR:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Kapasitas uji coba sedang penuh. "
                    "Silakan coba kembali nanti."
                ),
            )

        hits.append(now)
        _global_hits.append(now)


def brain_payload(
    trial: PublicTrialRequest,
) -> dict[str, Any]:
    if trial.mode in {
        "creator",
        "freelancer",
    }:
        product = "personal_automation"
    else:
        product = "business_automation"

    section = {
        "creator": "creator",
        "freelancer": "freelancer",
        "whatsapp": "chat",
        "business_operations": "operations",
    }[trial.mode]

    suffix = {
        "creator": (
            "\n\nIni uji coba publik. Buat draft konten "
            "saja dan jangan menerbitkan apa pun."
        ),
        "freelancer": (
            "\n\nIni uji coba publik. Buat draft proposal "
            "saja dan jangan mengirimkannya."
        ),
        "whatsapp": (
            "\n\nIni simulasi publik. Buat draft balasan "
            "WhatsApp saja dan jangan mengirim pesan."
        ),
        "business_operations": (
            "\n\nIni uji coba publik. Buat analisis atau "
            "rencana operasional saja. Jangan menyimpan "
            "prospek, membuat booking, atau menjalankan "
            "pembayaran."
        ),
    }[trial.mode]

    return {
        "message": trial.message + suffix,
        "selected_product": product,
        "context": {
            "source": "public-trial",
            "section": section,
            "trial_mode": trial.mode,
        },
        "confirm_draft_only": True,
    }


def public_response(
    data: dict[str, Any],
) -> dict[str, Any]:
    results = []

    for item in data.get("tool_results") or []:
        if not isinstance(item, dict):
            continue

        results.append({
            "tool": item.get("tool"),
            "latency_ms": item.get("latency_ms"),
            "result": item.get("result") or {},
            "external_effects":
                item.get("external_effects") or {},
        })

    return {
        "ok": True,
        "version": PUBLIC_TRIAL_VERSION,
        "mode": "draft-only",
        "product": data.get("product"),
        "product_name": data.get("product_name"),
        "skill": data.get("skill"),
        "executed_tools":
            data.get("executed_tools") or [],
        "tool_results": results,
        "external_effects":
            data.get("external_effects") or {},
        "safety_notice":
            data.get("safety_notice")
            or "Hasil hanya berupa draft dan tidak disimpan.",
    }


def install_public_trial(
    app: Any,
    *,
    templates: Any,
    base_context: Callable[
        [Request],
        dict[str, Any],
    ],
) -> None:
    existing_paths = {
        getattr(route, "path", "")
        for route in app.routes
    }

    required_paths = {
        "/try",
        "/api/automation/public-trial",
        "/api/automation/public-trial/health",
    }

    conflict = existing_paths & required_paths

    if conflict:
        raise RuntimeError(
            "Public trial route sudah ada: "
            + ", ".join(sorted(conflict))
        )

    @app.get(
        "/try",
        include_in_schema=False,
    )
    async def public_trial_page(
        request: Request,
    ):
        context = base_context(request)

        context.update({
            "trial_version":
                PUBLIC_TRIAL_VERSION,
            "trial_limit":
                REQUESTS_PER_IP,
            "trial_window_minutes":
                RATE_WINDOW_SECONDS // 60,
        })

        return templates.TemplateResponse(
            request,
            "public_trial.html",
            context,
        )

    @app.get(
        "/api/automation/public-trial/health",
    )
    async def public_trial_health():
        return {
            "ok": True,
            "service":
                "botconnector-public-trial",
            "version":
                PUBLIC_TRIAL_VERSION,
            "login_required": False,
            "mode": "draft-only",
            "automatic_save": False,
            "rate_limit": {
                "requests_per_ip":
                    REQUESTS_PER_IP,
                "window_seconds":
                    RATE_WINDOW_SECONDS,
            },
            "external_effects": False,
        }

    @app.post(
        "/api/automation/public-trial",
    )
    async def public_trial_execute(
        request: Request,
    ):
        if not same_origin(request):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Permintaan dari halaman "
                        "uji coba diperlukan."
                    ),
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
                        detail="Permintaan terlalu besar.",
                    )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Content-Length tidak valid.",
                ) from exc

        body = await request.body()

        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Permintaan terlalu besar.",
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
            parsed = model_validate(
                PublicTrialRequest,
                raw,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=exc.errors(),
            ) from exc

        await enforce_rate_limit(
            client_ip(request)
        )

        token = _existing_internal_token()

        if not token:
            raise HTTPException(
                status_code=503,
                detail="Layanan uji coba belum siap.",
            )

        payload = brain_payload(parsed)

        try:
            async with _request_lock:
                status, data = await asyncio.wait_for(
                    asyncio.to_thread(
                        _call_brain,
                        token,
                        payload,
                    ),
                    timeout=310,
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
                detail=(
                    "Automation Brain sedang "
                    "tidak tersedia."
                ),
            )

        if status >= 400:
            return JSONResponse(
                status_code=status,
                content=data,
                headers={
                    "Cache-Control": "no-store",
                    "X-BotConnector-Execution":
                        "public-trial-draft-only",
                },
            )

        _validate_draft_response(data)

        return JSONResponse(
            status_code=200,
            content=public_response(data),
            headers={
                "Cache-Control": "no-store",
                "X-BotConnector-Execution":
                    "public-trial-draft-only",
                "X-Robots-Tag": "noindex",
            },
        )
