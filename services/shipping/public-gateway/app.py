import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator


APP = FastAPI(
    title="BotConnector Shipping Public Gateway",
    version="1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

INTEGRATION_URL = os.environ.get(
    "BC_SHIPPING_INTEGRATION_URL",
    "http://127.0.0.1:18243",
).rstrip("/")

DB = os.environ["BC_SHIPPING_PUBLIC_DB"]

TIMEOUT = float(
    os.environ.get(
        "BC_SHIPPING_PUBLIC_TIMEOUT",
        "50",
    )
)

BUCKET_SECONDS = int(
    os.environ.get(
        "BC_SHIPPING_IDEMPOTENCY_BUCKET_SECONDS",
        "300",
    )
)

ALLOWED_COURIERS = {
    "jne",
    "jnt",
    "sicepat",
    "ninja",
    "anteraja",
    "pos",
}

LOCATION_RE = re.compile(
    r"^[0-9A-Za-zÀ-ÿ .,'()/&+-]{2,120}$"
)


def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def conn():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init():
    with conn() as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS public_rate_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_hash TEXT NOT NULL,
            source_ip_hash TEXT NOT NULL,
            http_status INTEGER NOT NULL,
            quote_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        db.execute("""
        CREATE INDEX IF NOT EXISTS idx_public_rate_created
        ON public_rate_requests(created_at)
        """)


init()


class RateRequest(BaseModel):

    origin: str = Field(
        min_length=2,
        max_length=120,
    )

    destination: str = Field(
        min_length=2,
        max_length=120,
    )

    weight_grams: int = Field(
        ge=1,
        le=100000,
    )

    couriers: list[str] = Field(
        min_length=1,
        max_length=6,
    )

    @field_validator(
        "origin",
        "destination",
    )
    @classmethod
    def validate_location(
        cls,
        value,
    ):
        value = " ".join(
            value.strip().split()
        )

        if not LOCATION_RE.fullmatch(
            value
        ):
            raise ValueError(
                "format lokasi tidak valid"
            )

        return value

    @field_validator("couriers")
    @classmethod
    def validate_couriers(
        cls,
        value,
    ):
        clean = []

        for courier in value:
            courier = (
                str(courier)
                .strip()
                .lower()
            )

            if courier not in ALLOWED_COURIERS:
                raise ValueError(
                    "kurir tidak didukung"
                )

            if courier not in clean:
                clean.append(
                    courier
                )

        if not clean:
            raise ValueError(
                "kurir wajib dipilih"
            )

        return clean


def normalized_payload(body):

    return {
        "origin":
            body.origin.lower(),

        "destination":
            body.destination.lower(),

        "weight_grams":
            body.weight_grams,

        "couriers":
            sorted(body.couriers),
    }


def request_hash(body):

    raw = json.dumps(
        normalized_payload(body),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    return hashlib.sha256(
        raw
    ).hexdigest()


def idempotency_key(body):

    bucket = int(
        time.time()
        // BUCKET_SECONDS
    )

    return (
        "public-rate:"
        + request_hash(body)
        + ":"
        + str(bucket)
    )


def ip_hash(request):

    ip = (
        request.headers
        .get(
            "x-real-ip",
            "",
        )
        .strip()
    )

    if not ip and request.client:
        ip = request.client.host

    return hashlib.sha256(
        ip.encode()
    ).hexdigest()


@APP.get("/api/shipping/health")
def health():

    return {
        "ok": True,
        "service":
            "shipping-public-gateway-v1",
    }


@APP.post("/api/shipping/rates")
async def rates(
    body: RateRequest,
    request: Request,
):

    payload = {
        "idempotency_key":
            idempotency_key(body),

        "provider":
            "rajaongkir",

        "origin_query":
            body.origin,

        "destination_query":
            body.destination,

        "weight_grams":
            body.weight_grams,

        "couriers":
            body.couriers,
    }

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            response = await client.post(
                INTEGRATION_URL
                + "/internal/shipping/rates",
                json=payload,
            )

    except httpx.TimeoutException:
        raise HTTPException(
            504,
            "Layanan ongkir sedang lambat. Silakan coba lagi.",
        )

    except httpx.HTTPError:
        raise HTTPException(
            503,
            "Layanan ongkir sedang tidak tersedia.",
        )

    if response.status_code != 200:
        raise HTTPException(
            502,
            "Penyedia ongkir belum dapat memproses permintaan.",
        )

    try:
        upstream = response.json()
        result = upstream["result"]
        quotes = result["quotes"]
    except Exception:
        raise HTTPException(
            502,
            "Respons ongkir tidak valid.",
        )

    if not isinstance(
        quotes,
        list,
    ):
        raise HTTPException(
            502,
            "Respons ongkir tidak valid.",
        )

    public_quotes = []

    for q in quotes:
        if not isinstance(q, dict):
            continue

        try:
            public_quotes.append({
                "courier":
                    str(q["courier"]),

                "service":
                    str(q["service"]),

                "cost":
                    int(q["cost"]),

                "currency":
                    "IDR",

                "etd":
                    str(q.get("etd", "")),
            })
        except Exception:
            continue

    if not public_quotes:
        raise HTTPException(
            404,
            "Tarif pengiriman tidak ditemukan.",
        )

    public_result = {
        "origin": {
            "label":
                str(
                    result
                    .get(
                        "origin",
                        {},
                    )
                    .get(
                        "label",
                        body.origin,
                    )
                ),

            "postal_code":
                str(
                    result
                    .get(
                        "origin",
                        {},
                    )
                    .get(
                        "postal_code",
                        "",
                    )
                ),
        },

        "destination": {
            "label":
                str(
                    result
                    .get(
                        "destination",
                        {},
                    )
                    .get(
                        "label",
                        body.destination,
                    )
                ),

            "postal_code":
                str(
                    result
                    .get(
                        "destination",
                        {},
                    )
                    .get(
                        "postal_code",
                        "",
                    )
                ),
        },

        "weight_grams":
            body.weight_grams,

        "quotes":
            public_quotes,
    }

    with conn() as db:
        db.execute("""
        INSERT INTO public_rate_requests(
            request_hash,
            source_ip_hash,
            http_status,
            quote_count,
            created_at
        )
        VALUES(?,?,?,?,?)
        """, (
            request_hash(body),
            ip_hash(request),
            200,
            len(public_quotes),
            now_iso(),
        ))

    return {
        "ok": True,
        "result": public_result,
    }
