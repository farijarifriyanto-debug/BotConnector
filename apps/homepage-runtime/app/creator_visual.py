# BOTCONNECTOR_WEBSITE_V0160_CREATOR_VISUAL

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import threading
import time
import uuid
from collections import deque
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field


# BOTCONNECTOR_VISUAL_COMPOSER_V4_FIXED
try:
    from .visual_composer import (
        PROFILE as VISUAL_COMPOSER_PROFILE,
        category_key as visual_category_key,
        compose_svg,
        template_key as visual_template_key,
    )
except ImportError:
    from visual_composer import (
        PROFILE as VISUAL_COMPOSER_PROFILE,
        category_key as visual_category_key,
        compose_svg,
        template_key as visual_template_key,
    )


router = APIRouter()

AI_URL = os.getenv(
    "PERSONAL_AI_VISUAL_URL",
    (
        "http://botconnector-personal-ai:8000"
        "/v1/creator/visual"
    ),
).strip()

TOKEN_FILE = pathlib.Path(
    os.getenv(
        "PERSONAL_AI_TOKEN_FILE",
        (
            "/run/secrets/"
            "botconnector_personal_ai_token"
        ),
    )
)

STORAGE_DIR = pathlib.Path(
    os.getenv(
        "CREATOR_VISUAL_STORAGE_DIR",
        (
            "/app/app/static/generated/"
            "creator-visuals"
        ),
    )
)

PUBLIC_PREFIX = (
    "/static/generated/creator-visuals"
)

PER_IP_LIMIT = 3
GLOBAL_LIMIT = 60
WINDOW_SECONDS = 3600
RETENTION_SECONDS = 86400
MAX_IMAGE_BYTES = 12_000_000

_rate_lock = threading.Lock()
_ip_hits: dict[str, deque[float]] = {}
_global_hits: deque[float] = deque()


class CreatorVisualInput(BaseModel):
    title: str = Field(
        min_length=2,
        max_length=240,
    )

    hook: str = Field(
        default="",
        max_length=900,
    )

    visuals: list[str] = Field(
        default_factory=list,
        max_length=8,
    )

    platform: str = Field(
        default="Instagram",
        max_length=80,
    )

    audience: str = Field(
        default="",
        max_length=500,
    )

    tone: str = Field(
        default="",
        max_length=160,
    )

    regenerate: bool = False


def _same_origin(
    request: Request,
) -> bool:
    host = (
        request.headers
        .get("host", "")
        .split(":", 1)[0]
        .strip()
        .lower()
    )

    origin = request.headers.get(
        "origin",
        "",
    ).strip()

    referer = request.headers.get(
        "referer",
        "",
    ).strip()

    candidates = [
        value
        for value in (
            origin,
            referer,
        )
        if value
    ]

    if not candidates:
        return False

    for value in candidates:
        try:
            parsed_host = (
                urlparse(value)
                .hostname
                or ""
            ).lower()
        except Exception:
            return False

        if not parsed_host:
            return False

        if parsed_host != host:
            return False

    marker = request.headers.get(
        "x-botconnector-request",
        "",
    ).strip()

    return marker == "creator-visual"


def _client_ip(
    request: Request,
) -> str:
    for header in (
        "cf-connecting-ip",
        "x-real-ip",
        "x-forwarded-for",
    ):
        value = request.headers.get(
            header,
            "",
        ).strip()

        if value:
            return value.split(
                ",",
                1,
            )[0].strip()[:100]

    if request.client:
        return str(
            request.client.host
        )[:100]

    return "unknown"


def _consume_limit(
    client_ip: str,
) -> None:
    now = time.time()
    cutoff = now - WINDOW_SECONDS

    with _rate_lock:
        while (
            _global_hits
            and _global_hits[0] < cutoff
        ):
            _global_hits.popleft()

        hits = _ip_hits.setdefault(
            client_ip,
            deque(),
        )

        while (
            hits
            and hits[0] < cutoff
        ):
            hits.popleft()

        if len(hits) >= PER_IP_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Batas pembuatan gambar trial "
                    "adalah 2 gambar per jam."
                ),
            )

        if len(_global_hits) >= GLOBAL_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Layanan gambar sedang mencapai "
                    "batas global. Coba lagi nanti."
                ),
            )

        hits.append(now)
        _global_hits.append(now)


def _read_token() -> str:
    try:
        token = TOKEN_FILE.read_text(
            encoding="utf-8",
        ).strip()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Token internal visual tidak "
                "dapat dibaca."
            ),
        ) from exc

    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Token internal visual kosong."
            ),
        )

    return token


