"""Server Local Business Suite - /bisnis/ (PWA offline-first).

Serves the Local Business UI (Retail POS, Restaurant, Inventory, Transfers,
Reports, Dashboard) and its JSON API. Preserves /integrasi untouched.

Endpoints:
  GET  /bisnis/            PWA shell (HTML)
  GET  /bisnis/manifest    PWA manifest
  GET  /bisnis/sw.js       Service Worker
  GET  /bisnis/api/state   dashboard + business state
  GET  /bisnis/api/products
  GET  /bisnis/api/inventory
  GET  /bisnis/api/sales
  GET  /bisnis/api/transfers
  GET  /bisnis/api/restaurant
  GET  /bisnis/api/kitchen
  POST /bisnis/api/sale
  POST /bisnis/api/return
  POST /bisnis/api/transfer
  POST /bisnis/api/restaurant/order
  POST /bisnis/api/kitchen/status
  POST /bisnis/api/offline/sync
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse

sys.path.insert(0, "/opt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
from botconnector_multichannel.persistence import db
from botconnector_multichannel.persistence.db import koneksi as _pg
from botconnector_multichannel.local_business import (  # noqa
    core, inventory as inv, retail, returns, transfer, restaurant,
    offline, procurement, marketplace, reporting, intake, telegram_intake,
    tenant, telegram_registry as reg, crypto, bot_poller,
)

log = logging.getLogger("bc.bisnis.server")

async def get_user_id(request: Request):
    """Establish trusted admin or Core-customer tenant context."""
    return tenant.require_auth(request)


async def get_customer_entry(request: Request):
    """Allow entitled customers to reach onboarding before membership exists.

    A valid session that is NOT entitled to Business Suite is let through so the
    shell can show a customer-safe activation state instead of a raw 403.
    """
    try:
        return tenant.resolve(request, allow_unprovisioned=True)
    except HTTPException as exc:
        if exc.status_code == 401:
            return None
        if exc.status_code == 403:
            request.state.business_no_entitlement = True
            return None
        raise
APP = FastAPI(title="BotConnector Local Business", version="1.0.0")


@APP.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    """Customer-safe catch-all: never leak a stack trace / raw DB message.

    FastAPI already handles HTTPException and request-validation errors with
    their structured detail. Everything else becomes a generic customer-safe
    message while the original detail is preserved server-side for diagnosis.
    """
    import traceback
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.responses import JSONResponse as _JR

    if isinstance(exc, (_StarletteHTTPException, RequestValidationError)):
        return await _default_http_handler(request, exc)
    log.exception("bisnis_unhandled path=%s error=%s", request.url.path, exc)
    return _JR(
        status_code=500,
        content={"ok": False, "error": "Terjadi kesalahan pada sistem. Silakan coba lagi."},
    )


async def _default_http_handler(request: Request, exc: Exception):
    from starlette.exceptions import HTTPException as _StarletteHTTPException
    from starlette.responses import JSONResponse as _JR
    status = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", "Terjadi kesalahan.")
    return _JR(status_code=status, content={"detail": detail})


def _default_business():
    """Resolve the business from the trusted request context, never a client ID."""
    context = tenant.current_context()
    if context.business_id is None:
        return None
    return core.get_business(context.business_id)


def _context_tenant() -> str:
    return tenant.current_context().tenant_id


def _context_business_id() -> int:
    return tenant.require_business_id()


def _branch_map(business_id: int) -> dict:
    """branch_id -> warehouse_id."""
    return {b["id"]: b["warehouse_id"] for b in core.list_branch(business_id)}


# ============================================================ API
@APP.get("/bisnis/api/state", dependencies=[Depends(get_user_id)])
def state():
    biz = _default_business()
    if not biz:
        return {"ok": True, "business": None}
    branches = core.list_branch(biz["id"])
    dash = reporting.dashboard(biz["id"])
    return {"ok": True, "business": biz, "branches": branches,
            "dashboard": dash, "tenant": _context_tenant()}


def _onboarding_state(business_id: int) -> dict:
    """Derive real first-run completion state from production data.

    Each flag reflects genuine persisted state, never a frontend-only marker.
    """
    with db.koneksi() as c:
        cur = c.cursor()
        # 1. Profil bisnis: a meaningful profile exists when the business name
        #    is set (defaults to the user-chosen name) — treat as complete.
        cur.execute("SELECT name FROM local_business.business WHERE id=%s", (business_id,))
        biz_row = cur.fetchone()
        profil_done = bool(biz_row and biz_row["name"] and biz_row["name"].strip())

        # 2. Cabang: at least one valid ACTIVE branch.
        cur.execute(
            "SELECT count(*) AS n FROM local_business.branch WHERE business_id=%s AND status='ACTIVE'",
            (business_id,))
        branch_count = int(cur.fetchone()["n"] or 0)
        cabang_done = branch_count >= 1

        # 3. Produk: at least one active product bound to the business.
        cur.execute(
            """SELECT count(*) AS n FROM local_business.business_product
               WHERE business_id=%s AND active=TRUE""", (business_id,))
        product_count = int(cur.fetchone()["n"] or 0)
        produk_done = product_count >= 1

        # 4. Harga: at least one sellable product has a valid retail price.
        cur.execute(
            """SELECT count(*) AS n
               FROM local_business.business_product bp
               JOIN local_business.retail_selling_price rsp
                 ON rsp.business_id=bp.business_id
                AND rsp.master_sku_id=bp.master_sku_id
                AND rsp.active=TRUE AND rsp.selling_price>0
               WHERE bp.business_id=%s AND bp.active=TRUE""", (business_id,))
        price_count = int(cur.fetchone()["n"] or 0)
        harga_done = price_count >= 1

        # 5. Stok: initial inventory exists for at least one sellable product.
        cur.execute(
            """SELECT count(*) AS n
               FROM multichannel.inventory_balance ib
               JOIN local_business.branch br ON br.warehouse_id=ib.warehouse_id
               WHERE br.business_id=%s AND ib.on_hand>0""", (business_id,))
        stock_count = int(cur.fetchone()["n"] or 0)
        stok_done = stock_count >= 1

        # 6. Kasir/POS: at least one register + a genuine completed sale.
        cur.execute(
            """SELECT count(*) AS n
               FROM local_business.register r
               JOIN local_business.branch b ON b.id=r.branch_id
               WHERE b.business_id=%s""", (business_id,))
        register_count = int(cur.fetchone()["n"] or 0)
        cur.execute(
            """SELECT count(*) AS n FROM local_business.sale
               WHERE business_id=%s AND status='COMPLETED'""", (business_id,))
        sale_count = int(cur.fetchone()["n"] or 0)
        pos_done = register_count >= 1 and sale_count >= 1

        # 7. Telegram (optional): at least one destination/rule exists.
        cur.execute(
            """SELECT count(*) AS n FROM local_business.telegram_destination
               WHERE business_id=%s""", (business_id,))
        telegram_dest = int(cur.fetchone()["n"] or 0)
        cur.execute(
            """SELECT count(*) AS n FROM local_business.telegram_notification_rule
               WHERE business_id=%s""", (business_id,))
        telegram_rule = int(cur.fetchone()["n"] or 0)
        telegram_done = (telegram_dest + telegram_rule) >= 1

    first_sale_done = sale_count >= 1
    ready = profil_done and cabang_done and produk_done and harga_done \
        and stok_done and pos_done
    return {
        "profil": {"done": profil_done, "label": "Profil Bisnis"},
        "cabang": {"done": cabang_done, "label": "Cabang Pertama"},
        "produk": {"done": produk_done, "label": "Produk Pertama"},
        "harga": {"done": harga_done, "label": "Harga Jual"},
        "stok": {"done": stok_done, "label": "Stok Awal"},
        "pos": {"done": pos_done, "label": "Siapkan Kasir / POS"},
        "telegram": {"done": telegram_done, "label": "Hubungkan Telegram",
                     "optional": True},
        "first_sale": {"done": first_sale_done, "label": "Penjualan Pertama"},
        "ready": ready,
        "counts": {
            "branch": branch_count, "product": product_count,
            "price": price_count, "stock": stock_count,
            "register": register_count, "sale": sale_count,
        },
    }


@APP.get("/bisnis/api/onboarding", dependencies=[Depends(get_user_id)])
def onboarding_state():
    biz = _default_business()
    if not biz:
        return {"ok": True, "business": None, "onboarding": None}
    return {"ok": True, "business": biz, "onboarding": _onboarding_state(biz["id"])}


@APP.get("/bisnis/api/dashboard-v2", dependencies=[Depends(get_user_id)])
def dashboard_v2(days: int = 30):
    biz = _default_business()
    if not biz:
        return {"ok": True, "business": None}
    business_id = biz["id"]
    days = max(1, min(90, days))
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT id, code, name, branch_type, status, warehouse_id
               FROM local_business.branch
               WHERE business_id = %s
               ORDER BY id""",
            (business_id,)
        )
        branches = cur.fetchall()

        cur.execute(
            """SELECT COALESCE(SUM(total), 0) AS total_sales,
                      COUNT(*) AS tx_count
               FROM local_business.sale
               WHERE business_id = %s AND status = 'COMPLETED'
                 AND created_at >= (now() - make_interval(days => %s))""",
            (business_id, days)
        )
        sales_agg = cur.fetchone()
        total_sales = float(sales_agg["total_sales"] or 0)
        tx_count = int(sales_agg["tx_count"] or 0)
        avg_ticket = round(total_sales / tx_count, 2) if tx_count > 0 else 0.0

        cur.execute(
            """WITH date_series AS (
                 SELECT generate_series(
                   date_trunc('day', now() - make_interval(days => %s - 1)),
                   date_trunc('day', now()),
                   '1 day'::interval
                 )::date AS d
               ),
               daily_sales AS (
                 SELECT date_trunc('day', created_at)::date AS d,
                        COALESCE(SUM(total), 0) AS daily_total,
                        COUNT(*) AS daily_count
                 FROM local_business.sale
                 WHERE business_id = %s AND status = 'COMPLETED'
                   AND created_at >= date_trunc('day', now() - make_interval(days => %s - 1))
                 GROUP BY date_trunc('day', created_at)::date
               )
               SELECT ds.d AS date_str,
                      COALESCE(s.daily_total, 0) AS sales,
                      COALESCE(s.daily_count, 0) AS transactions
               FROM date_series ds
               LEFT JOIN daily_sales s ON s.d = ds.d
               ORDER BY ds.d ASC""",
            (days, business_id, days)
        )
        timeseries = [
            {
                "date": str(row["date_str"]),
                "sales": float(row["sales"]),
                "transactions": int(row["transactions"]),
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """SELECT b.id AS branch_id, b.code, b.name, b.status,
                      COALESCE(SUM(s.total), 0) AS sales,
                      COUNT(s.id) AS transactions
               FROM local_business.branch b
               LEFT JOIN local_business.sale s ON s.branch_id = b.id AND s.status = 'COMPLETED'
                    AND s.created_at >= (now() - make_interval(days => %s))
               WHERE b.business_id = %s
               GROUP BY b.id, b.code, b.name, b.status
               ORDER BY b.id""",
            (days, business_id)
        )
        branch_perf = []
        for row in cur.fetchall():
            b_sales = float(row["sales"] or 0)
            b_tx = int(row["transactions"] or 0)
            branch_perf.append({
                "branch_id": row["branch_id"],
                "code": row["code"],
                "name": row["name"],
                "status": row["status"] or "ACTIVE",
                "sales": b_sales,
                "transactions": b_tx,
                "avg_ticket": round(b_sales / b_tx, 2) if b_tx > 0 else 0.0,
            })

        cur.execute(
            """SELECT count(*) AS n FROM local_business.restaurant_order
               WHERE business_id = %s AND status IN ('NEW','ACCEPTED','PREPARING','READY')""",
            (business_id,)
        )
        open_orders = int(cur.fetchone()["n"] or 0)

        cur.execute(
            """SELECT count(*) AS n FROM local_business.kot k
               JOIN local_business.restaurant_order o ON o.id = k.order_id
               WHERE o.business_id = %s AND k.status IN ('NEW','ACCEPTED','PREPARING')""",
            (business_id,)
        )
        pending_kot = int(cur.fetchone()["n"] or 0)

        cur.execute(
            """SELECT count(*) AS n FROM local_business.transfer
               WHERE business_id = %s AND status IN ('APPROVED','IN_TRANSIT')""",
            (business_id,)
        )
        active_transfers = int(cur.fetchone()["n"] or 0)

        cur.execute(
            """SELECT b.code AS branch_code, m.sku, ib.on_hand, ib.available
               FROM local_business.branch b
               JOIN multichannel.inventory_balance ib ON ib.warehouse_id = b.warehouse_id
               JOIN multichannel.master_sku m ON m.id = ib.master_sku_id
               WHERE b.business_id = %s AND ib.available <= 5
               ORDER BY ib.available ASC LIMIT 10""",
            (business_id,)
        )
        low_stock_items = cur.fetchall()
        low_stock_count = len(low_stock_items)

        cur.execute(
            """(
                 SELECT 'SALE' AS act_type, 'Penjualan Kasir' AS title,
                        'Struk #' || COALESCE(receipt_number,'') AS detail,
                        total AS amount, created_at
                 FROM local_business.sale
                 WHERE business_id = %s AND status = 'COMPLETED'
                 ORDER BY created_at DESC LIMIT 5
               ) UNION ALL (
                 SELECT 'RESTAURANT' AS act_type, 'Order Restoran' AS title,
                        'Order #' || COALESCE(order_number,'') || ' (' || status || ')' AS detail,
                        total AS amount, created_at
                 FROM local_business.restaurant_order
                 WHERE business_id = %s
                 ORDER BY created_at DESC LIMIT 5
               ) UNION ALL (
                 SELECT 'TRANSFER' AS act_type, 'Transfer Stok' AS title,
                        'Transfer #' || COALESCE(transfer_number,'') || ' (' || status || ')' AS detail,
                        0 AS amount, created_at
                 FROM local_business.transfer
                 WHERE business_id = %s
                 ORDER BY created_at DESC LIMIT 5
               )
               ORDER BY created_at DESC LIMIT 6""",
            (business_id, business_id, business_id)
        )
        recent_activities = [
            {
                "type": r["act_type"],
                "title": r["title"],
                "detail": r["detail"],
                "amount": float(r["amount"] or 0),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in cur.fetchall()
        ]

    return {
        "ok": True,
        "business": biz,
        "days": days,
        "kpis": {
            "sales": total_sales,
            "transactions": tx_count,
            "average_ticket": avg_ticket,
            "active_branches": len(branches),
        },
        "timeseries": timeseries,
        "branches": branch_perf,
        "operations": {
            "open_restaurant_orders": open_orders,
            "pending_kitchen_orders": pending_kot,
            "active_transfers": active_transfers,
            "low_stock_count": low_stock_count,
            "low_stock_items": low_stock_items,
        },
        "recent_activities": recent_activities,
        "tenant": _context_tenant(),
    }


@APP.get("/bisnis/api/products", dependencies=[Depends(get_user_id)])
def products():
    business_id = _context_business_id()
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.id, m.sku, p.name, p.category, m.barcode, m.safety_stock
               FROM local_business.business_product bp
               JOIN multichannel.master_sku m ON m.id=bp.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               WHERE bp.business_id=%s AND bp.active=TRUE ORDER BY m.sku""",
            (business_id,))
        return {"ok": True, "products": cur.fetchall()}


@APP.post("/bisnis/api/products", dependencies=[Depends(tenant.require_role("owner", "admin", "manager"))])
async def create_product(request: Request):
    """Create a catalog SKU and bind it to the caller's business only."""
    body = await request.json()
    business_id = _context_business_id()
    sku = str(body.get("sku") or "").strip()
    name = str(body.get("name") or "").strip()
    if not sku or not name:
        raise HTTPException(status_code=422, detail="sku dan nama wajib diisi")
    with db.koneksi() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO multichannel.product (name, category)
                       VALUES (%s,%s) ON CONFLICT (name, category)
                       DO UPDATE SET updated_at=now() RETURNING id""",
                    (name, str(body.get("category") or "")),
                )
                product_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO multichannel.master_sku (sku, product_id, barcode)
                       VALUES (%s,%s,%s) RETURNING id""",
                    (sku, product_id, str(body.get("barcode") or "")),
                )
                master_sku_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO local_business.business_product (business_id, master_sku_id)
                       VALUES (%s,%s) RETURNING business_id, master_sku_id""",
                    (business_id, master_sku_id),
                )
                if float(body.get("price", 0) or 0) > 0:
                    cur.execute(
                        """INSERT INTO local_business.retail_selling_price
                           (business_id, master_sku_id, selling_price, currency, active)
                           VALUES (%s,%s,%s,'IDR',TRUE)
                           ON CONFLICT (business_id, master_sku_id)
                           WHERE active=TRUE DO UPDATE
                           SET selling_price=EXCLUDED.selling_price, active=TRUE""",
                        (business_id, master_sku_id, float(body.get("price", 0))),
                    )
    return {"ok": True, "master_sku_id": master_sku_id, "business_id": business_id}


@APP.get("/bisnis/api/inventory", dependencies=[Depends(get_user_id)])
def inventory():
    biz = _default_business()
    if not biz:
        return {"ok": True, "stock": []}
    return {"ok": True, "stock": reporting.stock_by_branch(biz["id"]),
            "global": reporting.global_stock(biz["id"]),
            "low": reporting.low_stock(biz["id"])}


@APP.post("/bisnis/api/stock/receive", dependencies=[Depends(tenant.require_role("owner", "admin", "manager"))])
async def stock_receive(request: Request):
    """Receive initial/additional stock for one sellable product at the first
    retail branch. Idempotent per idempotency_key. Focused onboarding helper."""
    body = await request.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    master_sku_id = int(body.get("master_sku_id") or 0)
    quantity = int(body.get("quantity") or 0)
    if master_sku_id <= 0 or quantity <= 0:
        raise HTTPException(status_code=422, detail="master_sku_id dan quantity wajib > 0")
    tenant.assert_object("product", master_sku_id, biz["id"])
    branch = core.list_branch(biz["id"])
    b = branch[0] if branch else None
    if not b:
        raise HTTPException(status_code=409, detail="Belum ada cabang aktif")
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT sku FROM multichannel.master_sku WHERE id=%s", (master_sku_id,))
        row = cur.fetchone()
    sku = row["sku"] if row else ""
    try:
        r = inv.receive_stock(
            tenant_id=_context_tenant(), business_id=biz["id"],
            branch_id=b["id"], warehouse_id=b["warehouse_id"],
            master_sku_id=master_sku_id, sku=sku, quantity=quantity,
            reference=f"receive:{biz['id']}:{master_sku_id}",
            note="Stok awal onboarding", actor="bisnis-ui",
            idempotency_key=f"receive:{biz['id']}:{master_sku_id}:{quantity}",
            source_document="ONBOARDING")
        return {"ok": True, **r}
    except inv.StokTidakCukup as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)


@APP.post("/bisnis/api/price", dependencies=[Depends(tenant.require_role("owner", "admin", "manager"))])
async def set_price(request: Request):
    """Set or update the retail selling price of one sellable product."""
    body = await request.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    master_sku_id = int(body.get("master_sku_id") or 0)
    price = float(body.get("price") or 0)
    if master_sku_id <= 0 or price <= 0:
        raise HTTPException(status_code=422, detail="master_sku_id dan price wajib > 0")
    tenant.assert_object("product", master_sku_id, biz["id"])
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.retail_selling_price
               (business_id, master_sku_id, selling_price, currency, active)
               VALUES (%s,%s,%s,'IDR',TRUE)
               ON CONFLICT (business_id, master_sku_id) DO UPDATE
               SET selling_price=EXCLUDED.selling_price, active=TRUE, updated_at=now()""",
            (biz["id"], master_sku_id, price))
    return {"ok": True, "master_sku_id": master_sku_id, "price": price}


@APP.get("/bisnis/api/sales", dependencies=[Depends(get_user_id)])
def sales():
    biz = _default_business()
    if not biz:
        return {"ok": True, "sales": []}
    out = []
    for b in core.list_branch(biz["id"]):
        for s in retail.list_sales(b["id"], limit=50):
            out.append(s)
    return {"ok": True, "sales": out}


@APP.get("/bisnis/api/transfers", dependencies=[Depends(get_user_id)])
def transfers():
    biz = _default_business()
    if not biz:
        return {"ok": True, "transfers": []}
    return {"ok": True, "transfers": transfer.list_transfers(biz["id"]),
            "report": reporting.transfer_report(biz["id"])}


