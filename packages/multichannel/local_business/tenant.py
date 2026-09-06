"""Trusted Business Suite identity, entitlement, membership, and scope.

The browser may send object identifiers, but it never selects the tenant. A
request's business is derived from the Core session and the membership table.
The ContextVar is request-scoped and is only a convenience for legacy service
functions that do not yet accept an explicit context argument.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from ..persistence.db import koneksi


BUSINESS_PRODUCT = "business-suite"
PILOT_TENANT = "LOCAL-PILOT"
_current: ContextVar["TenantContext | None"] = ContextVar(
    "business_suite_tenant_context", default=None
)
_log = logging.getLogger("botconnector.business_suite.auth")


@dataclass(frozen=True)
class TenantContext:
    auth_kind: str
    user_id: str
    email: str
    business_id: int | None
    tenant_id: str
    role: str
    entitlement_status: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.auth_kind == "admin"


class ScopeError(LookupError):
    """Raised by domain functions when an object is outside the tenant."""


def current_context() -> TenantContext:
    context = _current.get()
    if context is None:
        raise RuntimeError("Business Suite tenant context is not established")
    return context


def _core_request(request: Request, path: str) -> Any:
    base = os.environ.get("BC_CORE_API_URL", "http://127.0.0.1:8050").rstrip("/")
    token = request.cookies.get("bc_session", "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    req = urllib.request.Request(
        f"{base}{path}",
        headers={"Cookie": f"bc_session={token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(status_code=401, detail="Sesi Core tidak valid") from exc
        raise HTTPException(status_code=503, detail="Core tidak tersedia") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Core tidak tersedia") from exc
    if not isinstance(payload, (dict, list)):
        raise HTTPException(status_code=503, detail="Respons Core tidak valid")
    return payload


def _entitled(request: Request, user_id: str) -> str:
    products = _core_request(request, "/v1/me/products")
    if not isinstance(products, list):
        raise HTTPException(status_code=503, detail="Respons entitlement tidak valid")
    for product in products:
        if (
            product.get("slug") == BUSINESS_PRODUCT
            and product.get("product_status") == "active"
            and product.get("access_status") in {"active", "trial"}
        ):
            return str(product["access_status"])
    raise HTTPException(status_code=403, detail="Business Suite belum aktif untuk akun ini")


def _membership(user_id: str) -> dict[str, Any] | None:
    with koneksi() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bm.business_id, bm.role, b.tenant_id, b.status
                FROM local_business.business_membership bm
                JOIN local_business.business b ON b.id=bm.business_id
                WHERE bm.user_id=%s AND bm.status='ACTIVE' AND b.status='ACTIVE'
                ORDER BY bm.created_at, bm.business_id
                LIMIT 1
                """,
                (user_id,),
            )
            return cur.fetchone()


def _admin_context(request: Request) -> TenantContext | None:
    """Validate the existing Admin Gate without mixing cookie semantics."""
    token = request.cookies.get("bc_admin", "")
    if not token:
        return None
    req = urllib.request.Request(
        "http://127.0.0.1:18160/check",
        headers={"Cookie": f"bc_admin={token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Authorization service unavailable") from exc
    if not isinstance(payload, dict) or not payload.get("admin"):
        raise HTTPException(status_code=403, detail="Admin authorization required")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=403, detail="Admin authorization required")
    return TenantContext("admin", "admin:" + email, email, 336, PILOT_TENANT, "admin")


