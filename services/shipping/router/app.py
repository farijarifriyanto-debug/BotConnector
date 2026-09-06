import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP = FastAPI()


DB = os.environ["BC_SHIPPING_ROUTER_DB"]

RAJAONGKIR_URL = os.environ[
    "BC_PROVIDER_RAJAONGKIR_URL"
].rstrip("/")

HTTP_TIMEOUT = float(
    os.environ.get(
        "BC_SHIPPING_ROUTER_TIMEOUT",
        "35",
    )
)


def now_iso():

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
        CREATE TABLE IF NOT EXISTS router_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            idempotency_key TEXT NOT NULL UNIQUE,

            provider TEXT NOT NULL,

            request_fingerprint TEXT NOT NULL,

            response_json TEXT NOT NULL,

            source TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS provider_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            provider TEXT NOT NULL,

            request_fingerprint TEXT NOT NULL,

            http_status INTEGER,

            normalized_status TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)


init()


class RouteRateRequest(BaseModel):

    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
    )

    provider: str = Field(
        min_length=1,
        max_length=50,
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


def fingerprint(body):

    normalized = {
        "provider":
            body.provider.lower().strip(),

        "origin_id":
            body.origin_id,

        "destination_id":
            body.destination_id,

        "weight_grams":
            body.weight_grams,

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


@APP.get("/health")
def health():

    with conn() as c:

        requests = c.execute(
            "SELECT count(*) FROM router_requests"
        ).fetchone()[0]

        attempts = c.execute(
            "SELECT count(*) FROM provider_attempts"
        ).fetchone()[0]

    return {
        "ok":
            True,

        "version":
            "shipping-provider-router-v1-candidate",

        "state":
            "sqlite",

        "providers":[
            "rajaongkir",
        ],

        "requests":
            requests,

        "provider_attempts":
            attempts,
    }


@APP.post("/internal/shipping/providers/rates")
async def route_rate(
    body: RouteRateRequest,
):

    provider = (
        body.provider
        .strip()
        .lower()
    )

    if provider != "rajaongkir":

        raise HTTPException(
            422,
            detail={
                "code":
                    "unsupported_provider",

                "provider":
                    provider,
            },
        )

    fp = fingerprint(body)

    # --------------------------------------------------------
    # ROUTER IDEMPOTENCY
    # --------------------------------------------------------

    with conn() as c:

        existing = c.execute("""
            SELECT
                response_json
            FROM router_requests
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

            "router_cached":
                True,

            "provider":
                provider,

            "request_fingerprint":
                fp,

            "result":
                json.loads(
                    existing[
                        "response_json"
                    ]
                ),
        }

    # --------------------------------------------------------
    # PROVIDER REQUEST
    # --------------------------------------------------------

    provider_payload = {
        "idempotency_key":
            body.idempotency_key,

        "origin_id":
            body.origin_id,

        "destination_id":
            body.destination_id,

        "weight_grams":
            body.weight_grams,

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
                RAJAONGKIR_URL
                + "/internal/providers/rajaongkir/rates",

                json=provider_payload,
            )

    except httpx.TimeoutException:

        with conn() as c:

            c.execute("""
                INSERT INTO provider_attempts(
                    provider,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?)
            """, (
                provider,
                fp,
                None,
                "provider_timeout",
                now_iso(),
            ))

        raise HTTPException(
            503,
            detail={
                "code":
                    "provider_timeout",

                "provider":
                    provider,
            },
        )

    except httpx.HTTPError:

        with conn() as c:

            c.execute("""
                INSERT INTO provider_attempts(
                    provider,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?)
            """, (
                provider,
                fp,
                None,
                "provider_unavailable",
                now_iso(),
            ))

        raise HTTPException(
            503,
            detail={
                "code":
                    "provider_unavailable",

                "provider":
                    provider,
            },
        )

    try:

        payload = response.json()

    except Exception:

        payload = {
            "detail":{
                "code":
                    "provider_invalid_response"
            }
        }

    if response.status_code != 200:

        with conn() as c:

            c.execute("""
                INSERT INTO provider_attempts(
                    provider,
                    request_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?)
            """, (
                provider,
                fp,
                response.status_code,
                "provider_rejected",
                now_iso(),
            ))

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_rejected",

                "provider":
                    provider,

                "provider_http":
                    response.status_code,
            },
        )

    quotes = payload.get(
        "quotes"
    )

    if not isinstance(
        quotes,
        list,
    ):

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_contract_error",

                "provider":
                    provider,
            },
        )

    # Validate canonical provider output.

    for q in quotes:

        if not isinstance(
            q,
            dict,
        ):

            raise HTTPException(
                502,
                detail={
                    "code":
                        "provider_contract_error"
                },
            )

        for required in (
            "provider",
            "courier",
            "service",
            "cost",
            "currency",
            "etd",
        ):

            if required not in q:

                raise HTTPException(
                    502,
                    detail={
                        "code":
                            "provider_contract_error",

                        "missing":
                            required,
                    },
                )

    with conn() as c:

        c.execute("""
            INSERT INTO provider_attempts(
                provider,
                request_fingerprint,
                http_status,
                normalized_status,
                created_at
            )
            VALUES(?,?,?,?,?)
        """, (
            provider,
            fp,
            200,
            "success",
            now_iso(),
        ))

        c.execute("""
            INSERT INTO router_requests(
                idempotency_key,
                provider,
                request_fingerprint,
                response_json,
                source,
                created_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            body.idempotency_key,
            provider,
            fp,
            json.dumps(
                payload,
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

        "router_cached":
            False,

        "provider":
            provider,

        "request_fingerprint":
            fp,

        "result":
            payload,
    }
