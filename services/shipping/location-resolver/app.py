import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP = FastAPI()

DB = os.environ["BC_LOCATION_RESOLVER_DB"]

RAJAONGKIR_API_KEY = os.environ[
    "RAJAONGKIR_SHIPPING_COST_API_KEY"
]

RAJAONGKIR_BASE = os.environ.get(
    "BC_RAJAONGKIR_BASE_URL",
    "https://rajaongkir.komerce.id/api/v1",
).rstrip("/")

CACHE_TTL = int(
    os.environ.get(
        "BC_LOCATION_CACHE_TTL_SECONDS",
        "86400",
    )
)

HTTP_TIMEOUT = float(
    os.environ.get(
        "BC_LOCATION_HTTP_TIMEOUT",
        "30",
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
        CREATE TABLE IF NOT EXISTS location_queries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            idempotency_key TEXT NOT NULL UNIQUE,

            provider TEXT NOT NULL,

            normalized_query TEXT NOT NULL,

            query_fingerprint TEXT NOT NULL,

            response_json TEXT NOT NULL,

            source TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_location_query_fingerprint
        ON location_queries(
            provider,
            query_fingerprint,
            created_at
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS provider_calls(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            provider TEXT NOT NULL,

            operation TEXT NOT NULL,

            query_fingerprint TEXT NOT NULL,

            http_status INTEGER,

            normalized_status TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)


init()


class ResolveRequest(BaseModel):

    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
    )

    provider: str = Field(
        default="rajaongkir",
        min_length=1,
        max_length=50,
    )

    query: str = Field(
        min_length=2,
        max_length=200,
    )

    limit: int = Field(
        default=10,
        ge=1,
        le=50,
    )


def normalize_query(value: str) -> str:

    return " ".join(
        value.strip().lower().split()
    )


def fingerprint(
    provider: str,
    query: str,
    limit: int,
) -> str:

    raw = json.dumps(
        {
            "provider":
                provider,

            "query":
                query,

            "limit":
                limit,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    return hashlib.sha256(
        raw
    ).hexdigest()


def canonicalize_location(
    row: dict,
) -> dict:

    return {
        "provider":
            "rajaongkir",

        "provider_location_id":
            str(row.get("id", "")),

        "label":
            str(row.get("label", "")),

        "province":
            str(
                row.get(
                    "province_name",
                    row.get("province", ""),
                )
            ),

        "city":
            str(
                row.get(
                    "city_name",
                    row.get("city", ""),
                )
            ),

        "district":
            str(
                row.get(
                    "district_name",
                    row.get("district", ""),
                )
            ),

        "subdistrict":
            str(
                row.get(
                    "subdistrict_name",
                    row.get("subdistrict", ""),
                )
            ),

        "postal_code":
            str(
                row.get(
                    "zip_code",
                    row.get("postal_code", ""),
                )
            ),
    }


async def provider_search(
    query: str,
    limit: int,
    fp: str,
):

    try:

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            response = await client.get(
                RAJAONGKIR_BASE
                + "/destination/domestic-destination",

                headers={
                    "key":
                        RAJAONGKIR_API_KEY,
                },

                params={
                    "search":
                        query,

                    "limit":
                        limit,

                    "offset":
                        0,
                },
            )

    except httpx.TimeoutException:

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    provider,
                    operation,
                    query_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "rajaongkir",
                "destination_search",
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
            },
        )

    except httpx.HTTPError:

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    provider,
                    operation,
                    query_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "rajaongkir",
                "destination_search",
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
            },
        )

    if response.status_code != 200:

        if response.status_code in (401,403):
            status = "provider_auth_error"

        elif response.status_code == 429:
            status = "provider_rate_limited"

        elif 400 <= response.status_code < 500:
            status = "provider_request_rejected"

        else:
            status = "provider_unavailable"

        with conn() as c:
            c.execute("""
                INSERT INTO provider_calls(
                    provider,
                    operation,
                    query_fingerprint,
                    http_status,
                    normalized_status,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
            """, (
                "rajaongkir",
                "destination_search",
                fp,
                response.status_code,
                status,
                now_iso(),
            ))

        raise HTTPException(
            502,
            detail={
                "code":
                    status,

                "provider_http":
                    response.status_code,
            },
        )

    try:
        payload = response.json()

    except Exception:

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_invalid_response",
            },
        )

    rows = payload.get(
        "data",
    )

    if not isinstance(
        rows,
        list,
    ):

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_contract_error",
            },
        )

    results = [
        canonicalize_location(r)
        for r in rows
        if isinstance(r, dict)
    ]

    with conn() as c:

        c.execute("""
            INSERT INTO provider_calls(
                provider,
                operation,
                query_fingerprint,
                http_status,
                normalized_status,
                created_at
            )
            VALUES(?,?,?,?,?,?)
        """, (
            "rajaongkir",
            "destination_search",
            fp,
            200,
            "success",
            now_iso(),
        ))

    return results