def resolve(request: Request, *, allow_unprovisioned: bool = False) -> TenantContext:
    admin = _admin_context(request)
    if admin:
        _current.set(admin)
        request.state.business_context = admin
        return admin

    me = _core_request(request, "/v1/me")
    user = me.get("user") or {}
    user_id = str(user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Sesi Core tidak valid")
    entitlement = _entitled(request, user_id)
    membership = _membership(user_id)
    if not membership:
        if allow_unprovisioned:
            context = TenantContext(
                "customer", user_id, str(user.get("email") or ""), None,
                f"user:{user_id}", "owner", entitlement,
            )
            _current.set(context)
            request.state.business_context = context
            return context
        raise HTTPException(status_code=409, detail="Business Suite onboarding required")
    context = TenantContext(
        "customer", user_id, str(user.get("email") or ""),
        int(membership["business_id"]), str(membership["tenant_id"]),
        str(membership["role"]).lower(), entitlement,
    )
    _current.set(context)
    request.state.business_context = context
    return context


def require_auth(request: Request) -> TenantContext:
    return resolve(request)


def require_role(*roles: str):
    allowed = {role.lower() for role in roles}

    async def dependency(request: Request) -> TenantContext:
        context = resolve(request)
        if context.role not in allowed and not context.is_admin:
            raise HTTPException(status_code=403, detail="Role tidak diizinkan")
        return context

    return dependency


def optional_auth(request: Request) -> TenantContext | None:
    try:
        return resolve(request, allow_unprovisioned=True)
    except HTTPException:
        return None


def require_business_id() -> int:
    context = current_context()
    if context.business_id is None:
        raise HTTPException(status_code=409, detail="Business Suite onboarding required")
    return context.business_id


def assert_object(kind: str, object_id: int, business_id: int) -> None:
    queries = {
        "business": ("SELECT 1 FROM local_business.business WHERE id=%s AND id=%s", (object_id, business_id)),
        "branch": ("SELECT 1 FROM local_business.branch WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "register": ("""SELECT 1 FROM local_business.register r JOIN local_business.branch b ON b.id=r.branch_id
                       WHERE r.id=%s AND b.business_id=%s""", (object_id, business_id)),
        "cashier": ("SELECT 1 FROM local_business.cashier WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "warehouse": ("SELECT 1 FROM local_business.branch WHERE warehouse_id=%s AND business_id=%s", (object_id, business_id)),
        "product": ("SELECT 1 FROM local_business.business_product WHERE master_sku_id=%s AND business_id=%s", (object_id, business_id)),
        "sale": ("SELECT 1 FROM local_business.sale WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "order": ("SELECT 1 FROM local_business.restaurant_order WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "kot": ("SELECT 1 FROM local_business.kot WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "transfer": ("SELECT 1 FROM local_business.transfer WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "connector": ("SELECT 1 FROM local_business.webhook_connector WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "customer": ("SELECT 1 FROM local_business.customer WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "menu_item": ("SELECT 1 FROM local_business.menu_item WHERE id=%s AND business_id=%s", (object_id, business_id)),
        "table": ("""SELECT 1 FROM local_business.restaurant_table t
                    JOIN local_business.branch b ON b.id=t.branch_id
                    WHERE t.id=%s AND b.business_id=%s""", (object_id, business_id)),
    }
    if kind not in queries:
        raise ValueError(f"unknown scoped object: {kind}")
    with koneksi() as conn:
        with conn.cursor() as cur:
            sql, params = queries[kind]
            cur.execute(sql, params)
            if not cur.fetchone():
                context = _current.get()
                _log.warning(
                    "tenant_authorization_denied user_id=%s business_id=%s object=%s object_id=%s",
                    context.user_id if context else "unknown", business_id, kind, object_id,
                )
                raise HTTPException(status_code=404, detail="Resource tidak ditemukan")


def assert_same_business(business_id: int, **objects: int | None) -> None:
    aliases = {"source_branch": "branch", "dest_branch": "branch"}
    for kind, object_id in objects.items():
        if object_id is not None:
            assert_object(aliases.get(kind, kind), int(object_id), business_id)


def provision(*, user_id: str, email: str, name: str, business_type: str = "RETAIL") -> dict[str, Any]:
    """Create one owner business, branch, and register transactionally."""
    clean_name = name.strip()
    if len(clean_name) < 2 or len(clean_name) > 160:
        raise HTTPException(status_code=422, detail="Nama bisnis harus 2-160 karakter")
    kind = business_type.upper()
    if kind not in {"RETAIL", "RESTAURANT", "HYBRID"}:
        raise HTTPException(status_code=422, detail="Jenis bisnis tidak valid")
    with koneksi() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT b.id, b.name, b.tenant_id FROM local_business.business b
                       JOIN local_business.business_membership bm ON bm.business_id=b.id
                       WHERE bm.user_id=%s AND bm.role='OWNER' AND bm.status='ACTIVE'
                       ORDER BY b.id LIMIT 1""", (user_id,)
                )
                existing = cur.fetchone()
                if existing:
                    return {"created": False, "business_id": existing["id"], "name": existing["name"]}
                cur.execute(
                    """INSERT INTO local_business.business
                       (tenant_id, code, name, business_type, owner_user_id)
                       VALUES (%s,%s,%s,%s,%s) RETURNING id, tenant_id, name""",
                    (f"user:{user_id}", f"CUSTOMER-{user_id[:8]}", clean_name, kind, user_id),
                )
                business = cur.fetchone()
                cur.execute(
                    """INSERT INTO local_business.business_membership
                       (business_id, user_id, role, status) VALUES (%s,%s,'OWNER','ACTIVE')""",
                    (business["id"], user_id),
                )
                cur.execute(
                    """INSERT INTO multichannel.warehouse (code, name, is_default)
                       VALUES (%s,%s,TRUE) RETURNING id""",
                    (f"WH-{user_id[:8]}", f"{clean_name} - Gudang Utama"),
                )
                warehouse_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO local_business.branch
                       (business_id, code, name, warehouse_id, branch_type)
                       VALUES (%s,'MAIN',%s,%s,%s) RETURNING id""",
                    (business["id"], f"{clean_name} - Utama", warehouse_id, kind),
                )
                branch_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO local_business.register (branch_id, code, name)
                       VALUES (%s,'MAIN','Kasir Utama') RETURNING id""", (branch_id,)
                )
                register_id = cur.fetchone()["id"]
    return {"created": True, "business_id": business["id"], "name": business["name"],
            "branch_id": branch_id, "register_id": register_id, "owner_user_id": user_id}
