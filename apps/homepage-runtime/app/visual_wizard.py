# BOTCONNECTOR_WEBSITE_V0165_CONTENT_LOCKED_VISUAL_WIZARD
from __future__ import annotations

import os
import re
import threading
import time

from collections import defaultdict, deque
from typing import Any

import httpx

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    UploadFile,
)

from fastapi.responses import Response


PREFIX = (
    "/api/automation/public-trial/"
    "visual-wizard"
)

DIRECTOR_ENABLED = (
    os.getenv(
        "VISUAL_DIRECTOR_ENABLED",
        "false",
    ).strip().lower()
    == "true"
)

DIRECTOR_URL = os.getenv(
    "VISUAL_DIRECTOR_URL",
    "http://host.docker.internal:18096",
).rstrip("/")

MAX_JSON_BYTES = 96 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 15 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

router = APIRouter(
    prefix=PREFIX,
    include_in_schema=False,
)

rate_lock = threading.Lock()

rate_buckets: dict[
    tuple[str, str],
    deque[float],
] = defaultdict(deque)


def clean_text(
    value: Any,
    maximum: int = 500,
) -> str:
    if value is None:
        return ""

    if isinstance(value, list):
        value = " ".join(
            str(item)
            for item in value
            if item is not None
        )

    text = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    return text[:maximum]


def clean_list(
    value: Any,
    maximum_items: int = 8,
    maximum_length: int = 300,
) -> list[str]:
    if value is None:
        return []

    if not isinstance(value, list):
        value = [value]

    result: list[str] = []

    for item in value:
        text = clean_text(
            item,
            maximum_length,
        )

        if not text:
            continue

        result.append(text)

        if len(result) >= maximum_items:
            break

    return result


def client_key(
    request: Request,
) -> str:
    if request.client:
        return request.client.host

    return "unknown"


def enforce_rate(
    request: Request,
    bucket: str,
    maximum: int,
    window: int = 3600,
) -> None:
    now = time.monotonic()

    key = (
        client_key(request),
        bucket,
    )

    with rate_lock:
        values = rate_buckets[key]

        while (
            values
            and now - values[0] > window
        ):
            values.popleft()

        if len(values) >= maximum:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Batas penggunaan sementara "
                    "tercapai. Coba kembali nanti."
                ),
            )

        values.append(now)


def require_marker(
    request: Request,
) -> None:
    marker = request.headers.get(
        "x-botconnector-request",
        "",
    ).strip().lower()

    if marker != "visual-wizard":
        raise HTTPException(
            status_code=400,
            detail=(
                "Header Visual Wizard "
                "tidak valid."
            ),
        )


def require_director() -> None:
    if not DIRECTOR_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "Visual Director belum aktif."
            ),
        )


def response_detail(
    response: httpx.Response,
) -> str:
    try:
        body = response.json()
    except Exception:
        body = None

    if isinstance(body, dict):
        detail = body.get("detail")

        if isinstance(detail, str):
            return detail[:500]

        if detail is not None:
            return str(detail)[:500]

    text = response.text.strip()

    return (
        text[:500]
        if text
        else "Respons Visual Director tidak valid."
    )


async def read_json(
    request: Request,
) -> dict[str, Any]:
    length = request.headers.get(
        "content-length",
        "",
    )

    if (
        length.isdigit()
        and int(length) > MAX_JSON_BYTES
    ):
        raise HTTPException(
            status_code=413,
            detail=(
                "Data Visual Wizard terlalu besar."
            ),
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="JSON tidak valid.",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail=(
                "Isi permintaan harus "
                "berupa objek JSON."
            ),
        )

    return payload


def short_label(
    value: str,
    maximum: int = 54,
) -> str:
    value = clean_text(
        value,
        maximum + 20,
    )

    if len(value) <= maximum:
        return value

    return (
        value[:maximum].rstrip()
        + "…"
    )


