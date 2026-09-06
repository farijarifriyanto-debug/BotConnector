import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


APP = FastAPI()


DB = os.environ[
    "BC_SHIPPING_INTEGRATION_DB"
]

RESOLVER_URL = os.environ[
    "BC_LOCATION_RESOLVER_URL"
].rstrip("/")

ROUTER_URL = os.environ[
    "BC_PROVIDER_ROUTER_URL"
].rstrip("/")

TIMEOUT = float(
    os.environ.get(
        "BC_SHIPPING_INTEGRATION_TIMEOUT",
        "45",
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
        CREATE TABLE IF NOT EXISTS shipping_rate_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            idempotency_key TEXT NOT NULL UNIQUE,

            request_fingerprint TEXT NOT NULL,

            provider TEXT NOT NULL,

            origin_query TEXT NOT NULL,

            destination_query TEXT NOT NULL,

            origin_provider_location_id TEXT NOT NULL,

            destination_provider_location_id TEXT NOT NULL,

            response_json TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS integration_steps(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            idempotency_key TEXT NOT NULL,

            step TEXT NOT NULL,

            status TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """)


init()


class CanonicalRateRequest(BaseModel):

    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
    )

    provider: str = Field(
        default="rajaongkir",
        min_length=1,
        max_length=50,
    )

    origin_query: str = Field(
        min_length=2,
        max_length=200,
    )

    destination_query: str = Field(
        min_length=2,
        max_length=200,
    )

    weight_grams: int = Field(
        gt=0,
        le=1000000,
    )

    couriers: list[str] = Field(
        min_length=1,
        max_length=50,
    )


def normalize_text(value: str):

    return " ".join(
        value.strip().lower().split()
    )


def request_fingerprint(
    body: CanonicalRateRequest,
):

    normalized = {

        "provider":
            body.provider.strip().lower(),

        "origin_query":
            normalize_text(
                body.origin_query
            ),

        "destination_query":
            normalize_text(
                body.destination_query
            ),

        "weight_grams":
            body.weight_grams,

        "couriers":
            sorted(
                set(
                    x.strip().lower()
                    for x in body.couriers
                    if x.strip()
                )
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


async def post_json(
    url: str,
    payload: dict,
):

    try:

        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:

            r = await client.post(
                url,
                json=payload,
            )

    except httpx.TimeoutException:

        raise HTTPException(
            503,
            detail={
                "code":
                    "internal_component_timeout",
            },
        )

    except httpx.HTTPError:

        raise HTTPException(
            503,
            detail={
                "code":
                    "internal_component_unavailable",
            },
        )

    try:

        data = r.json()

    except Exception:

        raise HTTPException(
            502,
            detail={
                "code":
                    "internal_component_invalid_response",
            },
        )

    if r.status_code != 200:

        raise HTTPException(
            502,
            detail={
                "code":
                    "internal_component_rejected",

                "component_http":
                    r.status_code,
            },
        )

    return data


def choose_location(
    results: list,
    query: str,
):

    if not isinstance(
        results,
        list,
    ) or not results:

        raise HTTPException(
            422,
            detail={
                "code":
                    "location_not_found",

                "query":
                    query,
            },
        )

    normalized = normalize_text(
        query
    )

    # Postal code gets exact preference.
    if normalized.isdigit():

        for row in results:

            if str(
                row.get(
                    "postal_code",
                    "",
                )
            ) == normalized:

                return row

    # Otherwise use provider ranked result.
    return results[0]


@APP.get("/health")
def health():

    with conn() as c:

        requests = c.execute(
            """
            SELECT count(*)
            FROM shipping_rate_requests
            """
        ).fetchone()[0]

        steps = c.execute(
            """
            SELECT count(*)
            FROM integration_steps
            """
        ).fetchone()[0]

    return {
        "ok":
            True,

        "version":
            "shipping-integration-v1-r2-candidate",

        "state":
            "sqlite",

        "rate_requests":
            requests,

        "integration_steps":
            steps,
    }


@APP.post("/internal/shipping/rates")
async def rates(
    body: CanonicalRateRequest,
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

    couriers = sorted(
        set(
            x.strip().lower()
            for x in body.couriers
            if x.strip()
        )
    )

    if not couriers:

        raise HTTPException(
            422,
            detail={
                "code":
                    "courier_required",
            },
        )

    fp = request_fingerprint(
        body
    )

    # --------------------------------------------------------
    # FACADE IDEMPOTENCY
    # --------------------------------------------------------

    with conn() as c:

        existing = c.execute("""
            SELECT response_json
            FROM shipping_rate_requests
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

            "result":
                json.loads(
                    existing[
                        "response_json"
                    ]
                ),
        }

    # --------------------------------------------------------
    # RESOLVE ORIGIN
    # --------------------------------------------------------

    origin_result = await post_json(
        RESOLVER_URL
        + "/internal/shipping/locations/resolve",

        {
            "idempotency_key":
                body.idempotency_key
                + ":origin",

            "provider":
                provider,

            "query":
                body.origin_query,

            "limit":
                5,
        },
    )

    origin = choose_location(
        origin_result.get(
            "results",
            [],
        ),
        body.origin_query,
    )

    with conn() as c:

        c.execute("""
            INSERT INTO integration_steps(
                idempotency_key,
                step,
                status,
                created_at
            )
            VALUES(?,?,?,?)
        """, (
            body.idempotency_key,
            "resolve_origin",
            "success",
            now_iso(),
        ))

    # --------------------------------------------------------
    # RESOLVE DESTINATION
    # --------------------------------------------------------

    destination_result = await post_json(
        RESOLVER_URL
        + "/internal/shipping/locations/resolve",

        {
            "idempotency_key":
                body.idempotency_key
                + ":destination",

            "provider":
                provider,

            "query":
                body.destination_query,

            "limit":
                5,
        },
    )

    destination = choose_location(
        destination_result.get(
            "results",
            [],
        ),
        body.destination_query,
    )

    with conn() as c:

        c.execute("""
            INSERT INTO integration_steps(
                idempotency_key,
                step,
                status,
                created_at
            )
            VALUES(?,?,?,?)
        """, (
            body.idempotency_key,
            "resolve_destination",
            "success",
            now_iso(),
        ))

    origin_id = str(
        origin[
            "provider_location_id"
        ]
    )

    destination_id = str(
        destination[
            "provider_location_id"
        ]
    )

    # --------------------------------------------------------
    # PROVIDER ROUTING
    # --------------------------------------------------------

    routed = await post_json(
        ROUTER_URL
        + "/internal/shipping/providers/rates",

        {
            "idempotency_key":
                body.idempotency_key
                + ":rate",

            "provider":
                provider,

            "origin_id":
                int(origin_id),

            "destination_id":
                int(destination_id),

            "weight_grams":
                body.weight_grams,

            "courier":
                ":".join(
                    couriers
                ),
        },
    )

    result = routed.get(
        "result",
    )

    if not isinstance(
        result,
        dict,
    ):

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_router_contract_error",
            },
        )

    quotes = result.get(
        "quotes",
    )

    if not isinstance(
        quotes,
        list,
    ):

        raise HTTPException(
            502,
            detail={
                "code":
                    "provider_rate_contract_error",
            },
        )

    canonical_quotes = []

    for q in quotes:

        if not isinstance(
            q,
            dict,
        ):
            continue

        required = (
            "provider",
            "courier",
            "service",
            "cost",
            "currency",
            "etd",
        )

        if not all(
            k in q
            for k in required
        ):
            continue

        canonical_quotes.append({
            "provider":
                q["provider"],

            "courier":
                q["courier"],

            "service":
                q["service"],

            "cost":
                q["cost"],

            "currency":
                q["currency"],

            "etd":
                q["etd"],
        })

    if not canonical_quotes:

        raise HTTPException(
            502,
            detail={
                "code":
                    "no_canonical_shipping_quotes",
            },
        )

    # Provider location IDs intentionally excluded.
    response = {

        "provider":
            provider,

        "origin":{

            "label":
                origin.get(
                    "label",
                    "",
                ),

            "province":
                origin.get(
                    "province",
                    "",
                ),

            "city":
                origin.get(
                    "city",
                    "",
                ),

            "district":
                origin.get(
                    "district",
                    "",
                ),

            "subdistrict":
                origin.get(
                    "subdistrict",
                    "",
                ),

            "postal_code":
                origin.get(
                    "postal_code",
                    "",
                ),
        },

        "destination":{

            "label":
                destination.get(
                    "label",
                    "",
                ),

            "province":
                destination.get(
                    "province",
                    "",
                ),

            "city":
                destination.get(
                    "city",
                    "",
                ),

            "district":
                destination.get(
                    "district",
                    "",
                ),

            "subdistrict":
                destination.get(
                    "subdistrict",
                    "",
                ),

            "postal_code":
                destination.get(
                    "postal_code",
                    "",
                ),
        },

        "weight_grams":
            body.weight_grams,

        "quotes":
            canonical_quotes,
    }

    # IDs are internal reconciliation data only.
    with conn() as c:

        c.execute("""
            INSERT INTO integration_steps(
                idempotency_key,
                step,
                status,
                created_at
            )
            VALUES(?,?,?,?)
        """, (
            body.idempotency_key,
            "provider_rate",
            "success",
            now_iso(),
        ))

        c.execute("""
            INSERT INTO shipping_rate_requests(
                idempotency_key,
                request_fingerprint,
                provider,
                origin_query,
                destination_query,
                origin_provider_location_id,
                destination_provider_location_id,
                response_json,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            body.idempotency_key,
            fp,
            provider,
            normalize_text(
                body.origin_query
            ),
            normalize_text(
                body.destination_query
            ),
            origin_id,
            destination_id,
            json.dumps(
                response,
                separators=(",", ":"),
            ),
            now_iso(),
        ))

    return {
        "ok":
            True,

        "duplicate":
            False,

        "result":
            response,
    }
