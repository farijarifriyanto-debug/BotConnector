import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP = FastAPI()

DB = os.environ["BC_RO_DB"]

API_KEY = os.environ["RAJAONGKIR_SHIPPING_COST_API_KEY"]

BASE_URL = os.environ.get(
    "BC_RO_BASE_URL",
    "https://rajaongkir.komerce.id/api/v1",
).rstrip("/")

CACHE_TTL = int(
    os.environ.get(
        "BC_RO_CACHE_TTL_SECONDS",
        "300",
    )
)

HTTP_TIMEOUT = float(
    os.environ.get(
        "BC_RO_HTTP_TIMEOUT",
        "30",
    )
)


def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:

        c.execute("""
        CREATE TABLE IF NOT EXISTS rate_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            idempotency_key TEXT NOT NULL UNIQUE,

            request_fingerprint TEXT NOT NULL,

            origin_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            weight_grams INTEGER NOT NULL,
            courier TEXT NOT NULL,

            response_json TEXT NOT NULL,

            source TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_rate_fingerprint
        ON rate_requests(
            request_fingerprint,
            created_at
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS provider_calls(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            operation TEXT NOT NULL,

            request_fingerprint TEXT,

            http_status INTEGER,

            normalized_status TEXT NOT NULL,

            provider_message TEXT,

            created_at TEXT NOT NULL
        )
        """)


init()


class RateRequest(BaseModel):
    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
    )

    origin_id: int
    destination_id: int

    weight_grams: int = Field(
        gt=0,
        le=1000000,
    )

    courier: str = Field(
        min_length=1,
        max_length=500,
    )


def request_fingerprint(
    body: RateRequest,
) -> str:

    normalized = {
        "origin_id":
            int(body.origin_id),

        "destination_id":
            int(body.destination_id),

        "weight_grams":
            int(body.weight_grams),

        "courier":
            ":".join(
                x.strip().lower()
                for x in body.courier.split(":")
                if x.strip()
            ),
    }

    raw = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    return hashlib.sha256(
        raw
    ).hexdigest()


def normalize_provider_error(
    status: int,
    payload: Any,
) -> dict:

    message = ""

    if isinstance(payload, dict):
        meta = payload.get("meta")

        if isinstance(meta, dict):
            message = str(
                meta.get("message", "")
            )

        if not message:
            message = str(
                payload.get(
                    "message",
                    "",
                )
            )

    if status in (401, 403):
        code = "provider_auth_error"

    elif status == 404:
        code = "provider_not_found"

    elif status == 429:
        code = "provider_rate_limited"

    elif 400 <= status < 500:
        code = "provider_request_rejected"

    elif status >= 500:
        code = "provider_unavailable"

    else:
        code = "provider_error"

    return {
        "provider":
            "rajaongkir",

        "code":
            code,

        "http_status":
            status,

        "message":
            message[:300],
    }


def canonicalize_rates(
    payload: dict,
) -> list[dict]:

    rows = payload.get(
        "data",
        [],
    )

    if not isinstance(
        rows,
        list,
    ):
        raise ValueError(
            "provider_data_not_list"
        )

    out = []

    for row in rows:

        if not isinstance(
            row,
            dict,
        ):
            continue

        courier = (
            row.get("code")
            or row.get("name")
            or row.get("courier")
        )

        service = (
            row.get("service")
            or row.get("service_name")
            or row.get("type")
        )

        cost = (
            row.get("cost")
            if row.get("cost") is not None
            else row.get("price")
        )

        etd = (
            row.get("etd")
            or row.get("estimated")
            or row.get("estimate")
            or ""
        )

        if (
            courier is None
            or service is None
            or cost is None
        ):
            continue

        try:
            cost = int(cost)
        except Exception:
            try:
                cost = int(
                    float(cost)
                )
            except Exception:
                continue

        out.append({
            "provider":
                "rajaongkir",

            "courier":
                str(courier).lower(),

            "service":
                str(service),

            "cost":
                cost,

            "currency":
                "IDR",

            "etd":
                str(etd),
        })

    return out