def _extension(
    image_bytes: bytes,
    claimed: str,
) -> str:
    claimed = claimed.lower().strip()

    if claimed == "jpeg":
        claimed = "jpg"

    detected = ""

    if image_bytes.startswith(
        b"\xff\xd8\xff"
    ):
        detected = "jpg"

    elif image_bytes.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        detected = "png"

    elif (
        image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP"
    ):
        detected = "webp"

    if detected not in {
        "jpg",
        "png",
        "webp",
    }:
        raise HTTPException(
            status_code=502,
            detail=(
                "Format gambar AI tidak dikenali."
            ),
        )

    if (
        claimed
        and claimed != detected
    ):
        raise HTTPException(
            status_code=502,
            detail=(
                "Format respons gambar tidak sesuai."
            ),
        )

    return detected



# BOTCONNECTOR_CREATOR_VISUAL_TEXTFREE_V3_NO_UI
def _text_free_visuals(
    payload: CreatorVisualInput,
) -> list[str]:
    """
    Convert content into a safe visual metaphor.

    User copy is only used for category selection. It is never
    forwarded as wording for the image.
    """

    context = " ".join(
        [
            payload.title,
            payload.hook,
            payload.platform,
            payload.audience,
            *payload.visuals,
        ]
    ).casefold()

    def contains_any(
        terms: tuple[str, ...],
    ) -> bool:
        return any(
            term in context
            for term in terms
        )

    if contains_any(
        (
            "instagram",
            "whatsapp",
            "media sosial",
            "social media",
            "kontak",
            "contact",
            "prospek",
            "lead",
            "pelanggan",
            "customer",
            "akun",
            "audience",
            "pengikut",
            "follower",
        )
    ):
        scene = (
            "An adult small-business professional arranging "
            "a constellation of simple circular portrait symbols. "
            "The portrait circles are connected by smooth curved "
            "lines and accompanied by two abstract interlocking "
            "gears, representing organized customer connections."
        )

    elif contains_any(
        (
            "konten",
            "content",
            "creator",
            "kreator",
            "caption",
            "video",
            "youtube",
            "tiktok",
            "reels",
            "podcast",
            "kamera",
            "camera",
        )
    ):
        scene = (
            "An adult creative professional composing a visual "
            "idea using a camera silhouette, a light bulb, and "
            "several colorful geometric shapes arranged as one "
            "coherent editorial scene."
        )

    elif contains_any(
        (
            "lowongan",
            "loker",
            "job",
            "pekerjaan",
            "karier",
            "career",
            "freelancer",
            "proposal",
            "cv",
            "resume",
            "lamaran",
        )
    ):
        scene = (
            "An adult professional standing beside a plain "
            "briefcase and a group of simple human silhouettes "
            "connected by smooth curved paths, representing "
            "career opportunities and collaboration."
        )

    elif contains_any(
        (
            "belajar",
            "study",
            "edukasi",
            "education",
            "sekolah",
            "mahasiswa",
            "siswa",
            "kursus",
            "pelajaran",
            "tutorial",
        )
    ):
        scene = (
            "An adult learner with a graduation cap symbol, "
            "a glowing light bulb, and floating geometric knowledge "
            "shapes arranged in a clean and optimistic scene."
        )

    elif contains_any(
        (
            "keuangan",
            "finance",
            "uang",
            "profit",
            "trading",
            "investasi",
            "investment",
            "penjualan",
            "sales",
            "omzet",
        )
    ):
        scene = (
            "An adult business professional beside plain coins, "
            "ascending unlabeled geometric bars, and an abstract "
            "growth curve, arranged as a polished editorial scene."
        )

    elif contains_any(
        (
            "toko",
            "produk",
            "product",
            "jualan",
            "ecommerce",
            "e-commerce",
            "marketplace",
            "umkm",
            "usaha",
        )
    ):
        scene = (
            "An adult small-business owner organizing several "
            "plain unbranded product shapes and abstract customer "
            "symbols, with subtle gears representing automation."
        )

    else:
        scene = (
            "An adult business professional beside interlocking "
            "gears and connected geometric nodes, representing "
            "a simple automated workflow."
        )

    constraints = (
        "Create one coherent premium SaaS editorial illustration, "
        "not an infographic and not a mockup. Use natural adult "
        "proportions, clean flat-vector forms, a spacious neutral "
        "background, and balanced composition. The artwork is "
        "purely pictorial and contains zero typography or writing. "
        "Use only the described person and abstract symbols. "
        "Do not add labels, letters, words, numbers, logos, "
        "signatures, watermarks, menus, lists, interface elements, "
        "framed panels, speech bubbles, callouts, or decorative "
        "text-like marks."
    )

    return [
        scene,
        constraints,
    ]