@APP.get("/bisnis/api/restaurant", dependencies=[Depends(get_user_id)])
def restaurant_menu():
    biz = _default_business()
    if not biz:
        return {"ok": True, "menu": [], "orders": []}
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT mi.id, mi.name, mi.price, mi.is_stocked, mc.name AS category
               FROM local_business.menu_item mi
               LEFT JOIN local_business.menu_category mc ON mc.id=mi.category_id
               WHERE mi.business_id=%s AND mi.active=TRUE ORDER BY mi.name""",
            (biz["id"],))
        menu = cur.fetchall()
    orders = []
    for b in core.list_branch(biz["id"]):
        orders += restaurant.list_restaurant_orders(b["id"])
    return {"ok": True, "menu": menu, "orders": orders}


@APP.get("/bisnis/api/kitchen", dependencies=[Depends(get_user_id)])
def kitchen():
    biz = _default_business()
    if not biz:
        return {"ok": True, "kots": []}
    kots = []
    for b in core.list_branch(biz["id"]):
        kots += restaurant.list_kot(b["id"])
    return {"ok": True, "kots": kots}


@APP.post("/bisnis/api/sale", dependencies=[Depends(get_user_id)])
async def api_sale(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    tenant.assert_same_business(
        biz["id"], branch=body.get("branch_id"), register=body.get("register_id"),
        cashier=body.get("cashier_id"), warehouse=body.get("warehouse_id"),
        customer=body.get("customer_id"),
    )
    for line in body.get("lines", []):
        tenant.assert_object("product", int(line["master_sku_id"]), biz["id"])
    try:
        r = retail.create_sale(
            tenant_id=_context_tenant(), business_id=biz["id"],
            branch_id=body["branch_id"], register_id=body["register_id"],
            cashier_id=body.get("cashier_id"), warehouse_id=body["warehouse_id"],
            lines=body["lines"], tender_method=body.get("tender_method", "CASH"),
            amount_tendered=body.get("amount_tendered", 0),
            customer_id=body.get("customer_id"),
            shift_id=body.get("shift_id"), discount=body.get("discount", 0),
            tax_amount=body.get("tax_amount", 0),
            client_event_id=body.get("client_event_id", ""),
            device_id=body.get("device_id", ""),
            created_at_client=body.get("created_at_client"))
        return {"ok": True, "sale": r}
    except inv.StokTidakCukup as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)


@APP.post("/bisnis/api/return", dependencies=[Depends(get_user_id)])
async def api_return(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    tenant.assert_same_business(biz["id"], branch=body.get("branch_id"), sale=body.get("sale_id"))
    try:
        r = returns.create_return(
            tenant_id=_context_tenant(), business_id=biz["id"], branch_id=body["branch_id"],
            warehouse_id=body["warehouse_id"], sale_id=body["sale_id"],
            reason=body.get("reason", ""), actor=tenant.current_context().user_id,
            client_event_id=body.get("client_event_id", ""),
            device_id=body.get("device_id", ""))
        return {"ok": True, "return": r}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@APP.post("/bisnis/api/transfer", dependencies=[Depends(get_user_id)])
async def api_transfer(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    tenant.assert_same_business(
        biz["id"], source_branch=body.get("source_branch_id"),
        dest_branch=body.get("dest_branch_id"),
    )
    for line in body.get("lines", []):
        tenant.assert_object("product", int(line["master_sku_id"]), biz["id"])
    try:
        r = transfer.create_transfer(
            tenant_id=_context_tenant(), business_id=biz["id"],
            source_branch_id=body["source_branch_id"],
            dest_branch_id=body["dest_branch_id"], lines=body["lines"],
            note=body.get("note", ""), actor=tenant.current_context().user_id)
        return {"ok": True, "transfer": r}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@APP.post("/bisnis/api/restaurant/order", dependencies=[Depends(get_user_id)])
async def api_restaurant_order(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    tenant.assert_same_business(
        biz["id"], branch=body.get("branch_id"), register=body.get("register_id"),
        cashier=body.get("cashier_id"), warehouse=body.get("warehouse_id"),
        table=body.get("table_id"),
    )
    for line in body.get("lines", []):
        tenant.assert_object("menu_item", int(line["menu_item_id"]), biz["id"])
    try:
        r = restaurant.create_restaurant_order(
            tenant_id=_context_tenant(), business_id=biz["id"], branch_id=body["branch_id"],
            register_id=body["register_id"], cashier_id=body.get("cashier_id"),
            warehouse_id=body["warehouse_id"], lines=body["lines"],
            order_type=body.get("order_type", "DINE_IN"),
            table_id=body.get("table_id"), guest_count=body.get("guest_count", 1),
            note=body.get("note", ""), client_event_id=body.get("client_event_id", ""),
            device_id=body.get("device_id", ""))
        return {"ok": True, "order": r}
    except restaurant.StokTidakCukup as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=409)


@APP.post("/bisnis/api/kitchen/status", dependencies=[Depends(get_user_id)])
async def api_kitchen_status(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    tenant.assert_object("kot", int(body["kot_id"]), biz["id"])
    try:
        r = restaurant.set_kot_status(
            kot_id=body["kot_id"], status=body["status"],
            actor=tenant.current_context().user_id, business_id=biz["id"])
        return {"ok": True, "kot": r}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@APP.post("/bisnis/api/offline/sync", dependencies=[Depends(get_user_id)])
async def api_offline_sync(req: Request):
    body = await req.json()
    biz = _default_business()
    if not biz:
        return JSONResponse({"ok": False, "error": "belum ada business"}, status_code=400)
    wmap = _branch_map(biz["id"])
    r = offline.replay_offline_queue(biz["id"], warehouse_map=wmap)
    return {"ok": True, "sync": r}


@APP.get("/bisnis/api/reports", dependencies=[Depends(get_user_id)])
def reports(days: int = 30):
    """Runtime-backed business reports (restaurant + retail + channel + branches)."""
    from botconnector_multichannel.local_business import business_reporting as BR
    biz = _default_business()
    if not biz:
        return {"ok": True, "reports": None}
    days = max(1, min(365, days))
    return {"ok": True, "reports": {
        "restaurant": BR.restaurant_sales_report(biz["id"], days=days),
        "retail": BR.retail_sales_report(biz["id"], days=days),
        "channel": BR.channel_report(biz["id"], days=days),
        "branches": reporting.sales_by_branch(biz["id"], days=days),
        "days": days,
    }}


@APP.get("/bisnis/api/pos", dependencies=[Depends(get_user_id)])
def pos():
    """POS data: products + registers + branches + shifts (read for cart UI)."""
    biz = _default_business()
    if not biz:
        return {"ok": True, "business": None}
    branches = core.list_branch(biz["id"])
    registers = []
    for b in branches:
        with db.koneksi() as c:
            cur = c.cursor()
            cur.execute("SELECT id, code, name FROM local_business.register WHERE branch_id=%s", (b["id"],))
            registers += cur.fetchall()
    return {"ok": True, "business": biz, "branches": branches, "registers": registers,
            "products": _product_list(biz["id"])}


def _product_list(business_id):
    with db.koneksi() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT m.id AS master_sku_id, m.sku, p.name, p.category, m.barcode,
                      m.safety_stock, rsp.selling_price AS price,
                      mi.reporting_category, mi.id AS menu_item_id,
                      COALESCE((SELECT SUM(ib.on_hand) FROM multichannel.inventory_balance ib
                                JOIN local_business.branch br ON br.warehouse_id=ib.warehouse_id
                                WHERE br.business_id=%s AND ib.master_sku_id=m.id), 0) AS stock_quantity
               FROM local_business.business_product bp
               JOIN multichannel.master_sku m ON m.id=bp.master_sku_id
               JOIN multichannel.product p ON p.id=m.product_id
               LEFT JOIN local_business.retail_selling_price rsp ON rsp.master_sku_id=m.id AND rsp.business_id=%s AND rsp.active=TRUE
               LEFT JOIN local_business.menu_item mi ON mi.stocked_sku_id=m.id AND mi.business_id=%s
               WHERE bp.business_id=%s AND bp.active=TRUE
               ORDER BY m.sku""",
             (business_id, business_id, business_id, business_id))
        return cur.fetchall()


@APP.get("/bisnis/api/barcode", dependencies=[Depends(get_user_id)])
def barcode_lookup(barcode: str = ""):
    from botconnector_multichannel.local_business import barcode as bc
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return bc.lookup_barcode(business_id=biz["id"], barcode=barcode)


@APP.get("/bisnis/api/orders", dependencies=[Depends(get_user_id)])
def orders():
    biz = _default_business()
    if not biz:
        return {"ok": True, "sales": [], "restaurant_orders": []}
    sales = []
    for b in core.list_branch(biz["id"]):
        sales += retail.list_sales(b["id"], limit=100)
    orders = []
    for b in core.list_branch(biz["id"]):
        orders += restaurant.list_restaurant_orders(b["id"])
    return {"ok": True, "sales": sales, "orders": orders}


@APP.get("/bisnis/api/business-integrasi", dependencies=[Depends(get_user_id)])
def business_integrasi():
    """Operational (internal) integration state - no secret values, no external blockers wording."""
    from botconnector_multichannel.local_business.connectors import build_delivery_registry
    from botconnector_multichannel.local_business.pos import build_pos_registry
    delivery = [c.status_report() for c in build_delivery_registry().all()]
    pos = [c.status_report() for c in build_pos_registry().all()]
    # public-friendly status mapping
    def pub(s):
        return "SEGERA_HADIR" if s == "BLOCKED_EXTERNAL" else "TERSEDIA"
    return {
        "ok": True,
        "delivery": [{"provider": d["provider"], "status": pub(d["real_status"]),
                      "auth": d.get("auth", "")} for d in delivery],
        "pos": [{"provider": p["provider"], "status": pub(p["real_status"]),
                 "auth": p.get("auth", "")} for p in pos],
    }


@APP.get("/bisnis/api/sale/{sale_id}", dependencies=[Depends(get_user_id)])
def sale_detail(sale_id: int):
    tenant.assert_object("sale", sale_id, _context_business_id())
    return {"ok": True, "sale": retail.get_sale(sale_id, _context_business_id())}


@APP.get("/bisnis/api/receipt/{sale_id}", dependencies=[Depends(get_user_id)])
def receipt(sale_id: int):
    from botconnector_multichannel.local_business import print_receipt as pr
    tenant.assert_object("sale", sale_id, _context_business_id())
    s = pr.get_receipt_data(sale_id)
    if not s:
        return JSONResponse({"ok": False, "error": "sale tidak ada"}, status_code=404)
    return HTMLResponse(pr.render_receipt_html(
        business_name=s["business_name"], branch_name=s["branch_name"],
        receipt_number=s["receipt_number"], cashier=s["cashier_name"] or "",
        lines=s["lines"], subtotal=s["subtotal"], discount=s["discount"],
        tax_amount=s["tax_amount"], total=s["total"],
        tender_method=s["tender_method"], amount_tendered=s["amount_tendered"],
        change_due=s["change_due"], timestamp=str(s["created_at"])))


@APP.get("/bisnis/manifest")
def manifest():
    return JSONResponse({
        "name": "BotConnector Local Business",
        "short_name": "BC Bisnis",
        "start_url": "/bisnis/",
        "display": "standalone",
        "background_color": "#f8fafc",
        "theme_color": "#f8fafc",
        "icons": [{"src": "/favicon.ico", "type": "image/x-icon"}],
    })


@APP.get("/bisnis/sw.js")
def business_service_worker_retirement():
    """
    Temporary retirement worker.

    BC Bisnis is an authenticated multi-tenant application.
    The previous worker used broad cache-first handling under /bisnis/
    and could cache authenticated API GET responses.

    This worker intentionally:
    - does NOT intercept fetch requests
    - removes only BC Bisnis caches
    - unregisters itself
    """
    from starlette.responses import Response

    script = r"""
self.addEventListener('install', event => {
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();

    await Promise.all(
      keys
        .filter(key => {
          const k = String(key).toLowerCase();
          return (
            k.startsWith('bc-bisnis') ||
            k.startsWith('botconnector-bisnis') ||
            k.includes('bc-bisnis-')
          );
        })
        .map(key => caches.delete(key))
    );

    await self.clients.claim();
    await self.registration.unregister();
  })());
});

/*
 * Deliberately NO fetch event handler.
 * Network/auth remains authoritative.
 */
"""

    return Response(
        content=script,
        media_type="application/javascript",
        headers={
            "Cache-Control":
                "no-store, no-cache, must-revalidate, max-age=0",
        },
    )



# Customer entry/provisioning is deliberately separate from the admin pilot.
_NO_ENTITLEMENT_HTML = """<!doctype html><html lang='id'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Business Suite — BotConnector</title>
<style>
:root{--indigo:#5B5FEF;--ink:#101828;--muted:#667085;--bg:#F6F7FB;--border:#E7E9F2;--ok:#22C55E;--ok-soft:#e8f9ef}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;display:grid;place-items:center;padding:24px;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid var(--border);border-radius:24px;max-width:520px;width:100%;padding:40px;box-shadow:0 12px 36px rgba(11,16,32,0.05)}
.eyebrow{display:inline-flex;align-items:center;gap:8px;color:var(--indigo);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.eyebrow::before{content:"";width:18px;height:2px;background:var(--indigo);border-radius:2px}
h1{font-size:26px;font-weight:850;letter-spacing:-.03em;margin:14px 0 10px}
p{font-size:14px;color:var(--muted);line-height:1.6;margin-bottom:24px}
.badge{display:inline-flex;align-items:center;gap:6px;background:var(--ok-soft);color:var(--ok);padding:6px 14px;border-radius:99px;font-size:12px;font-weight:800;margin-bottom:20px}
.badge span{width:7px;height:7px;border-radius:50%;background:var(--ok)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 22px;border-radius:11px;background:var(--indigo);color:#fff;font-size:13.5px;font-weight:750;text-decoration:none;border:1px solid transparent;cursor:pointer;box-shadow:0 6px 16px rgba(91,95,239,.22)}
.btn:hover{background:#4a4edb}
.btn-line{background:#fff;color:#344054;border-color:var(--border);box-shadow:none;margin-left:10px}
.btn-line:hover{border-color:#b9bdcb;background:#fafafa}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}
a.back{display:inline-block;margin-top:22px;font-size:13px;color:var(--muted);text-decoration:none;font-weight:600}
a.back:hover{color:var(--indigo)}
</style>
</head><body><div class="card">
<div class="eyebrow">BUSINESS SUITE</div>
<h1>Business Suite belum aktif di akun Anda</h1>
<p>Untuk mulai mengoperasikan toko, kasir POS, inventori, dan laporan, Business Suite perlu diaktifkan terlebih dahulu pada akun BotConnector Anda.</p>
<span class="badge"><span></span> Perlu Aktivasi</span>
<div class="actions">
<a class="btn" href="/my-products">Buka Produk Saya</a>
<a class="btn btn-line" href="/">Ke Beranda BotConnector</a>
</div>
</div></body></html>
"""

_ONBOARDING_HTML = """<!doctype html><html lang='id'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Siapkan Business Suite</title>
<style>body{font:16px system-ui;max-width:560px;margin:8vh auto;padding:24px;color:#172033}input,select,button{display:block;width:100%;padding:12px;margin:10px 0;box-sizing:border-box}button{background:#172033;color:white;border:0;border-radius:6px}</style>
<h1>Siapkan Business Suite</h1><p>Buat bisnis pertama Anda. Data ini tidak terkait dengan pilot internal.</p>
<form id='f'><input name='name' required minlength='2' maxlength='160' placeholder='Nama bisnis'><select name='business_type'><option>RETAIL</option><option>RESTAURANT</option><option>HYBRID</option></select><button>Mulai Business Suite</button></form><p id='e'></p>
<script>f.onsubmit=async e=>{e.preventDefault();let r=await fetch('/bisnis/api/provision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(f)))});let d=await r.json();if(!r.ok){document.querySelector('#e').textContent=d.detail||'Gagal';return}location.href='/bisnis/';}</script>
"""

@APP.post("/bisnis/api/provision")
async def provision_business(request: Request):
    context = tenant.resolve(request, allow_unprovisioned=True)
    if context.is_admin:
        raise HTTPException(status_code=403, detail="Gunakan alur admin untuk pilot")
    body = await request.json()
    result = tenant.provision(
        user_id=context.user_id,
        email=context.email,
        name=str(body.get("name") or ""),
        business_type=str(body.get("business_type") or "RETAIL"),
    )
    return {"ok": True, **result}


# BC_BISNIS_SHELL_ROUTES_CUSTOMER_V1
@APP.get("/bisnis/", response_class=HTMLResponse, dependencies=[Depends(get_customer_entry)])
@APP.get("/bisnis", response_class=HTMLResponse, dependencies=[Depends(get_customer_entry)])
def halaman(request: Request):
    context = (
        request.state.business_context
        if hasattr(request.state, "business_context")
        else None
    )
    # Logged-in but not entitled to Business Suite: show an activation state
    # rather than silently redirecting to login.
    if context is None and getattr(request.state, "business_no_entitlement", False):
        return HTMLResponse(_NO_ENTITLEMENT_HTML)
    if context is None:
        return RedirectResponse("/login?next=%2Fbisnis%2F", status_code=303)
    if context.business_id is None:
        return HTMLResponse(_ONBOARDING_HTML)
    return _HTML


@APP.get("/health")
@APP.get("/bisnis/api/health")
def health():
    db_ok = False
    try:
        with _pg() as c:
            cur = c.cursor()
            cur.execute("SELECT 1")
            db_ok = bool(cur.fetchone())
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "service": "botconnector-business-suite",
        "database": "connected" if db_ok else "disconnected",
    }


@APP.get("/bisnis/api/telegram/health")
def telegram_health():
    reg_ok = False
    try:
        with _pg() as c:
            cur = c.cursor()
            cur.execute("SELECT COUNT(*) FROM local_business.telegram_bot")
            reg_ok = True
    except Exception:
        reg_ok = False
    return {
        "ok": reg_ok,
        "service": "botconnector-telegram-v2",
        "registry": "ready" if reg_ok else "unavailable",
    }


# ============================================================ Intake Engine API
def _resolve_intake_scope(request: Request):
    """Resolve default business + first retail branch/warehouse for intake."""
    biz = _default_business()
    if not biz:
        return None, None
    branch = core.list_branch(biz["id"])
    b = branch[0] if branch else None
    return biz, b


@APP.post("/bisnis/api/intake/draft", dependencies=[Depends(get_user_id)])
async def intake_draft(request: Request):
    """UPLOAD -> DETECT -> MAP -> VALIDATE -> PREVIEW (no mutation)."""
    biz, _ = _resolve_intake_scope(request)
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    form = await request.form()
    file = form.get("file")
    if file is None:
        return {"ok": False, "error": "file diperlukan"}
    content = await file.read()
    filename = getattr(file, "filename", "") or ""
    fmt = "XLSX" if filename.lower().endswith((".xlsx", ".xlsm")) else "CSV"
    idem = form.get("idempotency_key", "") or ""
    return intake.create_draft(
        business_id=biz["id"], source=fmt, filename=filename, format=fmt,
        content=content, idempotency_key=idem, actor="bisnis-ui")


@APP.post("/bisnis/api/intake/confirm", dependencies=[Depends(get_user_id)])
async def intake_confirm(request: Request):
    body = await request.json()
    biz, br = _resolve_intake_scope(request)
    if not biz or not br:
        return {"ok": False, "error": "belum ada business/branch"}
    res = intake.confirm_batch(
        batch_id=body.get("batch_id", ""), business_id=biz["id"],
        tenant_id=_context_tenant(), branch_id=br["id"], warehouse_id=br["warehouse_id"],
        actor="biz-ui")
    return res


@APP.get("/bisnis/api/intake/history", dependencies=[Depends(get_user_id)])
def intake_history():
    biz = _default_business()
    if not biz:
        return {"ok": True, "batches": []}
    return {"ok": True, "batches": intake.history(biz["id"])}


@APP.post("/bisnis/api/intake/mapping", dependencies=[Depends(get_user_id)])
async def intake_mapping(request: Request):
    """Return detected header mapping for a file without persisting."""
    form = await request.form()
    file = form.get("file")
    if file is None:
        return {"ok": False, "error": "no file"}
    content = await file.read()
    filename = getattr(file, "filename", "") or ""
    fmt = "XLSX" if filename.endswith((".xlsx", ".xlsm")) else "CSV"
    rows = intake.parse_rows(content, fmt)
    headers = list(rows[0].keys()) if rows else []
    return {"ok": True, "headers": headers, "mapping": intake.auto_map(headers)}


@APP.post("/bisnis/api/intake/telegram/draft", dependencies=[Depends(get_user_id)])
async def telegram_draft(request: Request):
    form = await request.form()
    file = form.get("file")
    if file is None:
        return {"ok": False, "error": "no file"}
    content = await file.read()
    filename = getattr(file, "filename", "") or ""
    fmt = "XLSX" if filename.endswith((".xlsx", ".xlsm")) else "CSV"
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return telegram_intake.submit_intake_draft(
        business_id=biz["id"], telegram_user_id=0, owner_id=0,
        format=fmt, filename=filename, content=content)


def _telegram_public_runtime():
    """Safe Telegram pairing metadata for the authenticated BC Bisnis UI.

    Never returns or reads the Bot API token. Runtime readiness is based on
    the dedicated systemd poller plus a public-safe username file generated
    from a previously verified getMe call.
    """
    import re as _re
    import subprocess as _subprocess
    from pathlib import Path as _Path

    username = ""
    cfg = _Path("/etc/botconnector/bisnis-telegram-public.env")

    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("BC_BISNIS_TELEGRAM_BOT_USERNAME="):
                username = line.split("=", 1)[1].strip().lstrip("@")
                break
    except Exception:
        username = ""

    try:
        active = (
            _subprocess.run(
                [
                    "systemctl",
                    "is-active",
                    "--quiet",
                    "botconnector-bisnis-telegram.service",
                ],
                stdout=_subprocess.DEVNULL,
                stderr=_subprocess.DEVNULL,
                timeout=3,
            ).returncode == 0
        )
    except Exception:
        active = False

    valid_username = bool(
        username
        and _re.fullmatch(r"[A-Za-z0-9_]{5,64}", username)
    )

    return {
        "active": bool(active and valid_username),
        "bot_username": username if valid_username else "",
        "connectivity": (
            "ENABLED"
            if active and valid_username
            else "UNAVAILABLE"
        ),
    }


@APP.get("/bisnis/api/intake/telegram/status", dependencies=[Depends(get_user_id)])
@APP.get("/bisnis/api/telegram/status", dependencies=[Depends(get_user_id)])
def telegram_status():
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    runtime = _telegram_public_runtime()
    bots = reg.list_business_bots(biz["id"])
    dests = reg.list_destinations(biz["id"])
    st = telegram_intake.pairing_status(biz["id"])
    return {
        "ok": True,
        "global_bot": {
            "username": runtime.get("bot_username", ""),
            "active": runtime.get("active", False),
            "connectivity": runtime.get("connectivity", "UNAVAILABLE"),
        },
        "paired": st["paired"],
        "telegram_user_id": st["telegram_user_id"],
        "byob_bots": bots,
        "destinations": dests,
        "connectivity": runtime["connectivity"],
        "bot_username": runtime["bot_username"],
    }