async def provider_rate_request(
    body: RateRequest,
    fingerprint: str,
) -> list[dict]:

    headers = {
        "key":
            API_KEY,

        "Content-Type":
            "application/x-www-form-urlencoded",
    }

    data = {
        "origin":
            str(body.origin_id),

        "destination":
            str(body.destination_id),

        "weight":
            str(body.weight_grams),

        "courier":
            body.courier,
    }

    try:

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            response = await client.post(
                BASE_URL
                + "/calculate/domestic-cost",

                headers=headers,
                data=data,
            )

    except httpx.TimeoutException:

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    operation,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    provider_message,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "domestic-cost",
                fingerprint,
                None,
                "provider_timeout",
                "timeout",
                now_iso(),
            ))

        raise HTTPException(
            503,
            detail={
                "provider":
                    "rajaongkir",

                "code":
                    "provider_timeout",
            },
        )

    except httpx.HTTPError:

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    operation,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    provider_message,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "domestic-cost",
                fingerprint,
                None,
                "provider_network_error",
                "network_error",
                now_iso(),
            ))

        raise HTTPException(
            503,
            detail={
                "provider":
                    "rajaongkir",

                "code":
                    "provider_network_error",
            },
        )

    try:
        payload = response.json()
    except Exception:
        payload = {}

    if response.status_code != 200:

        normalized = normalize_provider_error(
            response.status_code,
            payload,
        )

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    operation,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    provider_message,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "domestic-cost",
                fingerprint,
                response.status_code,
                normalized["code"],
                normalized["message"],
                now_iso(),
            ))

        mapped_http = 502

        if response.status_code == 429:
            mapped_http = 503

        elif response.status_code in (
            401,
            403,
        ):
            mapped_http = 502

        elif 400 <= response.status_code < 500:
            mapped_http = 422

        raise HTTPException(
            mapped_http,
            detail=normalized,
        )

    try:

        rates = canonicalize_rates(
            payload
        )

    except ValueError:

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    operation,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    provider_message,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "domestic-cost",
                fingerprint,
                200,
                "provider_contract_error",
                "provider_data_not_list",
                now_iso(),
            ))

        raise HTTPException(
            502,
            detail={
                "provider":
                    "rajaongkir",

                "code":
                    "provider_contract_error",
            },
        )

    with conn() as c:
        c.execute("""
            INSERT INTO provider_calls(
                operation,
                request_fingerprint,
                http_status,
                normalized_status,
                provider_message,
                created_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            "domestic-cost",
            fingerprint,
            200,
            "success",
            "",
            now_iso(),
        ))

    return rates


@APP.get("/health")
def health():

    with conn() as c:

        requests = c.execute(
            """
            SELECT count(*)
            FROM rate_requests
            """
        ).fetchone()[0]

        calls = c.execute(
            """
            SELECT count(*)
            FROM provider_calls
            """
        ).fetchone()[0]

    return {
        "ok":
            True,

        "version":
            "rajaongkir-cost-adapter-v1-candidate",

        "provider":
            "rajaongkir",

        "state":
            "sqlite",

        "cache_ttl_seconds":
            CACHE_TTL,

        "rate_requests":
            requests,

        "provider_calls":
            calls,
    }


@APP.post("/internal/providers/rajaongkir/rates")
async def rates(
    body: RateRequest,
):

    fingerprint = request_fingerprint(
        body
    )

    # --------------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------------

    with conn() as c:

        existing = c.execute("""
            SELECT response_json
            FROM rate_requests
            WHERE idempotency_key=?
        """, (
            body.idempotency_key,
        )).fetchone()

    if existing:

        return {
            "ok":
                True,

            "duplicate":
                True,

            "cached":
                True,

            "cache_scope":
                "idempotency",

            "request_fingerprint":
                fingerprint,

            "quotes":
                json.loads(
                    existing[
                        "response_json"
                    ]
                ),
        }

    # --------------------------------------------------------
    # CACHE BY REQUEST FINGERPRINT
    # --------------------------------------------------------

    now_epoch = time.time()

    with conn() as c:

        cache_rows = c.execute("""
            SELECT
                response_json,
                created_at
            FROM rate_requests
            WHERE request_fingerprint=?
            ORDER BY id DESC
            LIMIT 1
        """, (
            fingerprint,
        )).fetchone()

    if cache_rows:

        try:

            dt = datetime.fromisoformat(
                cache_rows["created_at"]
            )

            age = (
                now_epoch
                - dt.timestamp()
            )

        except Exception:

            age = (
                CACHE_TTL
                + 1
            )

        if age <= CACHE_TTL:

            quotes = json.loads(
                cache_rows[
                    "response_json"
                ]
            )

            with conn() as c:

                c.execute("""
                    INSERT INTO rate_requests(
                        idempotency_key,
                        request_fingerprint,
                        origin_id,
                        destination_id,
                        weight_grams,
                        courier,
                        response_json,
                        source,
                        created_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?)
                """, (
                    body.idempotency_key,
                    fingerprint,
                    str(body.origin_id),
                    str(body.destination_id),
                    body.weight_grams,
                    body.courier,
                    json.dumps(
                        quotes,
                        separators=(",", ":"),
                    ),
                    "cache",
                    now_iso(),
                ))

            return {
                "ok":
                    True,

                "duplicate":
                    False,

                "cached":
                    True,

                "cache_scope":
                    "request_fingerprint",

                "request_fingerprint":
                    fingerprint,

                "quotes":
                    quotes,
            }

    # --------------------------------------------------------
    # REAL PROVIDER CALL
    # --------------------------------------------------------

    quotes = await provider_rate_request(
        body,
        fingerprint,
    )

    with conn() as c:

        c.execute("""
            INSERT INTO rate_requests(
                idempotency_key,
                request_fingerprint,
                origin_id,
                destination_id,
                weight_grams,
                courier,
                response_json,
                source,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            body.idempotency_key,
            fingerprint,
            str(body.origin_id),
            str(body.destination_id),
            body.weight_grams,
            body.courier,
            json.dumps(
                quotes,
                separators=(",", ":"),
            ),
            "provider",
            now_iso(),
        ))

    return {
        "ok":
            True,

        "duplicate":
            False,

        "cached":
            False,

        "cache_scope":
            None,

        "request_fingerprint":
            fingerprint,

        "quotes":
            quotes,
    }
