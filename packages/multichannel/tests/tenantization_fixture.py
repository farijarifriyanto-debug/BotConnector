"""Create deterministic synthetic Business Suite tenant fixtures.

This module only touches the explicitly marked tenantization-test accounts and
businesses. It is intended for a live isolated acceptance run, not production
customer provisioning.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from botconnector_multichannel.persistence.db import koneksi


PASSWORD = "TEST_ONLY_DUMMY_PASSWORD_DO_NOT_USE"
PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=2$Y2FdkqzkaXTya8XSNxO1/g$"
    "iL8V1/BKWAkKq2cOndEUf3c9msBbkgEMwavcp30BzC4"
)
PRODUCT_SLUG = "business-suite"
USERS = {
    "a": ("11111111-1111-4111-8111-111111111111", "tenantization-test-a@example.com", "Tenantization Test A"),
    "b": ("22222222-2222-4222-8222-222222222222", "tenantization-test-b@example.com", "Tenantization Test B"),
    "staff": ("33333333-3333-4333-8333-333333333333", "tenantization-test-staff@example.com", "Tenantization Test Staff"),
    "no_access": ("44444444-4444-4444-8444-444444444444", "tenantization-test-no-access@example.com", "Tenantization Test No Access"),
}


def _first(cur, sql: str, params: tuple[Any, ...]) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"fixture query returned no row: {sql}")
    return next(iter(row.values()))


def _login(email: str) -> httpx.Client:
    test_ip = {
        USERS["a"][1]: "198.18.0.10",
        USERS["b"][1]: "198.18.0.11",
        USERS["staff"][1]: "198.18.0.12",
        USERS["no_access"][1]: "198.18.0.13",
    }[email]
    client = httpx.Client(
        base_url="http://127.0.0.1",
        timeout=10.0,
        headers={"X-Forwarded-For": test_ip},
    )
    response = client.post(
        "http://127.0.0.1:8050/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    response.raise_for_status()
    token = response.cookies.get("bc_session")
    if not token:
        raise RuntimeError(f"Core login did not issue bc_session for {email}")
    # Core marks the production cookie Secure; local acceptance calls use HTTP.
    client.cookies.clear()
    client.cookies.set("bc_session", token, domain="127.0.0.1", path="/")
    return client


def _provision(email: str) -> tuple[dict[str, Any], httpx.Client]:
    client = _login(email)
    response = client.post(
        "http://127.0.0.1:18199/bisnis/api/provision",
        json={"name": f"Tenantization {email.split('@', 1)[0]}", "business_type": "HYBRID"},
    )
    response.raise_for_status()
    return response.json(), client


def _seed_business(cur, business_id: int, label: str) -> dict[str, int]:
    code = label.upper()
    warehouse_id = _first(
        cur,
        """INSERT INTO multichannel.warehouse (code, name, is_default)
           VALUES (%s, %s, TRUE) ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name
           RETURNING id""",
        (f"TENANTIZATION-{code}-WH", f"Tenantization {label} Warehouse"),
    )
    branch_id = _first(
        cur,
        """INSERT INTO local_business.branch
           (business_id, code, name, warehouse_id, branch_type)
           VALUES (%s, 'MAIN', %s, %s, 'HYBRID')
           ON CONFLICT (business_id, code) DO UPDATE SET name=EXCLUDED.name,
             warehouse_id=EXCLUDED.warehouse_id
           RETURNING id""",
        (business_id, f"Tenantization {label} Branch", warehouse_id),
    )
    register_id = _first(
        cur,
        """INSERT INTO local_business.register (branch_id, code, name, device_id)
           VALUES (%s, 'MAIN', %s, %s)
           ON CONFLICT (branch_id, code) DO UPDATE SET name=EXCLUDED.name,
             device_id=EXCLUDED.device_id
           RETURNING id""",
        (branch_id, f"Tenantization {label} Register", f"tenantization-{label.lower()}-device"),
    )
    cashier_id = _first(
        cur,
        """INSERT INTO local_business.cashier (business_id, code, name, role)
           VALUES (%s, 'MAIN', %s, 'CASHIER')
           ON CONFLICT (business_id, code) DO UPDATE SET name=EXCLUDED.name
           RETURNING id""",
        (business_id, f"Tenantization {label} Cashier"),
    )
    product_id = _first(
        cur,
        """INSERT INTO multichannel.product (name, category)
           VALUES (%s, 'TENANTIZATION_TEST')
           ON CONFLICT (name, category) DO UPDATE SET updated_at=now()
           RETURNING id""",
        (f"Tenantization {label} Product",),
    )
    sku_id = _first(
        cur,
        """INSERT INTO multichannel.master_sku (sku, product_id, barcode)
           VALUES (%s, %s, %s)
           ON CONFLICT (sku) DO UPDATE SET barcode=EXCLUDED.barcode
           RETURNING id""",
        (f"TENANT-{code}-SKU", product_id, f"8999{business_id:08d}"),
    )
    cur.execute(
        """INSERT INTO local_business.business_product (business_id, master_sku_id)
           VALUES (%s, %s) ON CONFLICT (business_id, master_sku_id)
           DO UPDATE SET active=TRUE""",
        (business_id, sku_id),
    )
    cur.execute(
        """INSERT INTO local_business.retail_selling_price
           (business_id, master_sku_id, selling_price, currency, active)
           VALUES (%s, %s, 125000, 'IDR', TRUE)
           ON CONFLICT (business_id, master_sku_id) WHERE active=TRUE
           DO UPDATE SET selling_price=EXCLUDED.selling_price""",
        (business_id, sku_id),
    )
    cur.execute(
        """INSERT INTO multichannel.inventory_balance
           (master_sku_id, warehouse_id, on_hand, available)
           VALUES (%s, %s, 50, 50)
           ON CONFLICT (master_sku_id, warehouse_id) DO UPDATE
           SET on_hand=50, available=50""",
        (sku_id, warehouse_id),
    )
    category_id = _first(
        cur,
        """INSERT INTO local_business.menu_category (business_id, name)
           VALUES (%s, 'Tenantization Test Menu')
           ON CONFLICT (business_id, name) DO UPDATE SET sort_order=0
           RETURNING id""",
        (business_id,),
    )
    menu_item_id = _first(
        cur,
        """INSERT INTO local_business.menu_item
           (business_id, category_id, name, price, is_stocked, stocked_sku_id)
           VALUES (%s, %s, %s, 125000, TRUE, %s)
           ON CONFLICT (business_id, name) DO UPDATE SET price=EXCLUDED.price,
             stocked_sku_id=EXCLUDED.stocked_sku_id
           RETURNING id""",
        (business_id, category_id, f"Tenantization {label} Dish", sku_id),
    )
    table_id = _first(
        cur,
        """INSERT INTO local_business.restaurant_table (branch_id, name, capacity)
           VALUES (%s, 'T-01', 4)
           ON CONFLICT (branch_id, name) DO UPDATE SET capacity=EXCLUDED.capacity
           RETURNING id""",
        (branch_id,),
    )
    sale_id = _first(
        cur,
        """INSERT INTO local_business.sale
           (tenant_id, business_id, branch_id, register_id, cashier_id,
            receipt_number, sale_type, subtotal, total, amount_tendered,
            change_due, client_event_id, device_id, origin, sales_channel)
           VALUES (%s, %s, %s, %s, %s, %s, 'RETAIL', 125000, 125000,
                   125000, 0, %s, %s, 'ONLINE', 'POS')
           ON CONFLICT (business_id, device_id, client_event_id)
           DO UPDATE SET total=EXCLUDED.total
           RETURNING id""",
        (
            f"tenantization-test-{label.lower()}", business_id, branch_id,
            register_id, cashier_id, f"TZ-{code}-RECEIPT", f"TZ-{code}-SALE",
            f"tenantization-{label.lower()}-device",
        ),
    )
    cur.execute(
        """INSERT INTO local_business.sale_line
           (sale_id, master_sku_id, sku, description, quantity, unit_price,
            line_total, line_no)
           VALUES (%s, %s, %s, %s, 1, 125000, 125000, 1)
           ON CONFLICT DO NOTHING""",
        (sale_id, sku_id, f"TENANT-{code}-SKU", f"Tenantization {label} Product"),
    )
    cur.execute(
        """INSERT INTO local_business.sale_finance
           (sale_id, invoice_number, invoice_id, journal_id, customer_code, total)
           VALUES (%s, %s, %s, %s, %s, 125000)
           ON CONFLICT (sale_id) DO UPDATE SET total=EXCLUDED.total""",
        (sale_id, f"TZ-{code}-INV", f"tz-{label.lower()}-invoice", f"tz-{label.lower()}-journal", f"TZ-{code}"),
    )
    order_id = _first(
        cur,
        """INSERT INTO local_business.restaurant_order
           (tenant_id, business_id, branch_id, register_id, cashier_id,
            table_id, order_number, order_type, guest_count, subtotal, total,
            client_event_id, device_id, sales_channel)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'DINE_IN', 2, 125000, 125000,
                   %s, %s, 'DINE_IN')
           ON CONFLICT (business_id, order_number) DO UPDATE SET total=EXCLUDED.total
           RETURNING id""",
        (
            f"tenantization-test-{label.lower()}", business_id, branch_id,
            register_id, cashier_id, table_id, f"TZ-{code}-ORDER",
            f"TZ-{code}-ORDER-EVENT", f"tenantization-{label.lower()}-device",
        ),
    )
    cur.execute(
        """INSERT INTO local_business.restaurant_order_line
           (order_id, menu_item_id, menu_item_name, quantity, unit_price, line_total)
           VALUES (%s, %s, %s, 1, 125000, 125000) ON CONFLICT DO NOTHING""",
        (order_id, menu_item_id, f"Tenantization {label} Dish"),
    )
    kot_id = _first(
        cur,
        """INSERT INTO local_business.kot (business_id, order_id, kot_number)
           VALUES (%s, %s, %s)
           ON CONFLICT (business_id, kot_number) DO UPDATE SET status='NEW'
           RETURNING id""",
        (business_id, order_id, f"TZ-{code}-KOT"),
    )
    cur.execute(
        """INSERT INTO local_business.expense
           (business_id, expense_number, category, amount, payment_source,
            payment_account_code, expense_account_code, description, idempotency_key,
            created_by)
           VALUES (%s, %s, 'TENANTIZATION_TEST', 25000, 'CASH', 'CASH',
                   'EXPENSE', %s, %s, %s)
           ON CONFLICT (expense_number) DO UPDATE SET amount=EXCLUDED.amount""",
        (business_id, f"TZ-{code}-EXPENSE", f"Tenantization {label} Expense", f"tz-{label.lower()}-expense", f"user:{code}"),
    )
    connector_id = _first(
        cur,
        """INSERT INTO local_business.webhook_connector
           (business_id, name, direction, kind, endpoint)
           VALUES (%s, %s, 'OUTBOUND', 'TEST', %s)
           ON CONFLICT (business_id, name) DO UPDATE SET endpoint=EXCLUDED.endpoint
           RETURNING id""",
        (business_id, f"Tenantization {label} Connector", f"https://example.invalid/{label.lower()}"),
    )
    cur.execute(
        """INSERT INTO local_business.offline_queue
           (tenant_id, business_id, branch_id, register_id, device_id,
            client_event_id, event_type, payload)
           VALUES (%s, %s, %s, %s, %s, %s, 'TEST_FIXTURE', %s)
           ON CONFLICT (business_id, device_id, client_event_id) DO NOTHING""",
        (
            f"tenantization-test-{label.lower()}", business_id, branch_id,
            register_id, f"tenantization-{label.lower()}-device",
            f"TZ-{code}-OFFLINE", json.dumps({"fixture": label, "sale_id": sale_id}),
        ),
    )
    return {
        "business_id": business_id,
        "branch_id": branch_id,
        "register_id": register_id,
        "cashier_id": cashier_id,
        "warehouse_id": warehouse_id,
        "master_sku_id": sku_id,
        "sale_id": sale_id,
        "order_id": order_id,
        "kot_id": kot_id,
        "menu_item_id": menu_item_id,
        "table_id": table_id,
        "connector_id": connector_id,
    }


def create_fixtures() -> dict[str, Any]:
    clients: dict[str, httpx.Client] = {}
    provision: dict[str, Any] = {}
    with koneksi() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for user_id, email, display_name in USERS.values():
                    cur.execute(
                        """INSERT INTO public.users
                           (id, email, display_name, status, email_verified_at)
                           VALUES (%s, %s, %s, 'active', now())
                           ON CONFLICT (id) DO UPDATE SET email=EXCLUDED.email,
                             display_name=EXCLUDED.display_name, status='active',
                             email_verified_at=COALESCE(users.email_verified_at, now())""",
                        (user_id, email, display_name),
                    )
                    cur.execute(
                        """INSERT INTO public.user_credentials (user_id, password_hash)
                           VALUES (%s, %s)
                           ON CONFLICT (user_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
                             failed_attempts=0, locked_until=NULL""",
                        (user_id, PASSWORD_HASH),
                    )
                    if email != USERS["no_access"][1]:
                        product_id = _first(cur, "SELECT id FROM public.products WHERE slug=%s", (PRODUCT_SLUG,))
                        cur.execute(
                            """INSERT INTO public.user_product_access (user_id, product_id, access_status, role)
                               VALUES (%s, %s, 'active', 'owner')
                               ON CONFLICT (user_id, product_id) DO UPDATE SET access_status='active', role='owner'""",
                            (user_id, product_id),
                        )
    for key in ("a", "b"):
        result, clients[key] = _provision(USERS[key][1])
        provision[key] = result

    with koneksi() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                business_a = int(provision["a"]["business_id"])
                business_b = int(provision["b"]["business_id"])
                cur.execute(
                    """INSERT INTO local_business.business_membership
                       (business_id, user_id, role, status)
                       VALUES (%s, %s, 'STAFF', 'ACTIVE')
                       ON CONFLICT (business_id, user_id) DO UPDATE SET role='STAFF', status='ACTIVE'""",
                    (business_a, USERS["staff"][0]),
                )
                resources = {
                    "a": _seed_business(cur, business_a, "A"),
                    "b": _seed_business(cur, business_b, "B"),
                }
    for client in clients.values():
        client.close()
    return {
        "password": PASSWORD,
        "users": {key: {"id": value[0], "email": value[1]} for key, value in USERS.items()},
        "provision": provision,
        "resources": resources,
    }


if __name__ == "__main__":
    print(json.dumps(create_fixtures(), indent=2, sort_keys=True))