@APP.get("/bisnis/api/intake/telegram/owner-status", dependencies=[Depends(get_user_id)])
def telegram_owner_status():
    return telegram_status()


@APP.post("/bisnis/api/intake/telegram/pair", dependencies=[Depends(get_user_id)])
@APP.post("/bisnis/api/telegram/pair", dependencies=[Depends(get_user_id)])
def telegram_pair():
    """Create a one-time pairing token and a real Telegram deep link."""
    import re as _re

    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}

    runtime = _telegram_public_runtime()
    if not runtime["active"]:
        return {
            "ok": False,
            "error": "Bot Telegram belum aktif",
        }

    ctx = tenant.current_context()
    res = telegram_intake.create_pairing_token(
        owner_id=biz["id"],
        business_id=biz["id"],
        core_user_id=ctx.user_id,
    )

    raw = str(res["raw_token"])
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw):
        return {
            "ok": False,
            "error": "Format token pairing tidak valid",
        }

    username = runtime["bot_username"]
    return {
        "ok": True,
        "pairing_token": raw,
        "expires_at": str(res["expires_at"]),
        "bot_username": username,
        "pairing_url": "https://t.me/" + username + "?start=" + raw,
    }


@APP.post("/bisnis/api/intake/telegram/unpair", dependencies=[Depends(get_user_id)])
@APP.post("/bisnis/api/telegram/unpair", dependencies=[Depends(get_user_id)])
def telegram_unpair():
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return telegram_intake.unpair(biz["id"])


# ------------------------------------------------------------ BYOB Bot Management APIs
@APP.get("/bisnis/api/telegram/bots", dependencies=[Depends(get_user_id)])
def list_bots_api():
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return {"ok": True, "bots": reg.list_business_bots(biz["id"])}


