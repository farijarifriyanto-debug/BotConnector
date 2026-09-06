"""Local Business Suite — entitas inti (business/branch/register/cashier/shift/customer).

Semua operasi idempoten. Lokasi stok = `multichannel.warehouse`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..persistence.db import koneksi as _pg


def _now():
    return datetime.now(timezone.utc)


# ============================================================ business
def upsert_business(*, tenant_id: str, code: str, name: str = "",
                    business_type: str = "RETAIL", currency: str = "IDR",
                    timezone: str = "Asia/Jakarta") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.business
               (tenant_id, code, name, business_type, currency, timezone)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (tenant_id, code) DO UPDATE SET
                 name=EXCLUDED.name, business_type=EXCLUDED.business_type,
                 currency=EXCLUDED.currency, timezone=EXCLUDED.timezone,
                 updated_at=now()
               RETURNING id, tenant_id, code, name, business_type, currency, timezone""",
            (tenant_id, code, name, business_type, currency, timezone))
        r = cur.fetchone()
        c.commit()
        return r


def get_business(business_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.business WHERE id=%s", (business_id,))
        return cur.fetchone()


def list_business(tenant_id: str) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.business WHERE tenant_id=%s ORDER BY code", (tenant_id,))
        return cur.fetchall()


# ============================================================ branch
def upsert_branch(*, business_id: int, code: str, name: str = "",
                  warehouse_id: int, branch_type: str = "RETAIL",
                  address: str = "") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.branch
               (business_id, code, name, warehouse_id, branch_type, address)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, code) DO UPDATE SET
                 name=EXCLUDED.name, warehouse_id=EXCLUDED.warehouse_id,
                 branch_type=EXCLUDED.branch_type, address=EXCLUDED.address,
                 updated_at=now()
               RETURNING id, business_id, code, name, warehouse_id, branch_type""",
            (business_id, code, name, warehouse_id, branch_type, address))
        r = cur.fetchone()
        c.commit()
        return r


def get_branch(branch_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.branch WHERE id=%s", (branch_id,))
        return cur.fetchone()


def list_branch(business_id: int) -> list[dict]:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.branch WHERE business_id=%s ORDER BY code", (business_id,))
        return cur.fetchall()


# ============================================================ register
def upsert_register(*, branch_id: int, code: str, name: str = "",
                    device_id: str = "") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.register
               (branch_id, code, name, device_id)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (branch_id, code) DO UPDATE SET
                 name=EXCLUDED.name, device_id=EXCLUDED.device_id
               RETURNING id, branch_id, code, name, device_id""",
            (branch_id, code, name, device_id))
        r = cur.fetchone()
        c.commit()
        return r


def get_register(register_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.register WHERE id=%s", (register_id,))
        return cur.fetchone()


def get_register_by_device(device_id: str) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.register WHERE device_id=%s", (device_id,))
        return cur.fetchone()


# ============================================================ cashier
def upsert_cashier(*, business_id: int, code: str, name: str = "",
                   role: str = "CASHIER", pin_hash: str = "") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.cashier
               (business_id, code, name, role, pin_hash)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, code) DO UPDATE SET
                 name=EXCLUDED.name, role=EXCLUDED.role, pin_hash=EXCLUDED.pin_hash
               RETURNING id, business_id, code, name, role""",
            (business_id, code, name, role, pin_hash))
        r = cur.fetchone()
        c.commit()
        return r


def get_cashier(cashier_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.cashier WHERE id=%s", (cashier_id,))
        return cur.fetchone()


# ============================================================ shift
def open_shift(*, register_id: int, cashier_id: int | None = None,
               opening_cash=0) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.shift (register_id, cashier_id, opening_cash)
               VALUES (%s,%s,%s)
               ON CONFLICT (register_id) WHERE status='OPEN' DO NOTHING
               RETURNING id, register_id, cashier_id, opening_cash, status""",
            (register_id, cashier_id, opening_cash))
        r = cur.fetchone()
        c.commit()
        if not r:
            cur = c.cursor()
            cur.execute(
                "SELECT * FROM local_business.shift WHERE register_id=%s AND status='OPEN'",
                (register_id,))
            r = cur.fetchone()
        return r


def close_shift(*, shift_id: int, closing_cash, expected_cash=None,
                note: str = "") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """UPDATE local_business.shift
               SET closed_at=now(), closing_cash=%s, expected_cash=%s,
                   status='CLOSED', note=%s
               WHERE id=%s AND status='OPEN'
               RETURNING id, register_id, opening_cash, closing_cash, expected_cash, status""",
            (closing_cash, expected_cash, note, shift_id))
        r = cur.fetchone()
        c.commit()
        return r


def get_open_shift(register_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.shift WHERE register_id=%s AND status='OPEN'",
            (register_id,))
        return cur.fetchone()


def record_cash_movement(*, shift_id: int, movement_type: str, amount,
                         reason: str = "", actor: str = "") -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.cash_movement
               (shift_id, movement_type, amount, reason, actor)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (shift_id, movement_type, amount, reason, actor))
        r = cur.fetchone()
        c.commit()
        return r


# ============================================================ customer
def upsert_customer(*, business_id: int, code: str, name: str = "",
                    phone: str = "", email: str = "", credit_limit=0) -> dict:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.customer
               (business_id, code, name, phone, email, credit_limit)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (business_id, code) DO UPDATE SET
                 name=EXCLUDED.name, phone=EXCLUDED.phone, email=EXCLUDED.email,
                 credit_limit=EXCLUDED.credit_limit
               RETURNING id, business_id, code, name, phone, credit_limit""",
            (business_id, code, name, phone, email, credit_limit))
        r = cur.fetchone()
        c.commit()
        return r


def get_customer(customer_id: int) -> dict | None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute("SELECT * FROM local_business.customer WHERE id=%s", (customer_id,))
        return cur.fetchone()


# ============================================================ audit
def catat_audit(event_type: str, *, actor: str = "", tenant_id: str = "",
                business_id: int | None = None, branch_id: int | None = None,
                payload: dict | None = None) -> None:
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.audit_log
               (event_type, actor, tenant_id, business_id, branch_id, payload)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (event_type, actor, tenant_id, business_id, branch_id,
             __import__("json").dumps(payload or {}, default=str)))
        c.commit()