@APP.get("/health")
def health():

    with conn() as c:

        queries = c.execute(
            "SELECT count(*) FROM location_queries"
        ).fetchone()[0]

        calls = c.execute(
            "SELECT count(*) FROM provider_calls"
        ).fetchone()[0]

    return {
        "ok":
            True,

        "version":
            "shipping-location-resolver-v1-candidate",

        "state":
            "sqlite",

        "providers":[
            "rajaongkir",
        ],

        "queries":
            queries,

        "provider_calls":
            calls,

        "cache_ttl_seconds":
            CACHE_TTL,
    }


@APP.post("/internal/shipping/locations/resolve")
async def resolve(
    body: ResolveRequest,
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

    query = normalize_query(
        body.query
    )

    if len(query) < 2:

        raise HTTPException(
            422,
            detail={
                "code":
                    "invalid_location_query",
            },
        )

    fp = fingerprint(
        provider,
        query,
        body.limit,
    )

    # --------------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------------

    with conn() as c:

        existing = c.execute("""
            SELECT response_json
            FROM location_queries
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

            "provider":
                provider,

            "query":
                query,

            "results":
                json.loads(
                    existing[
                        "response_json"
                    ]
                ),
        }

    # --------------------------------------------------------
    # QUERY CACHE
    # --------------------------------------------------------

    with conn() as c:

        cached = c.execute("""
            SELECT
                response_json,
                created_at
            FROM location_queries
            WHERE provider=?
              AND query_fingerprint=?
            ORDER BY id DESC
            LIMIT 1
        """, (
            provider,
            fp,
        )).fetchone()

    if cached:

        try:

            age = (
                time.time()
                - datetime.fromisoformat(
                    cached[
                        "created_at"
                    ]
                ).timestamp()
            )

        except Exception:

            age = (
                CACHE_TTL
                + 1
            )

        if age <= CACHE_TTL:

            results = json.loads(
                cached[
                    "response_json"
                ]
            )

            with conn() as c:

                c.execute("""
                    INSERT INTO location_queries(
                        idempotency_key,
                        provider,
                        normalized_query,
                        query_fingerprint,
                        response_json,
                        source,
                        created_at
                    )
                    VALUES(?,?,?,?,?,?,?)
                """, (
                    body.idempotency_key,
                    provider,
                    query,
                    fp,
                    json.dumps(
                        results,
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
                    "query_fingerprint",

                "provider":
                    provider,

                "query":
                    query,

                "results":
                    results,
            }

    # --------------------------------------------------------
    # REAL PROVIDER SEARCH
    # --------------------------------------------------------

    results = await provider_search(
        query,
        body.limit,
        fp,
    )

    with conn() as c:

        c.execute("""
            INSERT INTO location_queries(
                idempotency_key,
                provider,
                normalized_query,
                query_fingerprint,
                response_json,
                source,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
        """, (
            body.idempotency_key,
            provider,
            query,
            fp,
            json.dumps(
                results,
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

        "provider":
            provider,

        "query":
            query,

        "results":
            results,
    }