def content_locked_plan(
    payload: dict[str, Any],
) -> dict[str, Any]:
    title = clean_text(
        payload.get("title")
        or payload.get("user_text")
        or "Ide konten",
        240,
    )

    hook = clean_text(
        payload.get("hook"),
        300,
    )

    angle = clean_text(
        payload.get("angle"),
        300,
    )

    script = clean_list(
        payload.get("script"),
        maximum_items=6,
        maximum_length=240,
    )

    visuals = clean_list(
        payload.get("visuals"),
        maximum_items=8,
        maximum_length=260,
    )

    platform = clean_text(
        payload.get("platform")
        or "media sosial",
        80,
    )

    audience = clean_text(
        payload.get("audience"),
        160,
    )

    tone = clean_text(
        payload.get("tone")
        or "natural dan informatif",
        120,
    )

    primary_visual = (
        visuals[0]
        if visuals
        else (
            angle
            or hook
            or title
        )
    )

    secondary_visual = (
        visuals[1]
        if len(visuals) > 1
        else (
            script[0]
            if script
            else primary_visual
        )
    )

    primary_action = (
        script[0]
        if script
        else (
            hook
            or angle
            or primary_visual
        )
    )

    secondary_action = (
        script[1]
        if len(script) > 1
        else secondary_visual
    )

    outline_summary = "; ".join(
        script[:4]
    )

    if not outline_summary:
        outline_summary = (
            primary_action
            + "; "
            + secondary_action
        )

    audience_context = (
        f"Ditujukan kepada {audience}. "
        if audience
        else ""
    )

    platform_context = (
        f"Komposisi dibuat untuk konten {platform}. "
    )

    style_context = (
        f"Foto realistis natural, gaya {tone}, "
        "detail bersih, pencahayaan seimbang, "
        "subjek utama terlihat jelas."
    )

    anchor = (
        f'Visualisasi langsung ide konten "{title}". '
    )

    concept_one_scene = (
        f"{primary_visual}. "
        f"{hook or angle}"
    ).strip()

    concept_one_prompt = (
        anchor
        + f"Subjek utama: {primary_visual}. "
        + (
            f"Pesan yang divisualkan: {hook}. "
            if hook
            else ""
        )
        + (
            f"Sudut konten: {angle}. "
            if angle
            else ""
        )
        + audience_context
        + platform_context
        + style_context
        + " Medium shot dengan fokus pada objek "
          "dan aktivitas utama dari ide konten."
    )

    concept_two_scene = (
        f"{primary_action}. "
        f"{secondary_visual}"
    ).strip()

    concept_two_prompt = (
        anchor
        + f"Aksi utama: {primary_action}. "
        + f"Objek yang wajib terlihat: {primary_visual}. "
        + (
            f"Elemen pendukung: {secondary_visual}. "
            if secondary_visual
            else ""
        )
        + audience_context
        + platform_context
        + style_context
        + " Sudut over-the-shoulder atau close action shot "
          "yang memperlihatkan tindakan inti secara jelas."
    )

    concept_three_scene = (
        f"Alur visual: {outline_summary}"
    )

    concept_three_prompt = (
        anchor
        + f"Perlihatkan alur konten berikut: {outline_summary}. "
        + f"Fokus tetap pada {primary_visual}. "
        + (
            "Elemen visual tambahan: "
            + "; ".join(visuals[:4])
            + ". "
            if visuals
            else ""
        )
        + audience_context
        + platform_context
        + style_context
        + " Wide environmental shot yang tetap menjaga "
          "objek dan tindakan utama sebagai pusat adegan."
    )

    concepts = [
        {
            "name": "Visual Utama Sesuai Ide",
            "scene": concept_one_scene,
            "camera": "medium focused shot",
            "location": (
                "lingkungan yang langsung "
                "mendukung isi konten"
            ),
            "visual_prompt": concept_one_prompt,
            "content_locked": True,
        },
        {
            "name": "Aksi Sesuai Hook",
            "scene": concept_two_scene,
            "camera": (
                "over-the-shoulder "
                "atau close action shot"
            ),
            "location": (
                "lokasi yang relevan "
                "dengan tindakan utama"
            ),
            "visual_prompt": concept_two_prompt,
            "content_locked": True,
        },
        {
            "name": "Alur Sesuai Outline",
            "scene": concept_three_scene,
            "camera": "wide environmental shot",
            "location": (
                "lingkungan yang memperlihatkan "
                "alur konten secara utuh"
            ),
            "visual_prompt": concept_three_prompt,
            "content_locked": True,
        },
    ]

    # BOTCONNECTOR_DISTINCT_VISUAL_CHOICES_V1
    # Pilihan visual wajib mempunyai template yang berbeda.
    variant_templates = (
        "benefit",
        "process",
        "before_after",
    )

    variant_labels = (
        "Manfaat Utama",
        "Cara Kerja 3 Langkah",
        "Sebelum dan Sesudah",
    )

    for variant_index, concept in enumerate(
        concepts[:3]
    ):
        template_name = variant_templates[
            variant_index
        ]

        template_marker = (
            "[BOTCONNECTOR_TEMPLATE:"
            + template_name
            + "]"
        )

        original_prompt = clean_text(
            concept.get("visual_prompt"),
            5000,
        )

        if (
            template_marker.casefold()
            not in original_prompt.casefold()
        ):
            concept["visual_prompt"] = (
                template_marker
                + " "
                + original_prompt
            ).strip()

        concept["template"] = template_name
        concept["variant_number"] = (
            variant_index + 1
        )
        concept["variant_label"] = (
            variant_labels[variant_index]
        )

    return {
        "ok": True,
        "version": "0.16.5",
        "director_mode": (
            "content_locked_fast"
        ),
        "ai_used": False,
        "content_locked": True,
        "content_title": title,
        "content_anchor": primary_visual,
        "summary": (
            "Tiga visual dibuat langsung dari "
            "judul, hook, outline, dan ide visual "
            "pada kartu konten ini."
        ),
        "concepts": concepts,
        "mode": "generate",
    }