def _cache_key(
    payload: CreatorVisualInput,
) -> str:
    normalized = {
        "title":
            payload.title.strip(),
        "hook":
            payload.hook.strip(),
        "visuals": [
            item.strip()
            for item in payload.visuals
            if item.strip()
        ],
        "platform":
            payload.platform.strip(),
        "audience":
            payload.audience.strip(),
        "tone":
            payload.tone.strip(),
    }

    # BOTCONNECTOR_CREATOR_VISUAL_EDITORIAL_CARTOON_V0166
    normalized["prompt_profile"] = 'hybrid-svg-idea-aware-v2-distinct-choices'

    if payload.regenerate:
        normalized["regenerate_nonce"] = (
            uuid.uuid4().hex
        )

    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def _cleanup() -> None:
    cutoff = time.time() - RETENTION_SECONDS

    try:
        STORAGE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        for path in STORAGE_DIR.iterdir():
            if not path.is_file():
                continue

            if path.suffix.lower() not in {
                ".jpg",
                ".png",
                ".webp",
            }:
                continue

            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                pass

    except Exception:
        pass


@router.get(
    "/api/automation/public-trial/"
    "creator-visual/health",
    include_in_schema=False,
)
async def creator_visual_health():
    return {
        "ok": True,
        "service": "botconnector-creator-visual",
        "version": "0.4",
        "render_mode": "hybrid_svg",
        "prompt_profile": VISUAL_COMPOSER_PROFILE,
        "model": "botconnector-visual-composer",
        "templates": [
            "benefit",
            "process",
            "before_after",
        ],
        "format": "svg",
        "per_ip_limit": PER_IP_LIMIT,
        "window_seconds": WINDOW_SECONDS,
        "retention_seconds": RETENTION_SECONDS,
    }


@router.post(
    "/api/automation/public-trial/"
    "creator-visual",
    include_in_schema=False,
)
async def creator_visual_generate(
    payload: CreatorVisualInput,
    request: Request,
):
    if not _same_origin(request):
        raise HTTPException(
            status_code=403,
            detail="Origin tidak diizinkan.",
        )

    client_ip = _client_ip(request)
    key = _cache_key(payload)

    STORAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = STORAGE_DIR / f"{key}.svg"

    if (
        not payload.regenerate
        and target.is_file()
        and target.stat().st_size > 1_000
    ):
        return {
            "ok": True,
            "cached": True,
            "image_url": (
                PUBLIC_PREFIX
                + "/"
                + target.name
            ),
            "model": "botconnector-visual-composer",
            "render_mode": "hybrid_svg",
            "template": visual_template_key(payload),
            "category": visual_category_key(payload),
        }

    _consume_limit(client_ip)

    started = time.perf_counter()
    svg = compose_svg(payload)

    temporary = STORAGE_DIR / (
        f".{key}-{uuid.uuid4().hex}.tmp"
    )

    try:
        temporary.write_text(
            svg,
            encoding="utf-8",
        )

        if temporary.stat().st_size <= 1_000:
            raise RuntimeError(
                "Ukuran SVG hasil composer tidak valid."
            )

        os.replace(
            temporary,
            target,
        )
    finally:
        temporary.unlink(
            missing_ok=True,
        )

    cutoff = (
        time.time()
        - RETENTION_SECONDS
    )

    try:
        for candidate in STORAGE_DIR.iterdir():
            if not candidate.is_file():
                continue

            if candidate == target:
                continue

            if candidate.suffix.lower() not in {
                ".svg",
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            }:
                continue

            if candidate.stat().st_mtime < cutoff:
                candidate.unlink(
                    missing_ok=True,
                )
    except OSError:
        pass

    elapsed_ms = int(
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    return {
        "ok": True,
        "cached": False,
        "image_url": (
            PUBLIC_PREFIX
            + "/"
            + target.name
        ),
        "model": "botconnector-visual-composer",
        "render_mode": "hybrid_svg",
        "template": visual_template_key(payload),
        "category": visual_category_key(payload),
        "elapsed_ms": elapsed_ms,
    }


def install_creator_visual_routes(
    app,
) -> None:
    existing = {
        getattr(route, "path", "")
        for route in app.routes
    }

    endpoint = (
        "/api/automation/public-trial/"
        "creator-visual"
    )

    if endpoint not in existing:
        app.include_router(router)
