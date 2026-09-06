import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse


VERSION = "shipping-location-public-gateway-v1-candidate"

DB = os.environ.get(
    "BC_LOCATION_PUBLIC_DB",
    "/var/lib/botconnector-shipping-location-public-gateway-candidate/state.sqlite3",
)

RESOLVER_BASE = os.environ.get(
    "BC_LOCATION_RESOLVER_BASE",
    "http://127.0.0.1:18242",
).rstrip("/")

CACHE_TTL = int(
    os.environ.get(
        "BC_LOCATION_PUBLIC_CACHE_TTL",
        "300",
    )
)

HTTP_TIMEOUT = float(
    os.environ.get(
        "BC_LOCATION_PUBLIC_HTTP_TIMEOUT",
        "20",
    )
)


app = FastAPI(
    title="BotConnector Shipping Location Public Gateway",
    version="1",
    docs_url=None,
    redoc_url=None,
)


@contextmanager
def conn():
    db = sqlite3.connect(
        DB,
        timeout=10,
    )

    db.row_factory = sqlite3.Row

    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db():
    parent = os.path.dirname(DB)

    if parent:
        os.makedirs(
            parent,
            mode=0o700,
            exist_ok=True,
        )

    with conn() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS location_cache (
                query_key TEXT PRIMARY KEY,
                query_text TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                limit_value INTEGER NOT NULL,
                source TEXT NOT NULL,
                result_count INTEGER NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS upstream_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                http_status INTEGER,
                success INTEGER NOT NULL,
                error_class TEXT,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS
            idx_location_cache_expiry
            ON location_cache(expires_at);
            """
        )


init_db()


def normalize_query(value: str) -> str:
    q = " ".join(
        value.strip().split()
    )

    if len(q) < 2:
        raise HTTPException(
            422,
            "query_too_short",
        )

    if len(q) > 200:
        raise HTTPException(
            422,
            "query_too_long",
        )

    return q


def cache_key(q: str) -> str:
    return hashlib.sha256(
        q.casefold().encode()
    ).hexdigest()


def internal_idempotency(q: str) -> str:
    # 5-minute bucket.
    #
    # It is purely internal and is NEVER included
    # in the public response.
    bucket = int(time.time() // 300)

    raw = (
        "shipping-location-public-v1|"
        + str(bucket)
        + "|"
        + q.casefold()
    )

    digest = hashlib.sha256(
        raw.encode()
    ).hexdigest()

    return (
        "locpub-"
        + digest[:48]
    )


def sanitize_row(row: Any) -> dict:
    if not isinstance(row, dict):
        raise ValueError(
            "provider_result_not_object"
        )

    # Explicit allow-list.
    #
    # provider_location_id is intentionally absent.
    return {
        "label": str(
            row.get("label") or ""
        ),
        "province": str(
            row.get("province") or ""
        ),
        "city": str(
            row.get("city") or ""
        ),
        "district": str(
            row.get("district") or ""
        ),
        "subdistrict": str(
            row.get("subdistrict") or ""
        ),
        "postal_code": str(
            row.get("postal_code") or ""
        ),
    }


def public_payload(
    q: str,
    rows: list,
) -> dict:
    return {
        "ok": True,
        "query": q,
        "results": rows,
    }


def record_request(
    q: str,
    limit_value: int,
    source: str,
    count: int,
):
    with conn() as db:
        db.execute(
            """
            INSERT INTO requests
            (
                query_text,
                limit_value,
                source,
                result_count,
                created_at
            )
            VALUES (?,?,?,?,?)
            """,
            (
                q,
                limit_value,
                source,
                count,
                time.time(),
            ),
        )


def cached_response(
    q: str,
):
    key = cache_key(q)
    now = time.time()

    with conn() as db:
        row = db.execute(
            """
            SELECT response_json
            FROM location_cache
            WHERE query_key=?
              AND expires_at>?
            """,
            (
                key,
                now,
            ),
        ).fetchone()

    if not row:
        return None

    try:
        return json.loads(
            row["response_json"]
        )
    except Exception:
        return None


def save_cache(
    q: str,
    payload: dict,
):
    now = time.time()

    with conn() as db:
        db.execute(
            """
            INSERT INTO location_cache
            (
                query_key,
                query_text,
                response_json,
                created_at,
                expires_at
            )
            VALUES (?,?,?,?,?)
            ON CONFLICT(query_key)
            DO UPDATE SET
                query_text=excluded.query_text,
                response_json=excluded.response_json,
                created_at=excluded.created_at,
                expires_at=excluded.expires_at
            """,
            (
                cache_key(q),
                q,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                now,
                now + CACHE_TTL,
            ),
        )


def resolver_call(
    q: str,
    limit_value: int,
) -> dict:

    payload = {
        "idempotency_key":
            internal_idempotency(q),

        "provider":
            "rajaongkir",

        "query":
            q,

        "limit":
            limit_value,
    }

    body = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode()

    req = urllib.request.Request(
        RESOLVER_BASE
        + "/internal/shipping/locations/resolve",
        data=body,
        method="POST",
        headers={
            "Content-Type":
                "application/json",

            "Accept":
                "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=HTTP_TIMEOUT,
        ) as response:

            raw = response.read()

            status = response.status

    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code

        with conn() as db:
            db.execute(
                """
                INSERT INTO upstream_calls
                (
                    query_text,
                    http_status,
                    success,
                    error_class,
                    created_at
                )
                VALUES (?,?,?,?,?)
                """,
                (
                    q,
                    status,
                    0,
                    "http_error",
                    time.time(),
                ),
            )

        if status == 422:
            raise HTTPException(
                422,
                "location_query_invalid",
            )

        # ----------------------------------------------------
        # AUTOCOMPLETE FAIL-SOFT V1.1
        #
        # RajaOngkir destination search may return HTTP 404
        # for an unfinished prefix/no-match.
        #
        # Resolver preserves the real provider status in:
        #
        # detail.code = provider_request_rejected
        # detail.provider_http = 404
        #
        # ONLY this exact semantic becomes a successful
        # empty autocomplete result.
        # ----------------------------------------------------

        try:
            error_payload = json.loads(raw)
        except Exception:
            error_payload = None

        resolver_detail = (
            error_payload.get("detail")
            if isinstance(error_payload, dict)
            else None
        )

        if (
            status == 502
            and isinstance(resolver_detail, dict)
            and resolver_detail.get("code")
                == "provider_request_rejected"
            and resolver_detail.get("provider_http") == 404
        ):
            return {
                "ok": True,
                "duplicate": False,
                "cached": False,
                "cache_scope": "provider_no_match",
                "provider": "rajaongkir",
                "query": q,
                "results": [],
            }

        raise HTTPException(
            502,
            "location_provider_error",
        )

    except Exception:
        with conn() as db:
            db.execute(
                """
                INSERT INTO upstream_calls
                (
                    query_text,
                    http_status,
                    success,
                    error_class,
                    created_at
                )
                VALUES (?,?,?,?,?)
                """,
                (
                    q,
                    None,
                    0,
                    "transport_error",
                    time.time(),
                ),
            )

        raise HTTPException(
            502,
            "location_provider_unavailable",
        )

    with conn() as db:
        db.execute(
            """
            INSERT INTO upstream_calls
            (
                query_text,
                http_status,
                success,
                error_class,
                created_at
            )
            VALUES (?,?,?,?,?)
            """,
            (
                q,
                status,
                1 if status == 200 else 0,
                None,
                time.time(),
            ),
        )

    if status != 200:
        raise HTTPException(
            502,
            "location_provider_error",
        )

    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(
            502,
            "location_provider_invalid_json",
        )

    if data.get("ok") is not True:
        raise HTTPException(
            502,
            "location_provider_invalid_response",
        )

    rows = data.get("results")

    if not isinstance(rows, list):
        raise HTTPException(
            502,
            "location_provider_invalid_results",
        )

    safe = []

    for row in rows[:limit_value]:
        item = sanitize_row(row)

        if not item["label"]:
            continue

        safe.append(item)

    return public_payload(
        q,
        safe,
    )


@app.middleware("http")
async def security_headers(
    request,
    call_next,
):
    response = await call_next(
        request
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    response.headers[
        "X-Frame-Options"
    ] = "DENY"

    response.headers[
        "Referrer-Policy"
    ] = "no-referrer"

    return response


@app.get("/health")
def health():
    with conn() as db:
        cache_rows = db.execute(
            """
            SELECT count(*)
            FROM location_cache
            """
        ).fetchone()[0]

        requests = db.execute(
            """
            SELECT count(*)
            FROM requests
            """
        ).fetchone()[0]

        upstream = db.execute(
            """
            SELECT count(*)
            FROM upstream_calls
            """
        ).fetchone()[0]

    return {
        "ok": True,
        "version": VERSION,
        "cache_ttl_seconds":
            CACHE_TTL,
        "cache_rows":
            cache_rows,
        "requests":
            requests,
        "upstream_calls":
            upstream,
    }


@app.get("/api/shipping/locations")
def locations(
    q: str = Query(
        ...,
        min_length=2,
        max_length=200,
    ),
    limit: int = Query(
        10,
        ge=1,
        le=10,
    ),
):
    query = normalize_query(q)

    cached = cached_response(
        query
    )

    if cached is not None:

        rows = cached.get(
            "results",
            [],
        )[:limit]

        out = public_payload(
            query,
            rows,
        )

        record_request(
            query,
            limit,
            "cache",
            len(rows),
        )

        return JSONResponse(
            out,
            headers={
                "X-Location-Source":
                    "cache",
            },
        )

    upstream = resolver_call(
        query,
        10,
    )

    save_cache(
        query,
        upstream,
    )

    rows = upstream[
        "results"
    ][:limit]

    out = public_payload(
        query,
        rows,
    )

    record_request(
        query,
        limit,
        "resolver",
        len(rows),
    )

    return JSONResponse(
        out,
        headers={
            "X-Location-Source":
                "resolver",
        },
    )