@router.get("/health")
async def wizard_health() -> dict[str, Any]:
    require_director()

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
        ) as client:
            response = await client.get(
                DIRECTOR_URL + "/health"
            )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail=(
                "Visual Director belum "
                "dapat dihubungi."
            ),
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=response_detail(response),
        )

    director = response.json()

    return {
        "ok": True,
        "service": (
            "botconnector-visual-wizard"
        ),
        "version": "0.16.5",
        "planning_mode": (
            "content_locked_fast"
        ),
        "director": director,
        "features": {
            "content_locked_plan": True,
            "concept_cards": True,
            "image_generator": True,
            "upload": True,
            "remove_background": True,
            "download": True,
        },
    }


@router.post("/plan")
async def guided_plan(
    request: Request,
) -> dict[str, Any]:
    require_marker(request)

    enforce_rate(
        request,
        "content-plan",
        60,
    )

    payload = await read_json(request)

    return content_locked_plan(
        payload
    )


@router.post("/rembg")
async def remove_background(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    require_marker(request)

    enforce_rate(
        request,
        "rembg",
        12,
    )

    require_director()

    content_type = (
        file.content_type or ""
    ).lower()

    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Format yang didukung: "
                "JPG, PNG, dan WebP."
            ),
        )

    data = await file.read(
        MAX_UPLOAD_BYTES + 1
    )

    filename = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        file.filename or "upload",
    )[:120]

    await file.close()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="File gambar kosong.",
        )

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Ukuran gambar maksimal 10 MB."
            ),
        )

    detected_type = ""

    if data.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        detected_type = "image/png"

    elif data.startswith(
        b"\xff\xd8\xff"
    ):
        detected_type = "image/jpeg"

    elif (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        detected_type = "image/webp"

    if detected_type != content_type:
        raise HTTPException(
            status_code=415,
            detail=(
                "Isi file tidak sesuai "
                "dengan format gambar."
            ),
        )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                900.0,
                connect=10.0,
            )
        ) as client:
            response = await client.post(
                (
                    DIRECTOR_URL
                    + "/v1/visual-director/"
                    "tools/rembg/remove"
                ),
                files={
                    "file": (
                        filename,
                        data,
                        content_type,
                    )
                },
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=(
                "Proses hapus background "
                "melewati batas waktu."
            ),
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail=(
                "Mesin hapus background "
                "belum dapat dihubungi."
            ),
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=(
                response.status_code
                if response.status_code < 500
                else 502
            ),
            detail=response_detail(response),
        )

    try:
        body = response.json()
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=(
                "Respons hapus background "
                "tidak valid."
            ),
        )

    result_id = str(
        body.get("result_id", "")
    )

    if not re.fullmatch(
        r"[a-f0-9]{32}",
        result_id,
    ):
        raise HTTPException(
            status_code=502,
            detail="ID hasil tidak valid.",
        )

    body["download_url"] = (
        PREFIX
        + "/outputs/"
        + result_id
    )

    return body


@router.get("/outputs/{result_id}")
async def output_image(
    result_id: str,
    request: Request,
) -> Response:
    enforce_rate(
        request,
        "output",
        120,
    )

    require_director()

    if not re.fullmatch(
        r"[a-f0-9]{32}",
        result_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Hasil tidak ditemukan.",
        )

    try:
        async with httpx.AsyncClient(
            timeout=60.0,
        ) as client:
            response = await client.get(
                (
                    DIRECTOR_URL
                    + "/v1/visual-director/"
                    "outputs/"
                    + result_id
                )
            )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail=(
                "Hasil gambar belum "
                "dapat diambil."
            ),
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=(
                "Hasil gambar tidak ditemukan."
            ),
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=response_detail(response),
        )

    if len(response.content) > MAX_OUTPUT_BYTES:
        raise HTTPException(
            status_code=502,
            detail=(
                "Ukuran hasil gambar "
                "tidak valid."
            ),
        )

    return Response(
        content=response.content,
        media_type="image/png",
        headers={
            "Cache-Control": (
                "private, max-age=3600"
            ),
            "X-Content-Type-Options": (
                "nosniff"
            ),
            "Content-Disposition": (
                'inline; filename="'
                "botconnector-background-"
                f'{result_id}.png"'
            ),
        },
    )


def install_visual_wizard_routes(
    app: Any,
) -> None:
    existing = {
        getattr(route, "path", "")
        for route in app.routes
    }

    if any(
        path.startswith(PREFIX)
        for path in existing
    ):
        return

    app.include_router(router)