@APP.post("/bisnis/api/telegram/bots", dependencies=[Depends(get_user_id)])
async def add_byob_bot_api(request: Request):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    body = await request.json()
    token = (body.get("bot_token") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    ctx = tenant.current_context()
    return reg.register_byob_bot(
        business_id=biz["id"],
        raw_token=token,
        display_name=display_name,
        created_by_core_user_id=ctx.user_id,
    )


@APP.post("/bisnis/api/telegram/bots/{bot_id}/test", dependencies=[Depends(get_user_id)])
def test_byob_bot_api(bot_id: int):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.telegram_bot WHERE id=%s AND business_id=%s", (bot_id, biz["id"]))
        bot = cur.fetchone()
    if not bot:
        return {"ok": False, "error": "Bot tidak ditemukan"}
    try:
        client = reg.get_bot_client(bot)
        me = client.get_me()
        wh = client.get_webhook_info()
        client.close()
        return {
            "ok": True,
            "me": {"id": me.get("id"), "username": me.get("username"), "first_name": me.get("first_name")},
            "webhook": {
                "url": wh.get("url"),
                "pending_update_count": wh.get("pending_update_count", 0),
                "last_error_message": wh.get("last_error_message"),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": f"Uji koneksi gagal: {exc}"}


@APP.delete("/bisnis/api/telegram/bots/{bot_id}", dependencies=[Depends(get_user_id)])
def delete_byob_bot_api(bot_id: int):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return reg.delete_bot(biz["id"], bot_id)


# ------------------------------------------------------------ Destination & Rules APIs
@APP.get("/bisnis/api/telegram/destinations", dependencies=[Depends(get_user_id)])
def list_destinations_api():
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return {"ok": True, "destinations": reg.list_destinations(biz["id"])}


@APP.post("/bisnis/api/telegram/destinations/pair", dependencies=[Depends(get_user_id)])
async def destination_pair_api(request: Request):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    body = await request.json()
    dest_type = body.get("destination_type", "PRIVATE").upper()
    telegram_bot_id = body.get("telegram_bot_id")
    branch_id = body.get("branch_id")
    purpose = body.get("purpose", "GENERAL")
    ctx = tenant.current_context()

    bot_id_int = None
    if telegram_bot_id is not None and str(telegram_bot_id).strip().lower() not in ("", "0", "global", "null", "none"):
        try:
            bot_id_int = int(telegram_bot_id)
        except (ValueError, TypeError):
            return {"ok": False, "error": "ID bot tidak valid"}

    return reg.create_destination_pairing(
        business_id=biz["id"],
        core_user_id=ctx.user_id,
        telegram_bot_id=bot_id_int,
        destination_type=dest_type,
        branch_id=int(branch_id) if branch_id else None,
        purpose=purpose,
    )


@APP.post("/bisnis/api/telegram/destinations/{dest_id}/rules", dependencies=[Depends(get_user_id)])
async def set_destination_rules_api(dest_id: int, request: Request):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    body = await request.json()
    rules = body.get("rules", [])
    return reg.set_destination_rules(biz["id"], dest_id, rules)


@APP.delete("/bisnis/api/telegram/destinations/{dest_id}", dependencies=[Depends(get_user_id)])
def delete_destination_api(dest_id: int):
    biz = _default_business()
    if not biz:
        return {"ok": False, "error": "belum ada business"}
    return reg.delete_destination(biz["id"], dest_id)


# ------------------------------------------------------------ BYOB Webhook Receiver
@APP.post("/bisnis/api/webhooks/telegram/{public_bot_id}")
async def telegram_byob_webhook(public_bot_id: str, request: Request):
    """Customer-owned BYOB Telegram bot webhook receiver.

    Uses constant-time validation of X-Telegram-Bot-Api-Secret-Token.
    """
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    bot = reg.get_bot_by_public_id(public_bot_id)
    if not bot or bot.get("status") != "ACTIVE":
        raise HTTPException(status_code=404, detail="Bot not found")

    stored_hash = bot.get("webhook_secret_hash", "")
    if not crypto.verify_secret(received_secret, stored_hash):
        raise HTTPException(status_code=403, detail="Forbidden: Invalid webhook secret")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        client = reg.get_bot_client(bot)
        bot_poller.process_telegram_update(client, update, bot_info=bot)
        client.close()
    except Exception as exc:
        log.exception("Error processing BYOB webhook update for bot %s: %s", bot.get("bot_username"), exc)

    return {"ok": True}


_HTML = r"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#F6F7FB">
<link rel="manifest" href="/bisnis/manifest" crossorigin="use-credentials">
<title>Business Suite — BotConnector</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;850;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/__bc_shared_design_v1/v2/support_ai_widget.css">
<style>
/* ============ BOTCONNECTOR BUSINESS SUITE — UNIFIED DESIGN SYSTEM V2 ============ */
:root{
  --bc-white:#FFFFFF;
  --bc-gray:#F6F7FB;
  --bc-navy:#0B1020;
  --bc-dark-2:#111a33;
  --bc-ink:#101828;
  --bc-muted:#667085;
  --bc-muted2:#98a2b3;
  --bc-border:#E7E9F2;
  --bc-indigo:#5B5FEF;
  --bc-indigo-soft:#EEF0FF;
  --bc-indigo-hover:#4a4edb;
  --bc-ok:#22C55E;
  --bc-ok-soft:#e8f9ef;
  --bc-warn:#F59E0B;
  --bc-warn-soft:#fff6e0;
  --bc-err:#EF4444;
  --bc-err-soft:#fee2e2;
  --sidebar-w:260px;
  --header-h:70px;
  --radius-lg:24px;
  --radius-md:20px;
  --radius-sm:14px;
  --shadow-card:0 4px 20px rgba(11,16,32,0.03);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased;background:var(--bc-gray);color:var(--bc-ink);min-height:100vh;overflow-x:hidden}
.app{display:grid;grid-template-columns:var(--sidebar-w) 1fr;min-height:100vh}

/* ---------- SIDEBAR ---------- */
aside.sidebar{background:#FFFFFF;border-right:1px solid var(--bc-border);display:flex;flex-direction:column;width:var(--sidebar-w);z-index:50}
.brand{padding:18px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--bc-border);cursor:pointer;text-decoration:none;color:inherit}
.brand .plug{width:32px;height:32px;border-radius:9px;background:var(--bc-navy);color:#fff;display:grid;place-items:center;font-size:12px;font-weight:850;letter-spacing:-.02em;flex-shrink:0}
.brand .brand-title{font-size:16px;font-weight:850;letter-spacing:-.03em;color:var(--bc-ink)}
.brand .suite-badge{font-size:10px;font-weight:800;color:var(--bc-indigo);background:var(--bc-indigo-soft);padding:3px 8px;border-radius:99px;text-transform:uppercase;margin-left:auto;letter-spacing:.04em}

.branch{padding:14px 18px;border-bottom:1px solid var(--bc-border);background:#FAFBFD}
.branch label{display:block;font-size:10px;color:var(--bc-muted2);margin-bottom:6px;font-weight:800;text-transform:uppercase;letter-spacing:.08em}
.branch select{width:100%;background:#FFFFFF;border:1px solid var(--bc-border);color:var(--bc-ink);border-radius:10px;padding:9px 12px;font-size:13px;font-weight:650;outline:none;transition:.15s}
.branch select:focus{border-color:var(--bc-indigo);box-shadow:0 0 0 3px rgba(91,95,239,0.12)}

nav.nav{flex:1;padding:14px 12px;display:flex;flex-direction:column;gap:3px;overflow-y:auto}
nav.nav a{color:#475467;text-decoration:none;padding:10px 14px;border-radius:11px;font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:11px;transition:.15s ease}
nav.nav a:hover{color:var(--bc-ink);background:var(--bc-gray)}
nav.nav a.active{color:#FFFFFF !important;background:var(--bc-indigo);font-weight:750;box-shadow:0 4px 14px rgba(91,95,239,.28)}
nav.nav a svg{width:18px;height:18px;opacity:.9;stroke-width:2.2}
nav.nav a.active svg{stroke:#FFFFFF}

.sidebar-foot{padding:16px 18px;border-top:1px solid var(--bc-border);font-size:11px;color:var(--bc-muted);display:flex;flex-direction:column;gap:6px;background:#FAFBFD}
.sidebar-foot a{color:var(--bc-muted);text-decoration:none}
.sidebar-foot a:hover{color:var(--bc-indigo)}

/* ---------- TOPBAR ---------- */
main.workspace{display:flex;flex-direction:column;min-height:100vh;background:var(--bc-gray)}
header.topbar{height:var(--header-h);border-bottom:1px solid var(--bc-border);display:flex;align-items:center;justify-content:space-between;padding:0 32px;background:rgba(255,255,255,.94);backdrop-filter:blur(16px);position:sticky;top:0;z-index:40}
.page-title{font-size:19px;font-weight:850;color:var(--bc-ink);letter-spacing:-.025em}
.page-sub{color:var(--bc-muted);font-size:12px;margin-top:2px;font-weight:500}
.top-actions{display:flex;gap:12px;align-items:center}
.btn{min-height:40px;padding:0 18px;border-radius:11px;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-size:13px;font-weight:750;border:1px solid transparent;cursor:pointer;transition:.18s ease;text-decoration:none}
.btn-main{color:#fff;background:var(--bc-indigo);box-shadow:0 6px 16px rgba(91,95,239,.22)}
.btn-main:hover{background:var(--bc-indigo-hover);transform:translateY(-1px);box-shadow:0 8px 22px rgba(91,95,239,.32)}
.btn-line{color:#344054;background:#fff;border-color:var(--bc-border)}
.btn-line:hover{border-color:#b9bdcb;background:#fafafa}
.btn.sm{min-height:34px;padding:0 12px;font-size:12px;border-radius:8px}
.btn.danger{background:var(--bc-err);color:#fff}

.content{padding:32px 36px;overflow:auto;flex:1;max-width:1440px;width:100%;margin:0 auto}

/* Eyebrows */
.bc-eyebrow{display:inline-flex;align-items:center;gap:8px;color:var(--bc-indigo);font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
.bc-eyebrow::before{content:"";width:18px;height:2px;background:var(--bc-indigo);border-radius:2px}
.bc-eyebrow.navy{color:#a5b4fc}
.bc-eyebrow.navy::before{background:#a5b4fc}

/* ============================================================ */
/* DASHBOARD CENTERPIECE: DARK NAVY MULTI-BRANCH DASHBOARD CARD */
/* ============================================================ */
.bc-navy-dashboard{background:var(--bc-navy);border:1px solid var(--bc-navy);border-radius:var(--radius-lg);padding:32px 36px;color:#fff;position:relative;overflow:hidden;box-shadow:0 20px 50px rgba(11,16,32,.14);margin-bottom:24px}
.bc-navy-head{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:18px;margin-bottom:24px}
.bc-navy-title h2{margin:8px 0 0;font-size:22px;line-height:1.2;letter-spacing:-.025em;color:#fff;font-weight:850}
.bc-navy-title p{margin:6px 0 0;color:#98a2b3;font-size:13px;line-height:1.5}

/* Dark Period Pills */
.period-pills-dark{display:inline-flex;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:4px;gap:3px}
.pill-dark{background:transparent;border:none;border-radius:8px;padding:7px 14px;font-size:12px;font-weight:700;color:#98a2b3;cursor:pointer;transition:.15s}
.pill-dark:hover{color:#fff;background:rgba(255,255,255,.06)}
.pill-dark.active{background:var(--bc-indigo);color:#FFFFFF;font-weight:800;box-shadow:0 2px 10px rgba(91,95,239,.45)}

/* Navy KPIs */
.bc-navy-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
.bc-navy-kpi{padding:18px 20px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:rgba(255,255,255,.04);display:flex;flex-direction:column;justify-content:space-between}
.bc-navy-kpi .val{font-size:24px;font-weight:850;color:#fff;letter-spacing:-.02em;line-height:1.1}
.bc-navy-kpi .lbl{font-size:11px;font-weight:600;color:#8b90b8;margin-top:6px;text-transform:uppercase;letter-spacing:.04em}
.bc-navy-kpi .sub-tag{font-size:10px;font-weight:800;color:var(--bc-ok);background:rgba(34,197,94,.15);padding:3px 8px;border-radius:99px;margin-top:8px;display:inline-flex;align-items:center;gap:4px;width:fit-content}
.bc-navy-kpi .sub-tag.info{color:#a5b4fc;background:rgba(165,180,252,.12)}

/* Navy Chart */
.bc-navy-chart-wrap{border-top:1px solid rgba(255,255,255,.08);padding-top:20px;margin-top:6px}
.bc-navy-chart-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.bc-navy-chart-head span{font-size:11px;font-weight:700;color:#8b90b8;text-transform:uppercase;letter-spacing:.06em}
.bc-navy-chart{height:120px;display:flex;align-items:flex-end;gap:6px;padding:0 4px;overflow-x:auto}
.bc-navy-col{flex:1;min-width:14px;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;cursor:pointer}
.bc-navy-bar-wrap{width:100%;height:95px;display:flex;align-items:flex-end;justify-content:center}
.bc-navy-bar{width:65%;min-width:6px;max-width:26px;border-radius:6px 6px 0 0;background:linear-gradient(180deg,var(--bc-indigo),#3a3f9e);min-height:6px;transition:height 0.3s ease}
.bc-navy-bar.hi{background:linear-gradient(180deg,#7c7ff5,#4a4edb);box-shadow:0 0 12px rgba(124,127,245,.4)}
.bc-navy-bar.zero{background:rgba(255,255,255,.1);min-height:3px}
.bc-navy-label{font-size:9px;color:#8b90b8;font-weight:700;margin-top:6px;white-space:nowrap}

/* Zero Banner on Navy */
.bc-navy-zero-note{margin-top:16px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:14px 18px;color:#c7cbe0;font-size:13px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.bc-navy-zero-note a{background:var(--bc-indigo);color:#fff;border-radius:9px;padding:8px 16px;font-size:12px;font-weight:750;text-decoration:none;transition:.15s}
.bc-navy-zero-note a:hover{background:var(--bc-indigo-hover)}

/* Navy Branch Tags */
.bc-navy-branches{margin-top:20px;display:flex;flex-wrap:wrap;gap:8px;padding-top:16px;border-top:1px solid rgba(255,255,255,.08)}
.bc-navy-tag{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border:1px solid rgba(255,255,255,.14);border-radius:99px;font-size:11px;color:#c7cbe0;font-weight:600}
.bc-navy-tag .dot{width:7px;height:7px;border-radius:50%;background:var(--bc-ok)}

/* ============================================================ */
/* BENTO OPERATIONAL GRID */
/* ============================================================ */
.bc-ops-bento{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-bottom:24px}
.bc-op-bento-card{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:22px 24px;display:flex;align-items:center;gap:16px;text-decoration:none;color:inherit;box-shadow:var(--shadow-card);transition:.18s ease}
.bc-op-bento-card:hover{transform:translateY(-2px);border-color:var(--bc-indigo);box-shadow:0 8px 24px rgba(91,95,239,.08)}
.bc-op-icon{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;font-size:18px;flex-shrink:0}
.bc-op-icon svg{width:20px;height:20px;stroke-width:2.2}
.bc-op-icon.rest{background:#FEF3C7;color:#D97706}
.bc-op-icon.kit{background:#EEF0FF;color:#4F46E5}
.bc-op-icon.trf{background:#F3E8FF;color:#7E22CE}
.bc-op-icon.inv{background:#FEE2E2;color:#DC2626}
.bc-op-content .label{font-size:11px;font-weight:700;color:var(--bc-muted);text-transform:uppercase;letter-spacing:.04em}
.bc-op-content .count{font-size:22px;font-weight:850;color:var(--bc-ink);margin-top:2px;letter-spacing:-.02em}
.bc-op-content .count.warn{color:var(--bc-warn)}
.bc-op-content .count.err{color:var(--bc-err)}
.bc-op-arrow{margin-left:auto;display:flex;align-items:center;color:var(--bc-muted2)}
.bc-op-arrow svg{width:18px;height:18px;stroke-width:2.2}

/* ============================================================ */
/* BENTO LOWER GRID (BRANCH PERFORMANCE & QUICK ACTIONS) */
/* ============================================================ */
.bc-lower-bento{display:grid;grid-template-columns:1.2fr .8fr;gap:20px}
.bc-card{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:28px 30px;box-shadow:var(--shadow-card);margin-bottom:20px}
.bc-card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;gap:12px;flex-wrap:wrap}
.bc-card h3{margin:8px 0 0;font-size:19px;font-weight:850;color:var(--bc-ink);letter-spacing:-.02em}
.bc-card p{margin:4px 0 0;font-size:13px;color:var(--bc-muted)}

/* Tables */
table.bc-table{width:100%;border-collapse:collapse;font-size:13px}
table.bc-table th{text-align:left;padding:12px 14px;color:var(--bc-muted2);font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--bc-border);background:#FAFBFD}
table.bc-table td{padding:13px 14px;border-bottom:1px solid var(--bc-border);color:var(--bc-ink);vertical-align:middle}
table.bc-table tr:last-child td{border-bottom:none}
table.bc-table tr:hover td{background:#FAFBFD}

/* Badges */
.bc-badge{display:inline-flex;align-items:center;padding:4px 10px;border-radius:99px;font-size:10px;font-weight:850;letter-spacing:.04em;text-transform:uppercase}
.bc-badge.ok{background:var(--bc-ok-soft);color:var(--bc-ok)}
.bc-badge.warn{background:var(--bc-warn-soft);color:var(--bc-warn)}
.bc-badge.err{background:var(--bc-err-soft);color:var(--bc-err)}
.bc-badge.info{background:var(--bc-indigo-soft);color:var(--bc-indigo)}

/* Quick Actions Bento */
.bc-actions-list{display:flex;flex-direction:column;gap:10px}
.bc-action-btn{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border:1px solid var(--bc-border);border-radius:14px;background:#FAFBFD;text-decoration:none;color:var(--bc-ink);font-weight:700;font-size:13.5px;transition:.15s ease}
.bc-action-btn:hover{background:#FFFFFF;border-color:var(--bc-indigo);transform:translateY(-1px);box-shadow:0 4px 14px rgba(91,95,239,.08);color:var(--bc-indigo)}
.bc-action-btn .act-left{display:flex;align-items:center;gap:12px}
.bc-action-btn .act-icon{width:32px;height:32px;border-radius:8px;background:var(--bc-indigo-soft);color:var(--bc-indigo);display:grid;place-items:center}
.bc-action-btn .act-icon svg{width:16px;height:16px;stroke-width:2.2}

/* General Module UI Support */
.section{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:24px 28px;margin-bottom:20px;box-shadow:var(--shadow-card)}
.section h2{font-size:17px;margin-bottom:14px;color:var(--bc-ink);font-weight:850;letter-spacing:-0.01em}
.section h3{font-size:13px;margin-bottom:10px;color:var(--bc-muted);font-weight:700}
.dim{color:var(--bc-muted);font-size:13px}
.empty{padding:36px 20px;text-align:center;color:var(--bc-muted);border:1px dashed var(--bc-border);border-radius:14px;font-size:13px;background:#FFFFFF}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px}
.field{display:flex;flex-direction:column;gap:5px}
.field label{font-size:11px;color:var(--bc-muted);font-weight:700}
.field input,.field select,.field textarea{background:#FFFFFF;border:1px solid var(--bc-border);color:var(--bc-ink);border-radius:10px;padding:9px 12px;font-size:13px;min-width:150px;outline:none;font-family:inherit}
.field input:focus,.field select:focus,.field textarea:focus{border-color:var(--bc-indigo);box-shadow:0 0 0 3px rgba(91,95,239,0.12)}
.search{background:#FFFFFF;border:1px solid var(--bc-border);color:var(--bc-ink);border-radius:10px;padding:9px 14px;font-size:13px;min-width:220px;outline:none;font-family:inherit}
.search:focus{border-color:var(--bc-indigo);box-shadow:0 0 0 3px rgba(91,95,239,0.12)}

/* POS Unified UI */
.pos-layout{display:grid;grid-template-columns:1.35fr .65fr;gap:20px;align-items:start}
.pos-products{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:24px;min-height:480px;box-shadow:var(--shadow-card)}
.pos-cart{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:24px;position:sticky;top:90px;box-shadow:var(--shadow-card)}
.product-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;margin-top:16px}
.product-item{background:#FAFBFD;border:1px solid var(--bc-border);border-radius:14px;padding:16px;cursor:pointer;transition:.15s ease;display:flex;flex-direction:column;justify-content:space-between}
.product-item:hover{background:#FFFFFF;border-color:var(--bc-indigo);transform:translateY(-2px);box-shadow:0 8px 20px rgba(91,95,239,0.1)}
.product-item .p-icon{width:36px;height:36px;border-radius:10px;background:var(--bc-indigo-soft);color:var(--bc-indigo);display:grid;place-items:center;margin-bottom:10px}
.product-item .p-icon svg{width:18px;height:18px;stroke-width:2.2}
.product-item .name{font-size:13.5px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--bc-ink)}
.product-item .price{font-size:14px;color:var(--bc-indigo);font-weight:850;margin-top:6px}
.product-item .stock{font-size:10.5px;color:var(--bc-muted2);font-weight:650;margin-top:2px}
.cart-list{max-height:300px;overflow:auto;margin:14px 0}
.cart-item{display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--bc-border)}
.cart-item:last-child{border-bottom:none}
.cart-item .info{font-size:13px}
.cart-item .info .qty{font-size:11px;color:var(--bc-muted);margin-top:2px}
.cart-item .total{font-size:13.5px;font-weight:800}

/* POS Navy Summary Box */
.pos-navy-summary{background:var(--bc-navy);border-radius:16px;padding:18px 20px;color:#fff;margin-top:14px}
.pos-navy-summary .tot-lbl{font-size:11px;font-weight:700;color:#8b90b8;text-transform:uppercase;letter-spacing:.06em}
.pos-navy-summary .tot-val{font-size:26px;font-weight:900;color:#fff;letter-spacing:-.03em;margin-top:4px}

/* Kitchen KDS */
.kds{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.kds-lane{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:20px;min-height:320px;box-shadow:var(--shadow-card)}
.kds-lane h3{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--bc-ink);font-weight:850;margin-bottom:16px;text-transform:uppercase;letter-spacing:.04em}
.kds-card{background:#FAFBFD;border:1px solid var(--bc-border);border-radius:14px;padding:16px;margin-bottom:12px;transition:.15s}
.kds-card:hover{border-color:var(--bc-indigo);background:#FFFFFF}
.kds-card .kot{font-size:14px;font-weight:850;color:var(--bc-ink)}
.kds-card .meta{font-size:11px;color:var(--bc-muted);margin-top:4px}
.kds-card .items{font-size:12.5px;margin-top:10px;line-height:1.6}

/* Onboard Checklist */
.onboard-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
.onboard-step{background:#FFFFFF;border:1px solid var(--bc-border);border-radius:var(--radius-md);padding:24px;box-shadow:var(--shadow-card);display:flex;flex-direction:column;justify-content:space-between}
.onboard-step .step-num{width:30px;height:30px;border-radius:8px;background:var(--bc-indigo-soft);color:var(--bc-indigo);display:grid;place-items:center;font-size:12px;font-weight:850;margin-bottom:12px}
/* Contextual first-run guidance banner */
.bc-guidance-banner{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;background:var(--bc-indigo-soft);border:1px solid rgba(91,95,239,.25);border-radius:16px;padding:16px 22px;margin-bottom:20px}
.bc-guidance-main{display:flex;align-items:center;gap:14px;min-width:0;flex:1 1 auto}
.bc-guidance-icon{width:38px;height:38px;border-radius:10px;background:var(--bc-indigo);color:#fff;display:grid;place-items:center;flex-shrink:0}
.bc-guidance-icon svg{width:19px;height:19px;stroke-width:2.2}
.bc-guidance-text{min-width:0}
.bc-guidance-text div{overflow-wrap:anywhere;word-break:break-word}
.bc-guidance-banner > a{flex-shrink:0}

/* Responsive */
@media(max-width:1100px){
  .bc-navy-kpis{grid-template-columns:repeat(2,1fr)}
  .bc-ops-bento{grid-template-columns:repeat(2,1fr)}
  .bc-lower-bento{grid-template-columns:1fr}
  .pos-layout{grid-template-columns:1fr}
  .kds{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:900px){
  .app{grid-template-columns:1fr}
  aside.sidebar{position:fixed;left:0;top:0;bottom:0;z-index:60;transform:translateX(-100%);transition:.2s}
  .sidebar-open aside.sidebar{transform:translateX(0)}
  main.workspace{margin-left:0}
  .mobile-menu{display:flex;align-items:center;justify-content:center}
  .content{padding:20px 16px}
  header.topbar{padding:0 18px}
  .kds{grid-template-columns:1fr}
}
@media(max-width:560px){
  .bc-navy-dashboard{padding:22px 20px;border-radius:18px}
  .bc-navy-kpis{grid-template-columns:1fr}
  .bc-ops-bento{grid-template-columns:1fr}
}
/* Keep flex/grid children shrinkable so the approved navy panels never force
   horizontal overflow on small screens (applies to every page, not just onboarding). */
.bc-navy-head > *{min-width:0}
.bc-navy-title h2,.bc-navy-title p{overflow-wrap:anywhere;word-break:break-word}
.bc-navy-kpis > *{min-width:0}
.bc-navy-kpi .val,.bc-navy-kpi .lbl{overflow-wrap:anywhere;word-break:break-word}


/* In-App Guidance & First-Use Welcome System */
.bc-welcome-banner {
  background: linear-gradient(135deg, #EEF0FF 0%, #F5F6FF 100%);
  border: 1px solid #C7CBF8;
  border-radius: 16px;
  padding: 20px 24px;
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  box-shadow: 0 4px 16px rgba(91, 95, 239, 0.04);
}
.bc-guide-tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--bc-border);
  padding-bottom: 12px;
  margin-bottom: 20px;
  overflow-x: auto;
}
.bc-guide-tab-btn {
  background: transparent;
  border: 1px solid transparent;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 750;
  color: var(--bc-muted);
  cursor: pointer;
  white-space: nowrap;
}
.bc-guide-tab-btn.active {
  background: var(--bc-indigo-soft);
  color: var(--bc-indigo);
  border-color: #C7CBF8;
}
.bc-workflow-box {
  background: #F8FAFC;
  border: 1px solid var(--bc-border);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}
.bc-step-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 12px 0;
}
.bc-flow-pill {
  background: #FFFFFF;
  border: 1px solid var(--bc-border);
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 750;
  color: var(--bc-ink);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.bc-flow-arrow {
  color: var(--bc-indigo);
  font-weight: 800;
  font-size: 14px;
}
.bc-tip-box {
  background: #F0FDF4;
  border: 1px solid #BBF7D0;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
  color: #166534;
  margin: 12px 0;
  line-height: 1.5;
}
.kpi-help-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  margin-left: 6px;
  cursor: help;
  vertical-align: middle;
}

/* Modal Dialog System */
.bc-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(11, 16, 32, 0.65);
  backdrop-filter: blur(6px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.bc-modal-dialog {
  background: #FFFFFF;
  border: 1px solid var(--bc-border);
  border-radius: var(--radius-lg);
  width: 100%;
  max-width: 540px;
  box-shadow: 0 24px 60px rgba(11, 16, 32, 0.2);
  padding: 32px;
  position: relative;
  max-height: 90vh;
  overflow-y: auto;
}
.bc-modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 16px;
}
.bc-modal-close {
  background: transparent;
  border: none;
  font-size: 24px;
  line-height: 1;
  color: var(--bc-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 8px;
}
.bc-modal-close:hover {
  color: var(--bc-ink);
  background: var(--bc-indigo-soft);
}

</style></head><body class="app">
<aside class="sidebar">
  <a class="brand" href="/" style="text-decoration:none;color:inherit">
    <div class="plug">BC</div>
    <div class="brand-title">BotConnector</div>
    <div class="suite-badge">Suite</div>
  </a>
  <div class="branch">
    <label>Cabang / Lokasi</label>
    <select id="branchSelect"><option>Memuat...</option></select>
  </div>
  <nav class="nav" id="nav">
    <a href="#/dashboard" data-view="dashboard" class="active"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/></svg>Dashboard</a>
    <a href="#/pos" data-view="pos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="4" width="20" height="14" rx="3"/><path d="M7 18v4m10-4v4M6 9h12M9 13h2m4 0h2"/></svg>POS</a>
    <a href="#/orders" data-view="orders"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>Orders</a>
    <a href="#/products" data-view="products"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>Products</a>
    <a href="#/inventory" data-view="inventory"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>Inventory</a>
    <a href="#/transfers" data-view="transfers"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M17 1l4 4-4 4"/><path d="M3 5h18"/><path d="M7 23l-4-4 4-4"/><path d="M21 19H3"/></svg>Transfers</a>
    <a href="#/restaurant" data-view="restaurant"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>Restaurant</a>
    <a href="#/kitchen" data-view="kitchen"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 13.87A4 4 0 0 1 7.41 8a4 4 0 0 1 7.17-1.87A4 4 0 0 1 17.5 6.5"/><path d="M2 17h20"/><path d="M6 17v5"/><path d="M12 17v5"/><path d="M18 17v5"/></svg>Kitchen</a>
    <a href="#/reports" data-view="reports"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>Reports</a>
    <a href="#/integrasi" data-view="integrasi"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>Integrasi</a>
    <a href="#/onboard" data-view="onboard"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>Siapkan Toko</a>
    <a href="#/quick" data-view="quick"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>Quick Mode</a>
  </nav>
  <div class="sidebar-foot">
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <a href="/status" target="_blank">Status</a> &bull;
      <a href="/privacy" target="_blank">Privasi</a> &bull;
      <a href="/terms" target="_blank">Ketentuan</a>
    </div>
    <div style="color:var(--bc-muted2)">&copy; 2026 BotConnector</div>
  </div>
</aside>
<main class="workspace">
  <header class="topbar">
    <div style="display:flex;align-items:center;gap:14px">
      <button class="mobile-menu" aria-label="Buka menu" onclick="document.body.classList.toggle('sidebar-open')">☰</button>
      <div>
        <div class="page-title" id="pageTitle">Dashboard</div>
        <div class="page-sub" id="pageSub">Business Suite &middot; Multi-Branch Operations</div>
      </div>
    </div>
    <div class="top-actions">
      <button class="btn btn-line" id="guideBtn" onclick="openBizGuideModal()" style="display:inline-flex;align-items:center;gap:6px;font-weight:750">? Panduan</button>
      <button class="btn btn-line" id="syncBtn" style="display:inline-flex;align-items:center;gap:6px"><span style="width:7px;height:7px;border-radius:50%;background:var(--bc-ok)"></span>Sync Offline</button>
      <a class="btn btn-main" href="/">BotConnector.id</a>
    </div>
  </header>
  <div class="content" id="main"></div>
  <div id="modalContainer"></div>
</main>
<script>
const byId = id => document.getElementById(id);
const qsa = sel => Array.prototype.slice.call(document.querySelectorAll(sel));
async function j(u,o){
  const r=await fetch(u,o);
  const ct=(r.headers.get('content-type')||'');
  if(!r.ok){
    if(ct.includes('application/json')){
      const err=await r.json();
      throw new Error(err.detail||err.error||('HTTP error '+r.status));
    }
    throw new Error('Gagal memuat data (HTTP '+r.status+'). Silakan coba lagi.');
  }
  if(ct.includes('application/json')){
    return r.json();
  }
  const txt=await r.text();
  try{return JSON.parse(txt);}catch(e){throw new Error('Gagal memuat data. Format respon server tidak valid.');}
}
const esc=s=>String(s==null?'':s).replace(/[&<>\"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[m]));
const money=n=>new Intl.NumberFormat('id-ID').format(Number(n||0));
const time=(d)=>d?new Date(d).toLocaleString('id-ID',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'-';
const VIEWS={dashboard:'Dashboard',pos:'POS Kasir',orders:'Orders / Penjualan',products:'Katalog Produk',inventory:'Inventori Multi-Cabang',transfers:'Transfer Antar Cabang',restaurant:'Manajemen Restoran',kitchen:'Kitchen / KDS',reports:'Laporan & Analitik',integrasi:'Integrasi Sistem',onboard:'Siapkan Toko',quick:'Quick Mode'};
let BRANCHES=[],REGISTERS=[],PRODUCTS=[];

const ICONS = {
  pos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="2" y="4" width="20" height="14" rx="3"/><path d="M7 18v4m10-4v4M6 9h12M9 13h2m4 0h2"/></svg>',
  rest: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>',
  kit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 13.87A4 4 0 0 1 7.41 8a4 4 0 0 1 7.17-1.87A4 4 0 0 1 17.5 6.5"/><path d="M2 17h20"/><path d="M6 17v5"/><path d="M12 17v5"/><path d="M18 17v5"/></svg>',
  trf: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M17 1l4 4-4 4"/><path d="M3 5h18"/><path d="M7 23l-4-4 4-4"/><path d="M21 19H3"/></svg>',
  inv: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  prod: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
  rep: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
  arrowRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="20 6 9 17 4 12"/></svg>'
};

function page(title,sub,body){return '<div style="margin-bottom:24px"><div><div class="bc-eyebrow">BUSINESS SUITE</div><h1 style="font-size:26px;font-weight:850;letter-spacing:-.03em;color:var(--bc-ink);margin:8px 0 4px">'+esc(title)+'</h1><div style="color:var(--bc-muted);font-size:13.5px">'+esc(sub||'')+'</div></div></div>'+body;}

let DASH_DAYS = 30;

function renderSalesChart(series, totalSales) {
  if (!series || !series.length) {
    return '<div class="bc-navy-zero-note">' +
      '<span>Belum ada data penjualan pada periode ini.</span>' +
      '<a href="#/pos">Buka Kasir POS &rarr;</a>' +
    '</div>';
  }

  const maxVal = Math.max(...series.map(s => s.sales), 1000);
  const count = series.length;

  const cols = series.map((s, idx) => {
    const pct = s.sales > 0 ? Math.min(100, Math.max(10, Math.round((s.sales / maxVal) * 100))) : 3;
    const dateObj = new Date(s.date + 'T00:00:00');
    const dayName = dateObj.toLocaleDateString('id-ID', { weekday: 'narrow' });
    const dateLabel = dateObj.toLocaleDateString('id-ID', { day: 'numeric', month: 'numeric' });
    const isZero = s.sales === 0;

    const showLabel = count <= 7 ? (dayName + ' ' + dateLabel) : (count <= 14 ? (idx % 2 === 0 ? dateLabel : '') : (idx % 5 === 0 || idx === count - 1 ? dateLabel : ''));

    return '<div class="bc-navy-col" title="' + esc(s.date) + ': Rp ' + money(s.sales) + ' (' + s.transactions + ' transaksi)">' +
      '<div class="bc-navy-bar-wrap">' +
        '<div class="bc-navy-bar ' + (isZero ? 'zero' : 'hi') + '" style="height:' + pct + '%"></div>' +
      '</div>' +
      '<div class="bc-navy-label">' + showLabel + '</div>' +
    '</div>';
  }).join('');

  const zeroNote = totalSales === 0 ?
    '<div class="bc-navy-zero-note">' +
      '<span>⚡ Transaksi pertama di POS kasir akan langsung mengaktifkan grafik performa penjualan live ini.</span>' +
      '<a href="#/pos">Buka Kasir POS &rarr;</a>' +
    '</div>' : '';

  return '<div class="bc-navy-chart-wrap">' +
    '<div class="bc-navy-chart-head">' +
      '<span>Grafik Penjualan Harian</span>' +
      '<span style="color:#a5b4fc;font-weight:700">Rp ' + money(totalSales) + ' Total</span>' +
    '</div>' +
    '<div class="bc-navy-chart">' + cols + '</div>' +
    zeroNote +
  '</div>';
}

window.setDashPeriod = function(d) {
  DASH_DAYS = Number(d);
  route();
};

async function renderDashboard(){
  let data;
  try {
    data = await j('/bisnis/api/dashboard-v2?days=' + DASH_DAYS);
  } catch (e) {
    const st = await j('/bisnis/api/state');
    if (!st.business) return page('Dashboard', 'Business Suite', '<div class="empty">Belum ada business. Jalankan pilot seed.</div>');
    updateBranchSelect(st.branches);
    return page('Dashboard', 'Pantau performa dan operasional bisnis Anda.', '<div class="empty">Gagal memuat dashboard: ' + esc(e.message) + '</div>');
  }

  if (!data || !data.business) {
    return page('Dashboard', 'Business Suite', '<div class="empty">Belum ada business.</div>');
  }

  updateBranchSelect(data.branches || []);
  const kpis = data.kpis || { sales: 0, transactions: 0, average_ticket: 0, active_branches: 1 };
  const ops = data.operations || { open_restaurant_orders: 0, pending_kitchen_orders: 0, active_transfers: 0, low_stock_count: 0 };
  const timeseries = data.timeseries || [];
  const branchList = data.branches || [];

  const periodPillsDark = '<div class="period-pills-dark">' +
    '<button class="pill-dark ' + (DASH_DAYS === 1 ? 'active' : '') + '" onclick="setDashPeriod(1)">Hari Ini</button>' +
    '<button class="pill-dark ' + (DASH_DAYS === 7 ? 'active' : '') + '" onclick="setDashPeriod(7)">7 Hari</button>' +
    '<button class="pill-dark ' + (DASH_DAYS === 30 ? 'active' : '') + '" onclick="setDashPeriod(30)">30 Hari</button>' +
    '<button class="pill-dark ' + (DASH_DAYS === 90 ? 'active' : '') + '" onclick="setDashPeriod(90)">90 Hari</button>' +
  '</div>';

  const chartHtml = renderSalesChart(timeseries, kpis.sales);
  const branchTags = branchList.map(b => '<span class="bc-navy-tag"><span class="dot"></span>' + esc(b.name) + ' (' + esc(b.code) + ')</span>').join('');

  // 1. CENTERPIECE: DARK NAVY MULTI-BRANCH DASHBOARD PANEL
  const navyDashboard = '<div class="bc-navy-dashboard">' +
    '<div class="bc-navy-head">' +
      '<div class="bc-navy-title">' +
        '<div class="bc-eyebrow navy">Multi-Branch Dashboard</div>' +
        '<h2>Performa Operasional Bisnis Terhubung</h2>' +
        '<p>Konsolidasi penjualan, transaksi kasir, dan operasional seluruh cabang dalam satu tampilan.</p>' +
      '</div>' +
      periodPillsDark +
    '</div>' +
    '<div class="bc-navy-kpis">' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(kpis.sales) + '</div>' +
        '<div class="lbl">Total Penjualan (' + (DASH_DAYS === 1 ? 'Hari Ini' : DASH_DAYS + 'D') + ') <span class="kpi-help-btn" title="Total nilai transaksi selesai pada periode ini">?</span></div>' +
        '<div class="sub-tag info">● Selesai</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">' + money(kpis.transactions) + '</div>' +
        '<div class="lbl">Total Transaksi <span class="kpi-help-btn" title="Jumlah total tiket transaksi penjualan yang berhasil diselesaikan">?</span></div>' +
        '<div class="sub-tag">● Live</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(kpis.average_ticket) + '</div>' +
        '<div class="lbl">Rata-rata Ticket (AOV) <span class="kpi-help-btn" title="Average Order Value: Rata-rata nilai belanja per transaksi">?</span></div>' +
        '<div class="sub-tag info">Per Order</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">' + kpis.active_branches + '</div>' +
        '<div class="lbl">Cabang Aktif</div>' +
        '<div class="sub-tag">● Online</div>' +
      '</div>' +
    '</div>' +
    chartHtml +
    '<div class="bc-navy-branches">' +
      branchTags +
    '</div>' +
  '</div>';

  // 2. BENTO SUPPORTING OPERATIONAL ROW (WITH CLEAN SVG ICONS)
  const opsBento = '<div class="bc-ops-bento">' +
    '<a href="#/restaurant" class="bc-op-bento-card">' +
      '<div class="bc-op-icon rest">' + ICONS.rest + '</div>' +
      '<div class="bc-op-content">' +
        '<div class="label">Order Restoran</div>' +
        '<div class="count ' + (ops.open_restaurant_orders ? 'warn' : '') + '">' + ops.open_restaurant_orders + '</div>' +
      '</div>' +
      '<span class="bc-op-arrow">' + ICONS.arrowRight + '</span>' +
    '</a>' +
    '<a href="#/kitchen" class="bc-op-bento-card">' +
      '<div class="bc-op-icon kit">' + ICONS.kit + '</div>' +
      '<div class="bc-op-content">' +
        '<div class="label">KOT Dapur</div>' +
        '<div class="count ' + (ops.pending_kitchen_orders ? 'warn' : '') + '">' + ops.pending_kitchen_orders + '</div>' +
      '</div>' +
      '<span class="bc-op-arrow">' + ICONS.arrowRight + '</span>' +
    '</a>' +
    '<a href="#/transfers" class="bc-op-bento-card">' +
      '<div class="bc-op-icon trf">' + ICONS.trf + '</div>' +
      '<div class="bc-op-content">' +
        '<div class="label">Transfer Stok</div>' +
        '<div class="count">' + ops.active_transfers + '</div>' +
      '</div>' +
      '<span class="bc-op-arrow">' + ICONS.arrowRight + '</span>' +
    '</a>' +
    '<a href="#/inventory" class="bc-op-bento-card">' +
      '<div class="bc-op-icon inv">' + ICONS.inv + '</div>' +
      '<div class="bc-op-content">' +
        '<div class="label">Stok Menipis (&le;5)</div>' +
        '<div class="count ' + (ops.low_stock_count ? 'err' : '') + '">' + ops.low_stock_count + '</div>' +
      '</div>' +
      '<span class="bc-op-arrow">' + ICONS.arrowRight + '</span>' +
    '</a>' +
  '</div>';

  // 3. LOWER BENTO: BRANCH PERFORMANCE & QUICK ACTIONS
  const branchRows = branchList.map(b => '<tr>' +
    '<td><strong>' + esc(b.name) + '</strong><div style="font-size:11px;color:var(--bc-muted)">Kode: ' + esc(b.code) + '</div></td>' +
    '<td><strong>Rp ' + money(b.sales) + '</strong></td>' +
    '<td>' + money(b.transactions) + '</td>' +
    '<td>Rp ' + money(b.avg_ticket) + '</td>' +
    '<td><span class="bc-badge ok">' + esc(b.status) + '</span></td>' +
  '</tr>').join('');

  const branchCard = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">CABANG BISNIS</div>' +
        '<h3>Performa Penjualan per Cabang</h3>' +
        '<p>Ringkasan omzet dan transaksi selesai (' + (DASH_DAYS === 1 ? 'Hari Ini' : DASH_DAYS + ' hari') + ').</p>' +
      '</div>' +
      '<a href="#/inventory" class="btn btn-line sm">Kelola Inventori &rarr;</a>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>Cabang</th><th>Penjualan</th><th>Transaksi</th><th>Avg Ticket</th><th>Status</th></tr>' +
      (branchRows || '<tr><td colspan="5" style="text-align:center;color:var(--bc-muted)">Belum ada cabang terdaftar.</td></tr>') +
    '</table>' +
  '</div>';

  const quickActionsCard = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">OPERASIONAL</div>' +
        '<h3>Aksi Cepat &amp; Alur Kerja</h3>' +
        '<p>Akses cepat ke modul operasional utama bisnis Anda.</p>' +
      '</div>' +
    '</div>' +
    '<div class="bc-actions-list">' +
      '<a href="#/pos" class="bc-action-btn">' +
        '<div class="act-left"><div class="act-icon">' + ICONS.pos + '</div><span>Buka Kasir POS (Retail &amp; Toko)</span></div>' +
        '<span style="color:var(--bc-indigo)">' + ICONS.arrowRight + '</span>' +
      '</a>' +
      '<a href="#/restaurant" class="bc-action-btn">' +
        '<div class="act-left"><div class="act-icon">' + ICONS.rest + '</div><span>Buka Kasir &amp; Meja Restoran</span></div>' +
        '<span style="color:var(--bc-indigo)">' + ICONS.arrowRight + '</span>' +
      '</a>' +
      '<a href="#/products" class="bc-action-btn">' +
        '<div class="act-left"><div class="act-icon">' + ICONS.prod + '</div><span>Kelola Katalog Produk &amp; Harga</span></div>' +
        '<span style="color:var(--bc-indigo)">' + ICONS.arrowRight + '</span>' +
      '</a>' +
      '<a href="#/reports" class="bc-action-btn">' +
        '<div class="act-left"><div class="act-icon">' + ICONS.rep + '</div><span>Laporan Keuangan &amp; Laba Rugi</span></div>' +
        '<span style="color:var(--bc-indigo)">' + ICONS.arrowRight + '</span>' +
      '</a>' +
    '</div>' +
  '</div>';

  const lowerBento = '<div class="bc-lower-bento">' +
    branchCard +
    quickActionsCard +
  '</div>';

  const guidance = await onboardingGuidance();
  return guidance + navyDashboard + opsBento + lowerBento;
}

window.dismissBizWelcome = function() {
  localStorage.setItem('bc_biz_welcome_dismissed', '1');
  route();
};

window.resetBizGuide = function() {
  localStorage.removeItem('bc_biz_welcome_dismissed');
  openBizGuideModal();
};

async function onboardingGuidance() {
  let o;
  try {
    const st = await j('/bisnis/api/onboarding');
    o = st && st.onboarding;
  } catch(e) { o = null; }

  const dismissed = localStorage.getItem('bc_biz_welcome_dismissed') === '1';
  let welcomeHtml = '';
  if (!dismissed) {
    welcomeHtml = '<div class="bc-welcome-banner" id="bizWelcomeBanner">' +
      '<div style="max-width:720px">' +
        '<div style="font-size:11px;font-weight:850;color:var(--bc-indigo);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px">PANDUAN MEMULAI CEPAT</div>' +
        '<div style="font-size:18px;font-weight:850;color:var(--bc-ink);margin-bottom:6px">Selamat datang di Business Suite</div>' +
        '<div style="font-size:13.5px;color:var(--bc-muted);line-height:1.5">Siapkan bisnis mulai dari cabang, produk, harga, dan stok hingga transaksi kasir pertama. Setelah transaksi berjalan, dashboard dan laporan akan terisi otomatis.</div>' +
      '</div>' +
      '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">' +
        '<a href="#/onboard" class="btn btn-main sm">Mulai Siapkan Bisnis &rarr;</a>' +
        '<button class="btn btn-line sm" onclick="openBizGuideModal()">Lihat Cara Kerjanya</button>' +
        '<button class="btn btn-line sm" onclick="dismissBizWelcome()" style="color:var(--bc-muted)">Lewati untuk Sekarang</button>' +
      '</div>' +
    '</div>';
  }

  if (!o || o.ready) return welcomeHtml;

  let msg = '', link = '#/onboard', linkText = 'Buka Siapkan Toko';
  if (!o.produk.done) {
    msg = 'Tambahkan produk pertama Anda untuk mulai membangun katalog kasir.';
    link = '#/products'; linkText = 'Tambahkan Produk';
  } else if (!o.harga.done) {
    msg = 'Produk sudah ada, namun belum memiliki harga jual. Atur harga agar bisa dijual.';
    link = '#/products'; linkText = 'Atur Harga Jual';
  } else if (!o.stok.done) {
    msg = 'Harga sudah diatur. Masukkan stok awal agar produk siap dijual.';
    link = '#/products'; linkText = 'Tambah Stok';
  } else if (!o.pos.done) {
    msg = 'Produk, harga, dan stok sudah tersedia. Buka kasir POS untuk menyelesaikan penjualan pertama.';
    link = '#/pos'; linkText = 'Buka Kasir POS';
  }

  const stepCard = '<div class="bc-guidance-banner">' +
    '<div class="bc-guidance-main">' +
      '<div class="bc-guidance-icon">' + ICONS.prod + '</div>' +
      '<div class="bc-guidance-text">' +
        '<h4>Langkah Selanjutnya: ' + esc(linkText) + '</h4>' +
        '<p>' + esc(msg) + '</p>' +
      '</div>' +
    '</div>' +
    '<div style="display:flex;gap:8px;align-items:center">' +
      '<a href="' + link + '" class="btn btn-main sm">' + esc(linkText) + ' &rarr;</a>' +
      '<a href="#/onboard" class="btn btn-line sm">Checklist Persiapan</a>' +
    '</div>' +
  '</div>';

  return welcomeHtml + stepCard;
}

let CART = [];
async function renderPos(){
  let d;
  try { d = await j('/bisnis/api/pos'); } catch(e) {
    return page('POS Kasir', 'Kasir Penjualan Retail & Restoran', '<div class="empty">Gagal memuat POS: ' + esc(e.message) + '</div>');
  }
  if (!d.business) return page('POS Kasir', 'Business Suite', '<div class="empty">Belum ada bisnis terdaftar.</div>');
  PRODUCTS = d.products || [];
  BRANCHES = d.branches || [];
  REGISTERS = d.registers || [];
  updateBranchSelect(BRANCHES);

  function renderCartList(){
    if (!CART.length) return '<div class="dim" style="padding:28px 12px;text-align:center">Keranjang masih kosong.<br><small style="color:var(--bc-muted2)">Klik produk pada katalog di sebelah kiri untuk menambahkan ke transaksi.</small></div>';
    return CART.map((it, idx) => '<div class="cart-item">' +
      '<div class="info"><strong>' + esc(it.name) + '</strong><div class="qty">' + it.qty + ' x Rp ' + money(it.price) + '</div></div>' +
      '<div style="display:flex;align-items:center;gap:10px">' +
        '<span class="total">Rp ' + money(it.qty * it.price) + '</span>' +
        '<button onclick="removeCart(' + idx + ')" style="border:none;background:transparent;color:var(--bc-err);cursor:pointer;font-weight:800" title="Hapus item">&times;</button>' +
      '</div>' +
    '</div>').join('');
  }

  
  let oState = null;
  try {
    const st = await j('/bisnis/api/onboarding');
    oState = st && st.onboarding;
  } catch(e){}

  const posGuideTip = (!oState || !oState.first_sale || !oState.first_sale.done)
    ? '<div class="bc-tip-box" style="margin-bottom:16px">' +
        '<strong>Panduan Transaksi Pertama:</strong> 1. Pilih Produk &rarr; 2. Periksa Total &rarr; 3. Klik "Bayar Sekarang".<br>' +
        '<span style="font-size:12px;color:#15803D">Setelah transaksi selesai: transaksi bertambah, stok produk berkurang otomatis, struk dibuat, dan dashboard diperbarui.</span>' +
      '</div>'
    : '';

  const subtotal = CART.reduce((acc, it) => acc + (it.qty * it.price), 0);

  const productCards = (PRODUCTS.length ? PRODUCTS.map(p => {
    const hasStock = (p.stock_quantity || 0) > 0;
    return '<div class="product-item' + (hasStock ? '' : ' disabled') + '" onclick="' + (hasStock ? 'addToCart(' + esc(p.master_sku_id) + ')' : 'alert(\'Stok kosong. Buka menu Katalog Produk untuk menambah stok.\')') + '" style="' + (hasStock ? '' : 'opacity:.55;cursor:not-allowed') + '">' +
      '<div class="p-icon">' + ICONS.prod + '</div>' +
      '<div class="name">' + esc(p.name) + '</div>' +
      '<div class="price">Rp ' + money(p.price || 0) + '</div>' +
      '<div class="stock">SKU: ' + esc(p.sku) + ' &middot; Stok: ' + (p.stock_quantity || 0) + '</div>' +
    '</div>';
  }).join('') : '<div class="empty" style="grid-column:1/-1">Belum ada produk terdaftar. Buka menu Katalog Produk untuk menambahkan produk.</div>');

  const body = posGuideTip + '<div class="pos-layout">' +
    '<div class="pos-products">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:12px;flex-wrap:wrap">' +
        '<div style="position:relative;flex:1;min-width:240px">' +
          '<input type="text" class="search" style="width:100%;padding-left:36px" placeholder="Cari nama produk atau SKU..." id="posSearch" oninput="filterProducts(this.value)">' +
          '<span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--bc-muted2);display:flex">' + ICONS.search + '</span>' +
        '</div>' +
        '<span style="font-size:12px;color:var(--bc-muted);font-weight:700">' + PRODUCTS.length + ' Produk Tersedia</span>' +
      '</div>' +
      '<div class="product-grid" id="posProductGrid">' + productCards + '</div>' +
    '</div>' +
    '<div class="pos-cart">' +
      '<div class="bc-eyebrow">KASIR AKTIF</div>' +
      '<h3 style="font-size:18px;font-weight:850;color:var(--bc-ink);margin:6px 0 12px">Keranjang Transaksi</h3>' +
      '<div class="cart-list" id="cartList">' + renderCartList() + '</div>' +
      '<div class="pos-navy-summary">' +
        '<div class="tot-lbl">Total Tagihan</div>' +
        '<div class="tot-val">Rp ' + money(subtotal) + '</div>' +
      '</div>' +
      '<div style="margin-top:16px;display:flex;flex-direction:column;gap:10px">' +
        '<button class="btn btn-main" style="width:100%" onclick="checkoutPos()" ' + (CART.length ? '' : 'disabled') + '>Bayar Sekarang &rarr;</button>' +
        (CART.length ? '<button class="btn btn-line sm" style="width:100%" onclick="clearCart()">Kosongkan Keranjang</button>' : '') +
      '</div>' +
    '</div>' +
  '</div>';

  return page('POS Kasir', 'Kasir penjualan retail, toko cabang, dan restoran cepat.', body);
}

window.addToCart = function(skuId) {
  const p = PRODUCTS.find(x => Number(x.master_sku_id) === Number(skuId));
  if (!p) return;
  const existing = CART.find(x => Number(x.master_sku_id) === Number(skuId));
  if (existing) { existing.qty += 1; }
  else { CART.push({ master_sku_id: p.master_sku_id, name: p.name, price: p.price || 0, qty: 1 }); }
  route();
};

window.removeCart = function(idx) {
  CART.splice(idx, 1);
  route();
};

window.clearCart = function() {
  CART = [];
  route();
};

window.filterProducts = function(q) {
  q = (q || '').toLowerCase();
  const el = byId('posProductGrid');
  if (!el) return;
  const filtered = PRODUCTS.filter(p => (p.name || '').toLowerCase().includes(q) || (p.sku || '').toLowerCase().includes(q) || (p.barcode || '').includes(q));
  el.innerHTML = filtered.map(p => '<div class="product-item" onclick="addToCart(' + esc(p.master_sku_id) + ')">' +
    '<div class="p-icon">' + ICONS.prod + '</div>' +
    '<div class="name">' + esc(p.name) + '</div>' +
    '<div class="price">Rp ' + money(p.price || 0) + '</div>' +
    '<div class="stock">SKU: ' + esc(p.sku) + '</div>' +
  '</div>').join('') || '<div class="empty" style="grid-column:1/-1">Tidak ada produk yang cocok.</div>';
};

window.checkoutPos = async function() {
  if (!CART.length) return alert('Keranjang kosong');
  const b = BRANCHES[0];
  const reg = REGISTERS[0];
  if (!b) return alert('Cabang belum siap');
  const lines = CART.map(it => ({ master_sku_id: it.master_sku_id, quantity: it.qty, unit_price: it.price, discount: 0 }));
  const total = CART.reduce((acc, it) => acc + (it.qty * it.price), 0);
  try {
    const res = await j('/bisnis/api/sale', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        branch_id: b.id,
        register_id: reg ? reg.id : 1,
        warehouse_id: b.warehouse_id || 1,
        lines: lines,
        tender_method: 'CASH',
        amount_tendered: total,
        discount: 0,
        tax_amount: 0,
        client_event_id: 'pos-' + Date.now()
      })
    });
    if (res.ok) {
      const itemsCopy = CART.slice();
      CART = [];
      showSaleSuccessModal(res, itemsCopy, total);
      route();
    }
  } catch(e) {
    alert('Gagal transaksi: ' + e.message);
  }
};

async function renderOrders(){
  let d;
  try { d = await j('/bisnis/api/orders'); } catch(e) {
    return page('Orders', 'Daftar Transaksi Penjualan', '<div class="empty">Gagal memuat orders: ' + esc(e.message) + '</div>');
  }
  const sales = d.sales || [];
  const totalOmzet = sales.reduce((acc, s) => acc + (s.total || 0), 0);
  const avgAov = sales.length ? Math.round(totalOmzet / sales.length) : 0;

  const salesRows = sales.map(s => '<tr>' +
    '<td><strong>' + esc(s.receipt_number || ('# ' + s.id)) + '</strong></td>' +
    '<td>' + time(s.created_at) + '</td>' +
    '<td><strong>Rp ' + money(s.total) + '</strong></td>' +
    '<td><span class="bc-badge ok">' + esc(s.tender_method || 'CASH') + '</span></td>' +
    '<td><a href="/bisnis/api/receipt/' + s.id + '" target="_blank" class="btn btn-line sm">Struk &rarr;</a></td>' +
  '</tr>').join('');

  const body = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">TOTAL TRANSAKSI</div><div style="font-size:24px;font-weight:850;margin-top:6px">' + sales.length + ' Order</div></div>' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">TOTAL OMZET</div><div style="font-size:24px;font-weight:850;margin-top:6px">Rp ' + money(totalOmzet) + '</div></div>' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">RATA-RATA TICKET (AOV)</div><div style="font-size:24px;font-weight:850;margin-top:6px">Rp ' + money(avgAov) + '</div></div>' +
  '</div>' +
  '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">TRANSAKSI SELESAI</div>' +
        '<h3>Riwayat Penjualan Kasir &amp; POS</h3>' +
        '<p>Daftar seluruh transaksi yang telah dibayar dan dicatat ke sistem.</p>' +
      '</div>' +
      '<a href="#/pos" class="btn btn-main sm">+ Transaksi Baru</a>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>No. Struk</th><th>Waktu</th><th>Total</th><th>Metode</th><th>Aksi</th></tr>' +
      (salesRows || '<tr><td colspan="5" style="text-align:center;color:var(--bc-muted);padding:32px">Belum ada transaksi penjualan tercatat.</td></tr>') +
    '</table>' +
  '</div>';
  return page('Orders / Penjualan', 'Daftar transaksi penjualan POS dan kasir.', body);
}

async function renderProducts(){
  let d;
  try { d = await j('/bisnis/api/pos'); } catch(e) {
    return page('Products', 'Katalog Produk', '<div class="empty">Gagal memuat produk: ' + esc(e.message) + '</div>');
  }
  const prods = d.products || [];
  const prodRows = prods.map(p => '<tr>' +
    '<td><strong>' + esc(p.sku) + '</strong></td>' +
    '<td>' + esc(p.name) + '</td>' +
    '<td><span class="bc-badge info">' + esc(p.category || 'Umum') + '</span></td>' +
    '<td>' + esc(p.barcode || '-') + '</td>' +
    '<td><strong>Rp ' + money(p.price || 0) + '</strong>' +
      (p.price ? '' : '<div style="font-size:11px;color:var(--bc-warn);font-weight:700">Belum ada harga</div>') + '</td>' +
    '<td><strong>' + (p.stock_quantity || 0) + '</strong>' +
      ((p.stock_quantity || 0) <= 0 ? '<div style="font-size:11px;color:var(--bc-warn);font-weight:700">Kosong</div>' : '') + '</td>' +
    '<td><span class="bc-badge ok">Aktif</span></td>' +
    '<td><button class="btn btn-line sm" onclick="openProductActions(' + p.master_sku_id + ')">Atur &rarr;</button></td>' +
  '</tr>').join('');

  const form = '<div class="section">' +
    '<div class="bc-eyebrow">TAMBAH PRODUK</div>' +
    '<h2 style="margin:8px 0 16px">Tambahkan Produk Pertama</h2>' +
    '<div class="row">' +
      '<div class="field"><label>Nama Produk</label><input id="np_name" placeholder="Contoh: Kopi Arabika 250gr"></div>' +
      '<div class="field"><label>SKU</label><input id="np_sku" placeholder="Contoh: KOPI-001"></div>' +
      '<div class="field"><label>Kategori</label><input id="np_cat" placeholder="Contoh: Minuman"></div>' +
    '</div>' +
    '<div class="row">' +
      '<div class="field"><label>Harga Jual (Rp)</label><input id="np_price" type="number" min="0" placeholder="25000"></div>' +
      '<div class="field"><label>Stok Awal</label><input id="np_stock" type="number" min="0" placeholder="100"></div>' +
      '<button class="btn btn-main" style="align-self:flex-end" onclick="createProductOnboard()">Simpan Produk &rarr;</button>' +
    '</div>' +
    '<div id="np_result" style="margin-top:8px"></div>' +
  '</div>';

  const body = form + '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">KATALOG MASTER</div>' +
        '<h3>Katalog Produk Bisnis</h3><div style="margin-top:4px"><a href="/docs#business-products" target="_blank" style="font-size:12px;color:var(--bc-indigo);text-decoration:none;font-weight:750">📖 Panduan Produk di /docs &rarr;</a></div>' +
        '<p>Kelola SKU master, harga retail, barcode, dan stok.</p>' +
      '</div>' +
      '<a href="#/onboard" class="btn btn-line sm">Buka Siapkan Toko &rarr;</a>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>SKU</th><th>Nama Produk</th><th>Kategori</th><th>Barcode</th><th>Harga Jual</th><th>Stok</th><th>Status</th><th>Aksi</th></tr>' +
      (prodRows || '<tr><td colspan="8" style="text-align:center;color:var(--bc-muted);padding:32px">Belum ada produk terdaftar. Gunakan formulir di atas untuk menambahkan produk pertama.</td></tr>') +
    '</table>' +
  '</div>';
  return page('Katalog Produk', 'Master produk, harga jual, dan stok.', body);
}

window.createProductOnboard = async function() {
  const name = (byId('np_name')||{}).value || '';
  const sku = (byId('np_sku')||{}).value || '';
  const cat = (byId('np_cat')||{}).value || '';
  const price = Number((byId('np_price')||{}).value || 0);
  const stock = Number((byId('np_stock')||{}).value || 0);
  const resEl = byId('np_result');
  if (!name.trim() || !sku.trim()) {
    resEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Nama dan SKU wajib diisi.</div>';
    return;
  }
  try {
    const r = await j('/bisnis/api/products', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), sku: sku.trim(), category: cat.trim(), price: price, barcode: '' })
    });
    if (!r.ok) { resEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(r.error || 'Terjadi kesalahan') + '</div>'; return; }
    // Add initial stock if requested
    if (stock > 0) {
      const sr = await j('/bisnis/api/stock/receive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ master_sku_id: r.master_sku_id, quantity: stock })
      });
      if (!sr.ok) { resEl.innerHTML = '<div style="padding:10px;background:var(--bc-ok-soft);color:var(--bc-ok);border-radius:10px;font-size:12px;font-weight:700">Produk dibuat, tetapi gagal menambah stok: ' + esc(sr.error || '') + '</div>'; return; }
    }
    resEl.innerHTML = '<div style="padding:10px;background:var(--bc-ok-soft);color:var(--bc-ok);border-radius:10px;font-size:12px;font-weight:700">Produk berhasil dibuat!</div>';
    route();
  } catch(e) {
    resEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(e.message) + '</div>';
  }
};

window.openProductActions = async function(masterSkuId) {
  const p = (PRODUCTS || []).find(x => Number(x.master_sku_id) === Number(masterSkuId));
  if (!p) return alert('Produk tidak ditemukan');
  const cur = window.__product_cur = {
    id: masterSkuId, name: p.name, sku: p.sku,
    price: p.price || 0, stock: p.stock_quantity || 0
  };
  const modal = byId('modalContainer');
  modal.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog">' +
      '<div class="bc-modal-head"><div><div class="bc-eyebrow">ATUR PRODUK</div><h3 style="font-size:19px;font-weight:850;margin:8px 0 0">' + esc(p.name) + '</h3></div>' +
      '<button class="bc-modal-close" onclick="closeModal()">&times;</button></div>' +
      '<div class="field" style="margin-bottom:16px"><label>Harga Jual (Rp)</label><input id="pa_price" type="number" min="0" value="' + (p.price || 0) + '"></div>' +
      '<button class="btn btn-main" style="width:100%;margin-bottom:14px" onclick="saveProductPrice()">Simpan Harga &rarr;</button>' +
      '<div class="field" style="margin-bottom:16px"><label>Tambah Stok</label><input id="pa_stock" type="number" min="0" placeholder="Jumlah stok yang ditambahkan"></div>' +
      '<button class="btn btn-line" style="width:100%" onclick="saveProductStock()">Tambah Stok &rarr;</button>' +
      '<div id="pa_result" style="margin-top:12px"></div>' +
    '</div></div>';
};

window.saveProductPrice = async function() {
  const rEl = byId('pa_result');
  const price = Number((byId('pa_price')||{}).value || 0);
  if (price <= 0) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">Harga harus lebih dari 0.</div>'; return; }
  try {
    const r = await j('/bisnis/api/price', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ master_sku_id: window.__product_cur.id, price: price }) });
    if (!r.ok) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">Gagal: ' + esc(r.error || '') + '</div>'; return; }
    rEl.innerHTML = '<div style="color:var(--bc-ok);font-size:12px;font-weight:700">Harga disimpan!</div>';
    closeModal(); route();
  } catch(e) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">' + esc(e.message) + '</div>'; }
};

window.saveProductStock = async function() {
  const rEl = byId('pa_result');
  const qty = Number((byId('pa_stock')||{}).value || 0);
  if (qty <= 0) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">Jumlah stok harus lebih dari 0.</div>'; return; }
  try {
    const r = await j('/bisnis/api/stock/receive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ master_sku_id: window.__product_cur.id, quantity: qty }) });
    if (!r.ok) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">Gagal: ' + esc(r.error || '') + '</div>'; return; }
    rEl.innerHTML = '<div style="color:var(--bc-ok);font-size:12px;font-weight:700">Stok ditambahkan!</div>';
    closeModal(); route();
  } catch(e) { rEl.innerHTML = '<div style="color:var(--bc-err);font-size:12px;font-weight:700">' + esc(e.message) + '</div>'; }
};

async function renderInventory(){
  let d;
  try { d = await j('/bisnis/api/pos'); } catch(e) {
    return page('Inventory', 'Inventori Multi-Cabang', '<div class="empty">Gagal memuat inventori: ' + esc(e.message) + '</div>');
  }
  const prods = d.products || [];
  const rows = prods.map(p => '<tr>' +
    '<td><strong>' + esc(p.sku) + '</strong></td>' +
    '<td>' + esc(p.name) + '</td>' +
    '<td>' + esc(p.category || 'Umum') + '</td>' +
    '<td><strong>' + (p.stock_quantity || 0) + '</strong></td>' +
    '<td>' + (p.safety_stock || 0) + '</td>' +
    '<td>' + ((p.stock_quantity || 0) > 0 ? '<span class="bc-badge ok">Tersedia</span>' : '<span class="bc-badge warn">Kosong</span>') + '</td>' +
  '</tr>').join('');

  const lowStock = prods.filter(p => (p.stock_quantity || 0) <= 5 && (p.stock_quantity || 0) > 0);
  const emptyStock = prods.filter(p => !(p.stock_quantity || 0));

  const body = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:20px">' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">TOTAL SKU AKTIF</div><div style="font-size:24px;font-weight:850;margin-top:6px">' + prods.length + ' Item</div></div>' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">SKU TERSEDIA</div><div style="font-size:24px;font-weight:850;margin-top:6px;color:var(--bc-ok)">' + (prods.length - emptyStock.length) + ' SKU</div></div>' +
    '<div class="bc-card" style="margin-bottom:0"><div class="bc-eyebrow">STOK MENIPIS (&le;5)</div><div style="font-size:24px;font-weight:850;margin-top:6px">' + lowStock.length + ' SKU</div></div>' +
  '</div>' +
  '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">STOK GUDANG &amp; CABANG</div>' +
        '<h3>Inventori &amp; Stok Multi-Lokasi</h3><div style="margin-top:4px"><a href="/docs#business-inventory" target="_blank" style="font-size:12px;color:var(--bc-indigo);text-decoration:none;font-weight:750">📖 Panduan Stok di /docs &rarr;</a></div>' +
        '<p>Pantau pergerakan stok real-time antar lokasi bisnis.</p>' +
      '</div>' +
      '<a href="#/transfers" class="btn btn-main sm">Transfer Stok &rarr;</a>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>SKU</th><th>Nama Produk</th><th>Kategori</th><th>Stok Saat Ini</th><th>Batas Minimum</th><th>Status</th></tr>' +
      (rows || '<tr><td colspan="6" style="text-align:center;color:var(--bc-muted);padding:32px">Belum ada data stok.</td></tr>') +
    '</table>' +
  '</div>';
  return page('Inventori Multi-Cabang', 'Pantau dan kelola stok produk antar cabang.', body);
}

async function renderTransfers(){
  const body = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">DISTRIBUSI INTERNAL</div>' +
        '<h3>Transfer Stok Antar Cabang</h3>' +
        '<p>Kirim stok dari gudang utama ke cabang operasional lainnya.</p>' +
      '</div>' +
    '</div>' +
    '<div class="empty">Belum ada riwayat transfer antar cabang pada periode ini.</div>' +
  '</div>';
  return page('Transfer Antar Cabang', 'Mutasi dan pengiriman stok antar cabang bisnis.', body);
}

async function renderRestaurant(){
  const body = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">OPERASIONAL RESTORAN</div>' +
        '<h3>Manajemen Meja &amp; Pesanan Dine-In</h3>' +
        '<p>Kelola alur pemesanan meja, pesanan dapur, dan split bill.</p>' +
      '</div>' +
      '<a href="#/kitchen" class="btn btn-main sm">Buka Layar KDS &rarr;</a>' +
    '</div>' +
    '<div class="empty">Tidak ada meja dengan pesanan terbuka saat ini.</div>' +
  '</div>';
  return page('Manajemen Restoran', 'Pengaturan meja, dine-in, dan pesanan restoran.', body);
}

async function renderKitchen(){
  const lanes = { NEW: { label: 'Baru', items: [] }, PREPARING: { label: 'Diproses', items: [] }, READY: { label: 'Siap', items: [] }, SERVED: { label: 'Selesai', items: [] } };
  const body = '<div class="kds">' + Object.entries(lanes).map(([k, l]) => '<div class="kds-lane"><h3>' + l.label + ' <span class="bc-badge info">' + l.items.length + '</span></h3>' + (l.items.length ? l.items.join('') : '<div class="dim" style="font-size:12px;padding:36px 12px;text-align:center">Tidak ada pesanan</div>') + '</div>').join('') + '</div>';
  return page('Kitchen / KDS', 'Kitchen Order Ticket & Antrean Pesanan Dapur.', body);
}

let REPORT_DAYS = 30;
let REPORT_TYPE = 'ALL';

window.setReportDays = function(d) {
  REPORT_DAYS = Number(d);
  route();
};

window.setReportType = function(t) {
  REPORT_TYPE = t;
  route();
};

async function renderReports(){
  let d;
  try {
    d = await j('/bisnis/api/reports?days=' + REPORT_DAYS);
  } catch (e) {
    return page('Laporan & Analitik', 'Business Suite', '<div class="empty">Gagal memuat laporan: ' + esc(e.message) + '</div>');
  }

  if (!d || !d.reports) {
    return page('Laporan & Analitik', 'Business Suite', '<div class="empty">Belum ada data laporan.</div>');
  }

  const r = d.reports.restaurant || { gross_sales: 0, cogs: 0, gross_profit: 0, gross_margin_pct: 0, order_count: 0, category_sales: [], channel_sales: [] };
  const ret = d.reports.retail || { gross_sales: 0, cogs: 0, gross_profit: 0, gross_margin_pct: 0, transaction_count: 0, category_sales: [] };
  const chan = d.reports.channel || { channels: [] };
  const branches = d.reports.branches || [];

  const totalGross = (r.gross_sales || 0) + (ret.gross_sales || 0);
  const totalCogs = (r.cogs || 0) + (ret.cogs || 0);
  const totalProfit = (r.gross_profit || 0) + (ret.gross_profit || 0);
  const totalTx = (r.order_count || 0) + (ret.transaction_count || 0);
  const totalMargin = totalGross > 0 ? Math.round((totalProfit / totalGross) * 100) : 0;
  const avgTicket = totalTx > 0 ? Math.round(totalGross / totalTx) : 0;

  const periodPillsDark = '<div class="period-pills-dark">' +
    '<button class="pill-dark ' + (REPORT_DAYS === 7 ? 'active' : '') + '" onclick="setReportDays(7)">7 Hari</button>' +
    '<button class="pill-dark ' + (REPORT_DAYS === 30 ? 'active' : '') + '" onclick="setReportDays(30)">30 Hari</button>' +
    '<button class="pill-dark ' + (REPORT_DAYS === 90 ? 'active' : '') + '" onclick="setReportDays(90)">90 Hari</button>' +
  '</div>';

  const typePills = '<div style="display:flex;align-items:center;gap:8px;background:#FFFFFF;padding:4px;border-radius:12px;border:1px solid var(--bc-border)">' +
    '<button class="pill ' + (REPORT_TYPE === 'ALL' ? 'active' : '') + '" style="padding:6px 12px;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;' + (REPORT_TYPE === 'ALL' ? 'background:var(--bc-indigo);color:#fff;' : 'background:transparent;color:var(--bc-muted);') + '" onclick="setReportType(&apos;ALL&apos;)">Semua</button>' +
    '<button class="pill ' + (REPORT_TYPE === 'RETAIL' ? 'active' : '') + '" style="padding:6px 12px;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;' + (REPORT_TYPE === 'RETAIL' ? 'background:var(--bc-indigo);color:#fff;' : 'background:transparent;color:var(--bc-muted);') + '" onclick="setReportType(&apos;RETAIL&apos;)">Retail</button>' +
    '<button class="pill ' + (REPORT_TYPE === 'RESTAURANT' ? 'active' : '') + '" style="padding:6px 12px;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;' + (REPORT_TYPE === 'RESTAURANT' ? 'background:var(--bc-indigo);color:#fff;' : 'background:transparent;color:var(--bc-muted);') + '" onclick="setReportType(&apos;RESTAURANT&apos;)">Restoran</button>' +
  '</div>';

  // DARK NAVY REPORT SUMMARY PANEL
  const navyReportPanel = '<div class="bc-navy-dashboard">' +
    '<div class="bc-navy-head">' +
      '<div class="bc-navy-title">' +
        '<div class="bc-eyebrow navy">LAPORAN KEUANGAN &middot; MULTI-BRANCH</div>' +
        '<h2>Ringkasan Laba Rugi &amp; Kinerja Penjualan</h2>' +
        '<p>Konsolidasi gross sales, harga pokok penjualan (COGS), margin keuntungan, dan omzet retail.</p>' +
      '</div>' +
      periodPillsDark +
    '</div>' +
    '<div class="bc-navy-kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:0">' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(totalGross) + '</div>' +
        '<div class="lbl">Gross Sales (' + REPORT_DAYS + 'D)</div>' +
        '<div class="sub-tag info">● Total Omzet</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(totalCogs) + '</div>' +
        '<div class="lbl">Harga Pokok (COGS)</div>' +
        '<div class="sub-tag info">● Beban Pokok</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val" style="color:var(--bc-ok)">Rp ' + money(totalProfit) + '</div>' +
        '<div class="lbl">Gross Profit (' + totalMargin + '% Margin)</div>' +
        '<div class="sub-tag">● Laba Kotor</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">' + money(totalTx) + '</div>' +
        '<div class="lbl">Total Transaksi <span class="kpi-help-btn" title="Jumlah total tiket transaksi penjualan yang berhasil diselesaikan">?</span></div>' +
        '<div class="sub-tag">● Order &amp; Kasir</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(avgTicket) + '</div>' +
        '<div class="lbl">Rata-rata Ticket (AOV) <span class="kpi-help-btn" title="Average Order Value: Rata-rata nilai belanja per transaksi">?</span></div>' +
        '<div class="sub-tag info">Per Order</div>' +
      '</div>' +
      '<div class="bc-navy-kpi">' +
        '<div class="val">Rp ' + money(ret.gross_sales) + '</div>' +
        '<div class="lbl">Penjualan Retail Kasir</div>' +
        '<div class="sub-tag info">POS Toko</div>' +
      '</div>' +
    '</div>' +
  '</div>';

  let allCategories = [];
  if (REPORT_TYPE === 'ALL' || REPORT_TYPE === 'RETAIL') {
    allCategories = allCategories.concat(ret.category_sales || []);
  }
  if (REPORT_TYPE === 'ALL' || REPORT_TYPE === 'RESTAURANT') {
    allCategories = allCategories.concat(r.category_sales || []);
  }

  const catRows = allCategories.length ? allCategories.map(x => '<tr>' +
    '<td><strong>' + esc(x.category) + '</strong></td>' +
    '<td><strong>Rp ' + money(x.gross_sales) + '</strong></td>' +
    '<td>' + money(x.qty_sold || x.transaction_count) + '</td>' +
    '<td>Rp ' + money(x.cogs || 0) + '</td>' +
  '</tr>').join('') : '<tr><td colspan="4" style="text-align:center;color:var(--bc-muted);padding:28px">Belum ada transaksi penjualan per kategori pada periode ini.</td></tr>';

  const catSection = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">KATALOG &amp; KATEGORI</div>' +
        '<h3>Penjualan per Kategori Produk</h3>' +
        '<p>Distribusi penjualan dan kontribusi beban pokok produk.</p>' +
      '</div>' +
      typePills +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>Kategori</th><th>Total Penjualan</th><th>Qty / Transaksi</th><th>COGS</th></tr>' +
      catRows +
    '</table>' +
  '</div>';

  const chanRows = (chan.channels || []).length ? chan.channels.map(x => '<tr>' +
    '<td><strong>' + esc(x.channel) + '</strong></td>' +
    '<td>' + money(x.order_count) + '</td>' +
    '<td><strong>Rp ' + money(x.gross_sales) + '</strong></td>' +
    '<td>Rp ' + money(x.discounts) + '</td>' +
    '<td>Rp ' + money(x.provider_fee) + '</td>' +
  '</tr>').join('') : '<tr><td colspan="5" style="text-align:center;color:var(--bc-muted);padding:28px">Belum ada transaksi penjualan kanal/delivery pada periode ini.</td></tr>';

  const chanSection = (REPORT_TYPE === 'ALL' || REPORT_TYPE === 'RESTAURANT') ? ('<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">KANAL DISTRIBUSI</div>' +
        '<h3>Penjualan per Kanal &amp; Delivery</h3>' +
        '<p>Pesanan dine-in, takeaway, dan integrasi aggregator pihak ketiga.</p>' +
      '</div>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>Kanal</th><th>Order</th><th>Gross Sales</th><th>Diskon</th><th>Biaya Provider</th></tr>' +
      chanRows +
    '</table>' +
  '</div>') : '';

  const branchRows = branches.length ? branches.map(b => '<tr>' +
    '<td><strong>' + esc(b.branch_name) + '</strong> <span style="font-size:11px;color:var(--bc-muted)">(' + esc(b.branch_code) + ')</span></td>' +
    '<td><strong>Rp ' + money(b.total) + '</strong></td>' +
    '<td>' + money(b.sales_count) + '</td>' +
  '</tr>').join('') : '<tr><td colspan="3" style="text-align:center;color:var(--bc-muted);padding:28px">Belum ada penjualan cabang pada periode ini.</td></tr>';

  const branchSection = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">PERBANDINGAN CABANG</div>' +
        '<h3>Performa Penjualan per Cabang</h3>' +
        '<p>Kontribusi pendapatan kotor dan volume transaksi masing-masing cabang.</p>' +
      '</div>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>Cabang</th><th>Total Penjualan</th><th>Jumlah Transaksi</th></tr>' +
      branchRows +
    '</table>' +
  '</div>';

  return navyReportPanel + catSection + chanSection + branchSection;
}

async function renderIntegrasi(){
  let d = {}, st = {}, botsData = {}, destsData = {};
  try {
    [d, st, botsData, destsData] = await Promise.all([
      j('/bisnis/api/business-integrasi').catch(() => ({})),
      j('/bisnis/api/telegram/status').catch(() => ({})),
      j('/bisnis/api/telegram/bots').catch(() => ({ bots: [] })),
      j('/bisnis/api/telegram/destinations').catch(() => ({ destinations: [] }))
    ]);
  } catch(e) {
    console.error('Gagal memuat integrasi:', e);
  }

  function statusBadge(s){
    const cls = s === 'SEGERA_HADIR' ? 'warn' : 'ok';
    const txt = s === 'SEGERA_HADIR' ? 'Segera Hadir' : 'Tersedia';
    return '<span class="bc-badge ' + cls + '">' + txt + '</span>';
  }
  const delivery = (d.delivery || []).map(x => '<tr><td>' + esc(x.provider) + '</td><td>' + statusBadge(x.status) + '</td><td>' + esc(x.auth) + '</td></tr>').join('');
  const pos = (d.pos || []).map(x => '<tr><td>' + esc(x.provider) + '</td><td>' + statusBadge(x.status) + '</td><td>' + esc(x.auth) + '</td></tr>').join('');

  // 1. GLOBAL TELEGRAM BOT
  const isPaired = st.paired;
  const globalActive = st.global_bot ? st.global_bot.active : (st.connectivity === 'ONLINE');
  const globalName = st.global_bot ? st.global_bot.username : (st.bot_username || 'Botconector_Bot');
  const pairedUserId = st.telegram_user_id;

  const globalCard = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">GLOBAL TELEGRAM BOT</div>' +
        '<h3>@' + esc(globalName) + '</h3>' +
        '<p>Bot resmi bersama BotConnector untuk intake transaksi instan dan notifikasi.</p>' +
      '</div>' +
      '<span class="bc-badge ' + (globalActive ? 'ok' : 'warn') + '">' + (globalActive ? 'AKTIF' : 'TIDAK AKTIF') + '</span>' +
    '</div>' +
    '<div style="background:#FAFBFD;border:1px solid var(--bc-border);border-radius:14px;padding:16px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">' +
      '<div>' +
        '<div style="font-size:11px;font-weight:800;color:var(--bc-muted2);text-transform:uppercase">Status Akun Anda</div>' +
        '<div style="font-size:14px;font-weight:750;color:var(--bc-ink);margin-top:2px">' +
          (isPaired ? '● Terhubung (Telegram User ID: ' + esc(pairedUserId) + ')' : '○ Belum terhubung') +
        '</div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        (!isPaired ? '<button class="btn btn-main sm" onclick="pairGlobalTelegram()">Hubungkan Akun Telegram &rarr;</button>' : '<button class="btn btn-line sm" onclick="unpairTelegram()">Putuskan Koneksi</button>') +
        '<button class="btn btn-line sm" onclick="openPairModal(\'global\', \'PRIVATE\')">+ Pribadi</button>' +
        '<button class="btn btn-line sm" onclick="openPairModal(\'global\', \'GROUP\')">+ Grup</button>' +
      '</div>' +
    '</div>' +
    '<div id="globalPairResult"></div>' +
  '</div>';

  // 2. BOT TELEGRAM KUSTOM (BYOB)
  const byobBots = botsData.bots || st.byob_bots || [];
  window._BYOB_BOTS = byobBots;
  window._GLOBAL_BOT_NAME = globalName;

  const byobCards = byobBots.length ? byobBots.map(b => '<div style="background:#FAFBFD;border:1px solid var(--bc-border);border-radius:16px;padding:20px;display:flex;flex-direction:column;justify-content:space-between;gap:16px">' +
    '<div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
        '<strong style="font-size:16px;color:var(--bc-ink)">@' + esc(b.bot_username) + '</strong>' +
        '<span class="bc-badge ' + (b.status === 'ACTIVE' ? 'ok' : 'warn') + '">' + esc(b.status || 'ACTIVE') + '</span>' +
      '</div>' +
      '<div style="font-size:13px;color:var(--bc-muted)">' +
        'Label: <strong style="color:var(--bc-ink)">' + esc(b.display_name || '-') + '</strong> &bull; ' + (b.destination_count || 0) + ' Tujuan Terhubung' +
      '</div>' +
    '</div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button class="btn btn-line sm" onclick="testBot(' + b.id + ')">Uji Koneksi</button>' +
      '<button class="btn btn-line sm" onclick="openPairModal(' + b.id + ', \'PRIVATE\')">+ Pribadi</button>' +
      '<button class="btn btn-line sm" onclick="openPairModal(' + b.id + ', \'GROUP\')">+ Grup</button>' +
      '<button class="btn btn-line sm" style="color:var(--bc-err);border-color:var(--bc-err-soft)" onclick="deleteBot(' + b.id + ', \'' + esc(b.bot_username) + '\')">Hapus</button>' +
    '</div>' +
    '<div id="botTestResult_' + b.id + '"></div>' +
  '</div>').join('') : '<div class="dim" style="grid-column:1/-1;padding:28px 12px;text-align:center">Belum ada bot Telegram kustom terdaftar.<br><small style="color:var(--bc-muted2)">Klik tombol "+ Tambah Bot Kustom" di atas untuk mendaftarkan bot dari @BotFather.</small></div>';

  const byobSection = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">BOT TELEGRAM KUSTOM (BYOB)</div>' +
        '<h3>Bot Telegram Mandiri (BYOB)</h3>' +
        '<p>Daftarkan bot Telegram milik bisnis Anda sendiri dari @BotFather. Token disimpan secara aman dengan enkripsi saat disimpan.</p>' +
      '</div>' +
      '<button class="btn btn-main sm" onclick="openAddBotModal()">+ Tambah Bot Kustom</button>' +
    '</div>' +
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">' +
      byobCards +
    '</div>' +
  '</div>';

  // 3. TUJUAN NOTIFIKASI (PRIBADI & GRUP)
  const destinations = destsData.destinations || st.destinations || [];
  window._DESTINATIONS = destinations;

  const destRows = destinations.length ? destinations.map(d => {
    const rulesList = (d.rules || []).filter(r => r.enabled).map(r => '<span class="bc-badge info" style="font-size:10px;margin-right:4px">' + esc(r.event_type) + '</span>').join('');
    const rulesParam = esc(JSON.stringify(d.rules || []));
    return '<tr>' +
      '<td><strong>' + esc(d.display_name || ('Chat ' + d.chat_id)) + '</strong><div style="font-size:11px;color:var(--bc-muted2)">ID: ' + esc(d.chat_id) + '</div></td>' +
      '<td><span class="bc-badge ' + (d.chat_type === 'PRIVATE' ? 'ok' : 'info') + '">' + (d.chat_type === 'PRIVATE' ? 'Pribadi' : 'Grup') + '</span></td>' +
      '<td><strong>@' + esc(d.bot_username || 'Botconector_Bot') + '</strong></td>' +
      '<td>' + esc(d.branch_name || 'Semua Cabang') + '</td>' +
      '<td>' + (rulesList || '<span style="color:var(--bc-muted2);font-size:11.5px">Belum ada rule</span>') + '</td>' +
      '<td>' +
        '<div style="display:flex;gap:6px">' +
          '<button class="btn btn-line sm" style="font-size:11.5px;padding:4px 10px" onclick="openRulesModal(' + d.id + ', \'' + esc(d.display_name || ('Chat ' + d.chat_id)) + '\', ' + rulesParam + ')">Atur Rules</button>' +
          '<button class="btn btn-line sm" style="color:var(--bc-err);border-color:var(--bc-err-soft);padding:4px 8px" onclick="deleteDest(' + d.id + ', \'' + esc(d.display_name || ('Chat ' + d.chat_id)) + '\')">&times;</button>' +
        '</div>' +
      '</td>' +
    '</tr>';
  }).join('') : '<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--bc-muted)">Belum ada tujuan notifikasi terdaftar. Klik "+ Hubungkan Pribadi" atau "+ Hubungkan Grup".</td></tr>';

  const destSection = '<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">TUJUAN NOTIFIKASI</div>' +
        '<h3>Tujuan Notifikasi (Pribadi &amp; Grup)</h3>' +
        '<p>Daftar akun Telegram dan grup yang dikonfigurasi untuk menerima laporan berkala dan peringatan stok.</p>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        '<button class="btn btn-main sm" onclick="openPairModal(null, \'PRIVATE\')">+ Hubungkan Pribadi</button>' +
        '<button class="btn btn-line sm" onclick="openPairModal(null, \'GROUP\')">+ Hubungkan Grup</button>' +
      '</div>' +
    '</div>' +
    '<table class="bc-table">' +
      '<tr><th>Tujuan / Chat</th><th>Tipe</th><th>Bot</th><th>Cabang</th><th>Notifikasi Aktif</th><th>Aksi</th></tr>' +
      destRows +
    '</table>' +
  '</div>';

  // 4. LOWER BENTO: DELIVERY AGGREGATOR & POS HARDWARE
  const aggSection = '<div class="bc-lower-bento" style="margin-top:24px">' +
    '<div class="bc-card">' +
      '<div class="bc-card-head">' +
        '<div>' +
          '<div class="bc-eyebrow">DELIVERY &amp; AGGREGATOR</div>' +
          '<h3>Aggregator Online</h3>' +
          '<p>Integrasi sinkronisasi menu dan pesanan online.</p>' +
        '</div>' +
      '</div>' +
      '<table class="bc-table"><tr><th>Provider</th><th>Status</th><th>Autentikasi</th></tr>' +
      (delivery || '<tr><td colspan="3" class="dim">Kosong</td></tr>') +
      '</table>' +
    '</div>' +
    '<div class="bc-card">' +
      '<div class="bc-card-head">' +
        '<div>' +
          '<div class="bc-eyebrow">POS HARDWARE</div>' +
          '<h3>Mesin POS &amp; Kasir</h3>' +
          '<p>Integrasi hardware kasir dan terminal pihak ketiga.</p>' +
        '</div>' +
      '</div>' +
      '<table class="bc-table"><tr><th>Provider</th><th>Status</th><th>Autentikasi</th></tr>' +
      (pos || '<tr><td colspan="3" class="dim">Kosong</td></tr>') +
      '</table>' +
    '</div>' +
  '</div>';

  const body = '<div style="display:flex;flex-direction:column;gap:24px">' +
    globalCard +
    byobSection +
    destSection +
    aggSection +
  '</div>' +
  '<div id="modalContainer"></div>';

  return page('Integrasi Sistem', 'Pusat integrasi saluran Telegram V2, bot kustom (BYOB), delivery aggregator, dan perangkat kasir.', body);
}

// ------------------------------------------------------------ TELEGRAM ACTIONS & MODALS
window.pairGlobalTelegram = async function() {
  const el = byId('globalPairResult');
  if (el) el.innerHTML = '<span class="dim">Membuat tautan pairing...</span>';
  try {
    const res = await j('/bisnis/api/telegram/pair', { method: 'POST' });
    if (res.ok && res.pairing_url) {
      if (el) el.innerHTML = '<div style="margin-top:10px;padding:16px;background:var(--bc-indigo-soft);border:1px solid #c7d2fe;border-radius:14px;font-size:13px">' +
        '<strong>Tautan Pairing Akun:</strong><br><div style="font-size:12px;color:var(--bc-muted);margin:4px 0 10px">Kirim perintah /start pada Telegram bot untuk menyelesaikan pairing.</div>' +
        '<a href="' + res.pairing_url + '" target="_blank" class="btn btn-main sm">Buka Bot Telegram &rarr;</a>' +
      '</div>';
    } else {
      if (el) el.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">' + esc(res.error || 'Gagal pairing') + '</div>';
    }
  } catch(e) {
    if (el) el.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(e.message) + '</div>';
  }
};

window.unpairTelegram = async function() {
  if (!confirm('Putuskan koneksi akun Telegram?')) return;
  try {
    await j('/bisnis/api/telegram/unpair', { method: 'POST' });
    route();
  } catch(e) {
    alert('Gagal unpair: ' + e.message);
  }
};

// ------------------- ADD BYOB BOT MODAL
window.openAddBotModal = function() {
  const c = byId('modalContainer');
  if (!c) return;
  c.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog">' +
      '<div class="bc-modal-head">' +
        '<div>' +
          '<div class="bc-eyebrow">DAFTARKAN BOT KUSTOM</div>' +
          '<h3 style="font-size:20px;font-weight:850;color:var(--bc-ink);margin:4px 0 0">Tambah Bot Telegram (BYOB)</h3>' +
        '</div>' +
        '<button class="bc-modal-close" onclick="closeModal()">&times;</button>' +
      '</div>' +
      '<form onsubmit="submitAddBot(event)" style="display:flex;flex-direction:column;gap:16px">' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Nama Internal / Label</label>' +
          '<input type="text" id="byobDisplayName" class="search" style="width:100%" placeholder="Contoh: Bot Toko Cabang Utama" required>' +
        '</div>' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Bot Token dari @BotFather</label>' +
          '<input type="text" id="byobToken" class="search" style="width:100%" placeholder="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ..." required autocomplete="off">' +
        '</div>' +
        '<div style="background:#FAFBFD;border:1px solid var(--bc-border);border-radius:12px;padding:14px;font-size:12px;color:var(--bc-muted);line-height:1.6">' +
          '<strong style="color:var(--bc-ink);display:block;margin-bottom:4px">Cara Mendapatkan Token dari @BotFather:</strong>' +
          '1. Buka Telegram dan cari <strong>@BotFather</strong>.<br>' +
          '2. Kirim pesan <code>/newbot</code>.<br>' +
          '3. Tentukan nama tampilan dan username bot (akhiri dengan _bot).<br>' +
          '4. Salin token HTTP API yang diberikan.<br>' +
          '5. Tempelkan token pada kolom di atas.' +
        '</div>' +
        '<div id="addBotError"></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px">' +
          '<button type="button" class="btn btn-line sm" onclick="closeModal()">Batal</button>' +
          '<button type="submit" id="btnSubmitBot" class="btn btn-main sm">Verifikasi &amp; Tambahkan Bot &rarr;</button>' +
        '</div>' +
      '</form>' +
    '</div>' +
  '</div>';
};

window.submitAddBot = async function(event) {
  event.preventDefault();
  const token = (byId('byobToken').value || '').trim();
  const name = (byId('byobDisplayName').value || '').trim();
  const errEl = byId('addBotError');
  const btn = byId('btnSubmitBot');
  if (errEl) errEl.innerHTML = '';
  if (btn) { btn.disabled = true; btn.textContent = 'Memverifikasi token...'; }
  try {
    const res = await j('/bisnis/api/telegram/bots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bot_token: token, display_name: name })
    });
    if (res.ok) {
      closeModal();
      route();
    } else {
      if (errEl) errEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">' + esc(res.error || 'Gagal mendaftarkan bot') + '</div>';
    }
  } catch(e) {
    if (errEl) errEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(e.message) + '</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Verifikasi & Tambahkan Bot →'; }
  }
};

// ------------------- TEST BYOB BOT
window.testBot = async function(botId) {
  const resEl = byId('botTestResult_' + botId);
  if (resEl) resEl.innerHTML = '<div style="font-size:12px;color:var(--bc-indigo);margin-top:8px">Menguji koneksi getMe &amp; Webhook...</div>';
  try {
    const res = await j('/bisnis/api/telegram/bots/' + botId + '/test', { method: 'POST' });
    if (res.ok) {
      const me = res.me || {};
      const wh = res.webhook || {};
      if (resEl) resEl.innerHTML = '<div style="margin-top:8px;padding:12px;background:var(--bc-ok-soft);border:1px solid #bbf7d0;border-radius:12px;font-size:12px;color:#166534">' +
        '<strong>✓ Bot API Terhubung:</strong> @' + esc(me.username) + ' (ID: ' + esc(me.id) + ')<br>' +
        '<strong>✓ Webhook Aktif:</strong> ' + (wh.url ? '<span style="word-break:break-all">' + esc(wh.url) + '</span>' : 'Siap') + '<br>' +
        'Pending updates: ' + (wh.pending_update_count || 0) +
      '</div>';
    } else {
      if (resEl) resEl.innerHTML = '<div style="margin-top:8px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(res.error || 'Uji koneksi gagal') + '</div>';
    }
  } catch(e) {
    if (resEl) resEl.innerHTML = '<div style="margin-top:8px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(e.message) + '</div>';
  }
};

window.deleteBot = async function(botId, username) {
  if (!confirm('Hapus pendaftaran bot @' + username + '? Seluruh tujuan terkait bot ini akan dinonaktifkan.')) return;
  try {
    const res = await j('/bisnis/api/telegram/bots/' + botId, { method: 'DELETE' });
    if (res.ok) { route(); }
    else { alert('Gagal menghapus bot: ' + (res.error || 'Terjadi kesalahan')); }
  } catch(e) {
    alert('Error: ' + e.message);
  }
};

// ------------------- PAIR DESTINATION MODAL (EXPLICIT BOT SELECTION)
window.openPairModal = function(preselectedBotId, defaultType) {
  const c = byId('modalContainer');
  if (!c) return;
  const byobList = window._BYOB_BOTS || [];
  const globalName = window._GLOBAL_BOT_NAME || 'Botconector_Bot';
  const branchList = BRANCHES || [];

  let botOptions = '<option value="global" ' + (preselectedBotId === 'global' || !preselectedBotId ? 'selected' : '') + '>@' + esc(globalName) + ' (Global Bot)</option>';
  byobList.forEach(b => {
    botOptions += '<option value="' + b.id + '" ' + (Number(preselectedBotId) === Number(b.id) ? 'selected' : '') + '>@' + esc(b.bot_username) + ' (' + esc(b.display_name || 'BYOB') + ')</option>';
  });

  let branchOptions = '<option value="">Semua Cabang</option>';
  branchList.forEach(br => {
    branchOptions += '<option value="' + br.id + '">' + esc(br.name) + '</option>';
  });

  const isGroup = defaultType === 'GROUP';

  c.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog">' +
      '<div class="bc-modal-head">' +
        '<div>' +
          '<div class="bc-eyebrow">HUBUNGKAN TUJUAN</div>' +
          '<h3 style="font-size:20px;font-weight:850;color:var(--bc-ink);margin:4px 0 0">' + (isGroup ? 'Hubungkan Grup Telegram' : 'Hubungkan Chat Pribadi') + '</h3>' +
        '</div>' +
        '<button class="bc-modal-close" onclick="closeModal()">&times;</button>' +
      '</div>' +
      '<form onsubmit="generatePairingLink(event)" style="display:flex;flex-direction:column;gap:16px">' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Pilih Bot Telegram</label>' +
          '<select id="pairBotSelect" class="search" style="width:100%">' + botOptions + '</select>' +
        '</div>' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Tipe Tujuan</label>' +
          '<select id="pairTypeSelect" class="search" style="width:100%">' +
            '<option value="PRIVATE" ' + (!isGroup ? 'selected' : '') + '>Pribadi (Private Chat)</option>' +
            '<option value="GROUP" ' + (isGroup ? 'selected' : '') + '>Grup / Supergroup</option>' +
          '</select>' +
        '</div>' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Cabang Notifikasi</label>' +
          '<select id="pairBranchSelect" class="search" style="width:100%">' + branchOptions + '</select>' +
        '</div>' +
        '<div>' +
          '<label style="display:block;font-size:12px;font-weight:750;color:var(--bc-ink);margin-bottom:6px">Fokus / Scope Notifikasi</label>' +
          '<select id="pairPurposeSelect" class="search" style="width:100%">' +
            '<option value="GENERAL">Umum (Semua Notifikasi Bisnis)</option>' +
            '<option value="ALERTS">Peringatan Stok Saja</option>' +
            '<option value="FINANCE">Laporan Keuangan &amp; Kasir Saja</option>' +
          '</select>' +
        '</div>' +
        '<div id="pairModalResult"></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:8px">' +
          '<button type="button" class="btn btn-line sm" onclick="closeModal()">Batal</button>' +
          '<button type="submit" id="btnGenPair" class="btn btn-main sm">Buat Tautan Pairing &rarr;</button>' +
        '</div>' +
      '</form>' +
    '</div>' +
  '</div>';
};

window.generatePairingLink = async function(event) {
  event.preventDefault();
  const botVal = byId('pairBotSelect').value;
  const destType = byId('pairTypeSelect').value;
  const branchVal = byId('pairBranchSelect').value;
  const purposeVal = byId('pairPurposeSelect').value;
  const resEl = byId('pairModalResult');
  const btn = byId('btnGenPair');
  if (resEl) resEl.innerHTML = '<span class="dim">Membuat token pairing...</span>';
  if (btn) { btn.disabled = true; }

  try {
    const payload = {
      destination_type: destType,
      telegram_bot_id: botVal === 'global' ? null : Number(botVal),
      branch_id: branchVal ? Number(branchVal) : null,
      purpose: purposeVal
    };
    const res = await j('/bisnis/api/telegram/destinations/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.ok && res.pairing_url) {
      if (resEl) resEl.innerHTML = '<div style="margin-top:10px;padding:16px;background:var(--bc-indigo-soft);border:1px solid #c7d2fe;border-radius:14px;font-size:13px">' +
        '<strong>Tautan Pairing Siap:</strong>' +
        '<div style="font-size:12px;color:var(--bc-muted);margin:6px 0 12px">' +
          (destType === 'GROUP' ? 'Klik tombol di bawah untuk menambahkan bot ke grup Telegram Anda.' : 'Klik tombol di bawah dan tekan Start pada Telegram.') +
        '</div>' +
        '<div style="display:flex;gap:10px">' +
          '<a href="' + res.pairing_url + '" target="_blank" class="btn btn-main sm">Buka di Telegram &rarr;</a>' +
          '<button type="button" class="btn btn-line sm" onclick="closeModal();route()">Selesai</button>' +
        '</div>' +
      '</div>';
    } else {
      if (resEl) resEl.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(res.error || 'Terjadi kesalahan') + '</div>';
    }
  } catch(e) {
    if (resEl) resEl.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(e.message) + '</div>';
  } finally {
    if (btn) { btn.disabled = false; }
  }
};

// ------------------- RULES MANAGEMENT MODAL
window.openRulesModal = function(destId, destName, currentRules) {
  const c = byId('modalContainer');
  if (!c) return;
  const rulesMap = {};
  (currentRules || []).forEach(r => { rulesMap[r.event_type] = r.enabled; });

  const events = [
    { type: 'LOW_STOCK', label: 'Peringatan Stok Menipis', desc: 'Dikirim saat stok produk mencapai atau di bawah safety threshold.' },
    { type: 'OUT_OF_STOCK', label: 'Peringatan Stok Habis', desc: 'Dikirim saat stok produk habis bernilai 0.' },
    { type: 'DAILY_SUMMARY', label: 'Ringkasan Penjualan Harian', desc: 'Ringkasan omzet dan transaksi berkala.' },
    { type: 'DAILY_SUMMARY_FINAL', label: 'Rekapitulasi Akhir Hari & Penutupan Kasir', desc: 'Laporan komprehensif penutupan harian toko/cabang.' }
  ];

  const checkboxes = events.map(ev => {
    const isChecked = rulesMap[ev.type] === true;
    return '<label style="display:flex;align-items:flex-start;gap:12px;padding:12px 14px;background:#FAFBFD;border:1px solid var(--bc-border);border-radius:12px;cursor:pointer">' +
      '<input type="checkbox" name="rule_event" value="' + ev.type + '" ' + (isChecked ? 'checked' : '') + ' style="margin-top:3px;accent-color:var(--bc-indigo)">' +
      '<div>' +
        '<strong style="font-size:13.5px;color:var(--bc-ink);display:block">' + esc(ev.label) + '</strong>' +
        '<span style="font-size:12px;color:var(--bc-muted);line-height:1.4;display:block;margin-top:2px">' + esc(ev.desc) + '</span>' +
      '</div>' +
    '</label>';
  }).join('');

  c.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog">' +
      '<div class="bc-modal-head">' +
        '<div>' +
          '<div class="bc-eyebrow">ATURAN NOTIFIKASI</div>' +
          '<h3 style="font-size:20px;font-weight:850;color:var(--bc-ink);margin:4px 0 0">Kelola Aturan — ' + esc(destName) + '</h3>' +
        '</div>' +
        '<button class="bc-modal-close" onclick="closeModal()">&times;</button>' +
      '</div>' +
      '<form onsubmit="submitRules(' + destId + ', event)" style="display:flex;flex-direction:column;gap:12px">' +
        '<div style="font-size:13px;color:var(--bc-muted);margin-bottom:4px">Pilih notifikasi otomatis yang ingin dikirimkan ke tujuan ini:</div>' +
        checkboxes +
        '<div id="rulesModalResult"></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:12px">' +
          '<button type="button" class="btn btn-line sm" onclick="closeModal()">Batal</button>' +
          '<button type="submit" id="btnSubmitRules" class="btn btn-main sm">Simpan Aturan Notifikasi &rarr;</button>' +
        '</div>' +
      '</form>' +
    '</div>' +
  '</div>';
};

window.submitRules = async function(destId, event) {
  event.preventDefault();
  const checkboxes = qsa('input[name="rule_event"]:checked');
  const selectedRules = checkboxes.map(cb => cb.value);
  const resEl = byId('rulesModalResult');
  const btn = byId('btnSubmitRules');
  if (btn) { btn.disabled = true; btn.textContent = 'Menyimpan...'; }
  try {
    const res = await j('/bisnis/api/telegram/destinations/' + destId + '/rules', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rules: selectedRules })
    });
    if (res.ok) {
      closeModal();
      route();
    } else {
      if (resEl) resEl.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(res.error || 'Terjadi kesalahan') + '</div>';
    }
  } catch(e) {
    if (resEl) resEl.innerHTML = '<div style="margin-top:10px;padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(e.message) + '</div>';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Simpan Aturan Notifikasi →'; }
  }
};

window.deleteDest = async function(destId, name) {
  if (!confirm('Hapus tujuan notifikasi ' + name + '?')) return;
  try {
    const res = await j('/bisnis/api/telegram/destinations/' + destId, { method: 'DELETE' });
    if (res.ok) { route(); }
    else { alert('Gagal menghapus tujuan: ' + (res.error || 'Terjadi kesalahan')); }
  } catch(e) {
    alert('Error: ' + e.message);
  }
};


window.openBizGuideModal = function(tab) {
  tab = tab || 'workflow';
  let c = byId('modalContainer');
  if (!c) {
    c = document.createElement('div');
    c.id = 'modalContainer';
    document.body.appendChild(c);
  }

  let bodyContent = '';
  if (tab === 'workflow') {
    bodyContent = '<div class="bc-workflow-box">' +
      '<div style="font-weight:800;font-size:14px;color:var(--bc-ink);margin-bottom:6px">1. Alur Operasional Toko &amp; Retail</div>' +
      '<p style="font-size:13px;color:var(--bc-muted);line-height:1.5">Alur data standar mulai dari pencatatan barang masuk hingga laporan analitik keuangan.</p>' +
      '<div class="bc-step-flow">' +
        '<span class="bc-flow-pill">1. Produk (SKU)</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">2. Harga Jual</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">3. Stok Awal</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">4. POS Kasir</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">5. Penjualan</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">6. Stok Berkurang</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">7. Laporan Otomatis</span>' +
      '</div>' +
      '<div class="bc-tip-box"><strong>Dampak Nyata:</strong> Setiap transaksi yang diselesaikan kasir akan memotong stok di cabang secara real-time, membuat struk penjualan, dan menambahkan omzet ke dashboard tanpa input manual ulang.</div>' +
    '</div>' +
    '<div class="bc-workflow-box" style="margin-top:14px">' +
      '<div style="font-weight:800;font-size:14px;color:var(--bc-ink);margin-bottom:6px">2. Alur Restoran &amp; Dapur (KDS/KOT)</div>' +
      '<p style="font-size:13px;color:var(--bc-muted);line-height:1.5">Alur pemesanan meja makan (dine-in/takeaway) yang terhubung ke dapur.</p>' +
      '<div class="bc-step-flow">' +
        '<span class="bc-flow-pill">1. Menu Resto</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">2. Pilih Meja</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">3. Pesanan Kasir</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">4. KOT (Tiket Dapur)</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">5. KDS (Layar Masak)</span><span class="bc-flow-arrow">&rarr;</span>' +
        '<span class="bc-flow-pill">6. Pembayaran</span>' +
      '</div>' +
      '<div style="font-size:12.5px;color:var(--bc-muted);line-height:1.6;margin-top:8px">' +
        '<strong>KOT (Kitchen Order Ticket):</strong> Tiket ringkasan pesanan yang dikirim untuk proses masak dapur.<br>' +
        '<strong>KDS (Kitchen Display System):</strong> Tampilan layar dapur yang membantu koki memantau pesanan yang harus disiapkan.' +
      '</div>' +
    '</div>';
  } else if (tab === 'modules') {
    bodyContent = '<div style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:14px;color:var(--bc-ink)">Profil Bisnis &amp; Cabang</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:4px 0 6px">Menentukan identitas bisnis pada struk dan memisahkan operasional kasir per lokasi fisik.</p>' +
        '<div style="font-size:12px;color:var(--bc-indigo);font-weight:700">Hasil: Transaksi dan stok tercatat rapi per cabang.</div>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:14px;color:var(--bc-ink)">Produk &amp; SKU Master</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:4px 0 6px">SKU (Stock Keeping Unit) adalah kode unik internal toko untuk membedakan produk. Produk siap diberi harga dan stok.</p>' +
        '<div style="font-size:12px;color:var(--bc-indigo);font-weight:700">Hasil: Produk dapat dicari melalui nama atau scan barcode di POS.</div>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:14px;color:var(--bc-ink)">Stok Awal (Contoh Edukatif)</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:4px 0 6px">Masukkan jumlah barang fisik yang tersedia sebelum berjualan. Contoh: Jika Stok Awal 50 unit, saat POS menjual 2 unit, stok otomatis berkurang menjadi 48 unit.</p>' +
        '<div style="font-size:12px;color:var(--bc-indigo);font-weight:700">Hasil: Persediaan akurat tanpa hitung manual ulang.</div>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:14px;color:var(--bc-ink)">Kasir POS &amp; Transaksi Pertama</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:4px 0 6px">Buka kasir, masukkan item ke keranjang, pilih pembayaran tunai/QRIS, dan selesaikan transaksi.</p>' +
        '<div style="font-size:12px;color:var(--bc-indigo);font-weight:700">Hasil: Struk dibuat, stok terpotong, omzet dashboard terisi.</div>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:14px;color:var(--bc-ink)">Transfer Antar Cabang</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:4px 0 6px">Pindahkan stok dari Cabang Utama ke Cabang Lain dengan dokumen mutasi otomatis (Stok asal berkurang &rarr; Stok tujuan bertambah).</p>' +
        '<div style="font-size:12px;color:var(--bc-indigo);font-weight:700">Hasil: Riwayat perpindahan barang tercatat transparan.</div>' +
      '</div>' +
    '</div>';
  } else if (tab === 'troubleshooting') {
    bodyContent = '<div style="display:flex;flex-direction:column;gap:12px">' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:13.5px;color:var(--bc-ink);display:block;margin-bottom:4px">❓ Produk tidak muncul di layar POS?</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:0"><strong>Penyebab:</strong> Produk belum memiliki harga jual aktif atau status dinonaktifkan.<br><strong>Solusi:</strong> Buka menu Katalog Produk &rarr; klik tombol harga &rarr; simpan harga retail (>0).</p>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:13.5px;color:var(--bc-ink);display:block;margin-bottom:4px">❓ Stok barang tidak berkurang setelah penjualan?</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:0"><strong>Penyebab:</strong> Transaksi belum selesai atau terjadi kendala sinkronisasi.<br><strong>Solusi:</strong> Pastikan klik "Bayar Sekarang" hingga nomor struk tercetak dan status menjadi COMPLETED.</p>' +
      '</div>' +
      '<div class="bc-workflow-box">' +
        '<strong style="font-size:13.5px;color:var(--bc-ink);display:block;margin-bottom:4px">❓ Laporan dan Dashboard masih kosong?</strong>' +
        '<p style="font-size:12.5px;color:var(--bc-muted);margin:0"><strong>Penyebab:</strong> Belum ada transaksi penjualan yang diselesaikan.<br><strong>Solusi:</strong> Selesaikan transaksi pertama Anda di POS kasir, dashboard akan otomatis terisi real-time.</p>' +
      '</div>' +
    '</div>';
  }

  c.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog" style="max-width:680px">' +
      '<div class="bc-modal-head">' +
        '<div>' +
          '<div class="bc-eyebrow">PANDUAN RESMI</div>' +
          '<h3 style="font-size:22px;font-weight:850;color:var(--bc-ink);margin:4px 0 0">Panduan Operasional Business Suite</h3>' +
        '</div>' +
        '<button class="bc-modal-close" onclick="closeModal()">&times;</button>' +
      '</div>' +
      '<div class="bc-guide-tabs">' +
        '<button class="bc-guide-tab-btn ' + (tab === 'workflow' ? 'active' : '') + '" onclick="openBizGuideModal(\'workflow\')">Alur Kerja Retail &amp; Resto</button>' +
        '<button class="bc-guide-tab-btn ' + (tab === 'modules' ? 'active' : '') + '" onclick="openBizGuideModal(\'modules\')">Panduan Modul</button>' +
        '<button class="bc-guide-tab-btn ' + (tab === 'troubleshooting' ? 'active' : '') + '" onclick="openBizGuideModal(\'troubleshooting\')">Masalah Umum (FAQ)</button>' +
      '</div>' +
      '<div style="max-height:60vh;overflow-y:auto;padding-right:4px">' + bodyContent + '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:20px;border-top:1px solid var(--bc-border);padding-top:16px;flex-wrap:wrap;gap:10px">' +
        '<div style="display:flex;gap:8px">' +
          '<a href="#/onboard" class="btn btn-main sm" onclick="closeModal()">Buka Siapkan Toko &rarr;</a>' +
          '<a href="/docs#business-overview" target="_blank" class="btn btn-line sm">Dokumentasi Lengkap /docs &rarr;</a>' +
        '</div>' +
        '<button class="btn btn-line sm" onclick="closeModal()">Tutup</button>' +
      '</div>' +
    '</div>' +
  '</div>';
};

window.showSaleSuccessModal = function(res, lines, total) {
  const c = byId('modalContainer');
  if (!c) return;
  const sale = res.sale || {};
  const receiptNo = sale.receipt_number || ('# ' + sale.id);

  const lineItemsHtml = lines.map(it => {
    return '<div style="display:flex;justify-content:space-between;font-size:13px;padding:6px 0;border-bottom:1px dashed #E2E8F0">' +
      '<span>' + esc(it.name || ('Item SKU #' + it.master_sku_id)) + ' &times; ' + it.quantity + '</span>' +
      '<strong>Rp ' + money(it.quantity * it.unit_price) + '</strong>' +
    '</div>';
  }).join('');

  c.innerHTML = '<div class="bc-modal-overlay" onclick="if(event.target===this)closeModal()">' +
    '<div class="bc-modal-dialog" style="max-width:580px">' +
      '<div class="bc-modal-head">' +
        '<div>' +
          '<div class="bc-eyebrow" style="color:var(--bc-ok)">TRANSAKSI SELESAI</div>' +
          '<h3 style="font-size:22px;font-weight:850;color:var(--bc-ink);margin:4px 0 0">Transaksi Berhasil Dicatat!</h3>' +
        '</div>' +
        '<button class="bc-modal-close" onclick="closeModal()">&times;</button>' +
      '</div>' +
      '<div style="background:#F8FAFC;border:1px solid var(--bc-border);border-radius:12px;padding:16px;margin-bottom:16px">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
          '<span style="font-size:12px;color:var(--bc-muted);font-weight:750;text-transform:uppercase">Nomor Struk</span>' +
          '<strong style="font-size:14px;font-family:monospace;color:var(--bc-indigo)">' + esc(receiptNo) + '</strong>' +
        '</div>' +
        '<div style="margin:10px 0">' + lineItemsHtml + '</div>' +
        '<div style="display:flex;justify-content:space-between;align-items:center;font-size:16px;margin-top:8px;padding-top:8px;border-top:1px solid var(--bc-border)">' +
          '<strong>Total Pembayaran (CASH)</strong>' +
          '<strong style="color:var(--bc-ok);font-size:18px">Rp ' + money(total) + '</strong>' +
        '</div>' +
      '</div>' +
      '<div class="bc-tip-box" style="margin-bottom:20px">' +
        '<div style="font-weight:800;margin-bottom:4px">✓ Dampak Operasional Berhasil Dijalankan:</div>' +
        '<ul style="margin:0;padding-left:20px;line-height:1.6;font-size:12.5px">' +
          '<li>Penjualan tercatat ke database &amp; nomor struk unik diterbitkan.</li>' +
          '<li>Stok produk di inventori cabang otomatis terpotong sesuai kuantitas.</li>' +
          '<li>Omzet harian, transaksi, dan grafik di Dashboard otomatis bertambah.</li>' +
          '<li>Laporan keuangan laba rugi langsung terbarui secara real-time.</li>' +
        '</ul>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">' +
        '<a href="/bisnis/api/receipt/' + (sale.id || '') + '" target="_blank" class="btn btn-main sm">🖨 Lihat / Cetak Struk &rarr;</a>' +
        '<div style="display:flex;gap:8px">' +
          '<a href="#/dashboard" class="btn btn-line sm" onclick="closeModal()">Lihat Dashboard</a>' +
          '<button class="btn btn-line sm" onclick="closeModal()">Transaksi Baru</button>' +
        '</div>' +
      '</div>' +
    '</div>' +
  '</div>';
};

window.closeModal = function() {
  const c = byId('modalContainer');
  if (c) c.innerHTML = '';
};

async function renderOnboard(){
  let state;
  try {
    state = await j('/bisnis/api/onboarding');
  } catch(e) {
    return page('Siapkan Toko','Konfigurasi operasional bisnis Anda.','<div class="empty">Gagal memuat status: '+esc(e.message)+'</div>');
  }
  if (!state || !state.onboarding) {
    return page('Siapkan Toko','Konfigurasi operasional bisnis Anda.','<div class="empty">Belum ada bisnis aktif. Lengkapi pembuatan bisnis terlebih dahulu.</div>');
  }
  const o = state.onboarding;
  const done = k => o[k] && o[k].done;

  function step(n, eyebrow, title, explanation, ctaHtml, statusHtml){
    return '<div class="onboard-step">' +
      '<div>' +
        '<div class="step-num">'+n+'</div>' +
        '<div class="bc-eyebrow">'+eyebrow+'</div>' +
        '<h3 style="font-size:17px;font-weight:850;margin:6px 0 8px">'+title+'</h3>' +
        '<p style="font-size:13px;color:var(--bc-muted);line-height:1.5">'+explanation+'</p>' +
      '</div>' +
      '<div style="margin-top:16px">'+statusHtml+'</div>' +
      '<div style="margin-top:12px">'+(ctaHtml||'')+'</div>' +
    '</div>';
  }
  const okBadge = '<span class="bc-badge ok">● Selesai</span>';
  const waitBadge = '<span class="bc-badge warn">● Belum Selesai</span>';

  // Products are managed in the Products module; expose a quick inline creator.
  const productCta = done('produk')
    ? ''
    : '<a href="#/products" class="btn btn-main sm">Tambahkan Produk &rarr;</a>';

  // Price + stock act on the first sellable product (if any exists).
  let priceCta = done('harga') ? '' : '<a href="#/products" class="btn btn-main sm">Atur Harga Jual &rarr;</a>';
  let stockCta = done('stok') ? '' : '<a href="#/products" class="btn btn-main sm">Tambah Stok &rarr;</a>';

  const posCta = o.ready
    ? ''
    : (done('produk') && done('harga') && done('stok'))
      ? '<a href="#/pos" class="btn btn-main sm">Buka Kasir POS &rarr;</a>'
      : '<span class="dim" style="font-size:12px">Siapkan produk, harga, dan stok terlebih dahulu.</span>';

  const telegramCta = done('telegram')
    ? ''
    : '<a href="#/integrasi" class="btn btn-line sm">Buka Integrasi Telegram (opsional)</a>';

  let stepsHtml =
    step(1,'PROFIL BISNIS','1. Profil Bisnis',
      'Nama dan identitas resmi bisnis Anda. Digunakan pada struk belanja kasir dan kepala laporan keuangan.',
      '', done('profil') ? okBadge : waitBadge) +
    step(2,'CABANG PERTAMA','2. Cabang &amp; Gudang Utama',
      'Lokasi fisik operasional toko pertama Anda. Setiap cabang memiliki kasir dan persediaan stok terpisah.',
      '', done('cabang') ? okBadge : waitBadge) +
    step(3,'PRODUK PERTAMA','3. Katalog Produk &amp; SKU',
      'Tambahkan barang yang akan dijual. SKU (Stock Keeping Unit) adalah kode internal unik untuk identifikasi barang.',
      productCta, done('produk') ? okBadge : waitBadge) +
    step(4,'HARGA JUAL','4. Harga Jual Retail',
      'Tetapkan nominal harga jual setiap produk agar otomatis muncul saat dipilih kasir di POS.',
      priceCta, done('harga') ? okBadge : waitBadge) +
    step(5,'STOK AWAL','5. Stok Awal Gudang',
      'Masukkan persediaan fisik awal barang. Contoh: Stok Awal 50 unit &rarr; kasir menjual 2 unit di POS &rarr; sisa stok otomatis menjadi 48 unit.',
      stockCta, done('stok') ? okBadge : waitBadge) +
    step(6,'KASIR / POS','6. Siapkan Kasir POS',
      'Buka terminal kasir POS untuk menguji pemindaian barcode atau pemilihan produk.',
      posCta, done('pos') ? okBadge : waitBadge) +
    step(7,'TRANSAKSI PERTAMA','7. Penjualan Pertama Selesai',
      'Selesaikan transaksi pertama di kasir untuk mengaktifkan grafik performa penjualan dan laporan laba rugi.',
      done('first_sale') ? '' : '<a href="#/pos" class="btn btn-main sm">Selesaikan Transaksi &rarr;</a>', done('first_sale') ? okBadge : waitBadge) +
    step(8,'TELEGRAM NOTIFIKASI','8. Integrasi Telegram',
      'Aktifkan notifikasi otomatis peringatan stok menipis dan rekap omzet harian langsung ke akun Telegram Anda (BYOB).',
      telegramCta, (done('telegram') ? '<span class="bc-badge ok">● Terhubung</span>' : '<span class="bc-badge info">● Opsional</span>'));

  const readyHtml = o.ready
    ? '<div class="bc-navy-dashboard" style="background:var(--bc-ok);border:none">' +
        '<div class="bc-navy-head"><div class="bc-navy-title">' +
        '<div class="bc-eyebrow navy">SELESAI</div>' +
        '<h2>TOKO SIAP DIGUNAKAN</h2>' +
        '<p>Semua langkah penting sudah lengkap. Anda bisa langsung mengoperasikan toko.</p>' +
        '</div></div>' +
        '<div style="display:flex;gap:10px;flex-wrap:wrap">' +
        '<a href="#/dashboard" class="btn btn-main sm">Buka Dashboard &rarr;</a>' +
        '<a href="#/pos" class="btn btn-main sm" style="background:#fff;color:var(--bc-ink)">Buka Kasir POS &rarr;</a>' +
        '</div>' +
      '</div>'
    : '<div class="bc-navy-dashboard">' +
        '<div class="bc-navy-head"><div class="bc-navy-title">' +
        '<div class="bc-eyebrow navy">PERSIAPAN TOKO</div>' +
        '<h2>Lengkapi langkah berikut untuk siap berjualan</h2>' +
        '<p>Ikuti langkah secara berurutan. Setiap langkah selesai akan ditandai otomatis dari data toko Anda.</p>' +
        '</div></div>' +
      '</div>';

  const body = readyHtml + '<div class="onboard-grid">' + stepsHtml + '</div>';
  return page('Siapkan Toko','Langkah mudah menyiapkan toko pertama Anda.',body);
}

window.handleIntake = async function(e) {
  e.preventDefault();
  const form = e.target;
  const fd = new FormData(form);
  const resEl = byId('intakeResult');
  if (resEl) resEl.innerHTML = '<span class="dim">Memproses file...</span>';
  try {
    const res = await fetch('/bisnis/api/intake/draft', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.ok) {
      if (resEl) resEl.innerHTML = '<div style="padding:10px;background:var(--bc-ok-soft);color:var(--bc-ok);border-radius:10px;font-size:12px;font-weight:700">File berhasil divalidasi! Total baris: ' + (data.total_rows || 0) + '</div>';
    } else {
      if (resEl) resEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Gagal: ' + esc(data.error || 'Terjadi kesalahan') + '</div>';
    }
  } catch(err) {
    if (resEl) resEl.innerHTML = '<div style="padding:10px;background:var(--bc-err-soft);color:var(--bc-err);border-radius:10px;font-size:12px;font-weight:700">Error: ' + esc(err.message) + '</div>';
  }
};

async function renderQuick(){
  const body='<div class="bc-card">' +
    '<div class="bc-card-head">' +
      '<div>' +
        '<div class="bc-eyebrow">MODE CEPAT</div>' +
        '<h3>POS Kasir Cepat (Minimalis)</h3>' +
        '<p>Dirancang untuk perangkat kasir layar sentuh atau perangkat mobile.</p>' +
      '</div>' +
      '<a href="#/pos" class="btn btn-main sm">Buka POS Lengkap &rarr;</a>' +
    '</div>' +
    '<div class="empty">Mode cepat aktif. Gunakan POS standar untuk katalog visual lengkap.</div>' +
  '</div>';
  return page('Quick Mode','Antarmuka kasir cepat dan ringkas.',body);
}

function updateBranchSelect(branches){
  BRANCHES=branches||[];
  const sel=byId('branchSelect');
  if(!sel)return;
  sel.innerHTML=(BRANCHES.length?BRANCHES.map(b=>'<option value="'+b.id+'">'+esc(b.name)+'</option>').join(''):'<option>Cabang Utama</option>');
}

async function route(){
  const hash=(location.hash||'#/dashboard').replace(/^#\/?/,'').toLowerCase();
  const v=hash.split('/')[0]||'dashboard';
  const links=qsa('#nav a');
  links.forEach(a=>a.classList.toggle('active',a.getAttribute('data-view')===v));
  const main=byId('main');
  const pageTitle=byId('pageTitle');
  const pageSub=byId('pageSub');
  if(pageTitle)pageTitle.textContent=VIEWS[v]||'Business Suite';
  if(pageSub)pageSub.textContent='Business Suite · Multi-Branch Operations';
  if(!main)return;
  main.innerHTML='<div class="empty" style="border:none">Memuat...</div>';
  try{
    if(v==='dashboard')main.innerHTML=await renderDashboard();
    else if(v==='pos')main.innerHTML=await renderPos();
    else if(v==='orders')main.innerHTML=await renderOrders();
    else if(v==='products')main.innerHTML=await renderProducts();
    else if(v==='inventory')main.innerHTML=await renderInventory();
    else if(v==='transfers')main.innerHTML=await renderTransfers();
    else if(v==='restaurant')main.innerHTML=await renderRestaurant();
    else if(v==='kitchen')main.innerHTML=await renderKitchen();
    else if(v==='reports')main.innerHTML=await renderReports();
    else if(v==='integrasi')main.innerHTML=await renderIntegrasi();
    else if(v==='onboard')main.innerHTML=await renderOnboard();
    else if(v==='quick')main.innerHTML=await renderQuick();
    else main.innerHTML=await renderDashboard();
  }catch(e){
    main.innerHTML='<div class="empty" style="color:var(--bc-err);border-color:var(--bc-err)">Error memuat tampilan: '+esc(e.message)+'</div>';
  }
}

window.addEventListener('hashchange',route);
window.addEventListener('load',route);
byId('syncBtn').addEventListener('click',async()=>{
  try{
    const r=await j('/bisnis/api/offline/sync',{method:'POST'});
    alert('Sync berhasil: '+JSON.stringify(r.sync||{}));
  }catch(e){
    alert('Gagal sync: '+e.message);
  }
});
</script><script src="/__bc_shared_design_v1/v2/support_ai_widget.js" defer></script></body></html>
"""

