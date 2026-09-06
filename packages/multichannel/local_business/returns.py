"""Retail return/refund business workflow.

A return restocks the returned goods to the branch location and records a
sale_return. Idempotent per client_event_id. Finance reversal is handled by
the finance layer (not here).
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg
from . import core
from . import inventory as inv


def create_return(
    *,
    tenant_id: str, business_id: int, branch_id: int, warehouse_id: int,
    sale_id: int, reason: str = "", actor: str = "",
    client_event_id: str = "", device_id: str = "",
    lines: list[dict] | None = None,  # [{sale_line_id, quantity}]
) -> dict:
    """Return goods from a completed sale. Restocks location. Idempotent."""
    with _pg() as c:
        cur = c.cursor()
        if client_event_id and device_id:
            cur.execute(
                """SELECT id FROM local_business.sale_return
                   WHERE branch_id=%s AND device_id=%s AND client_event_id=%s""",
                (branch_id, device_id, client_event_id))
            ada = cur.fetchone()
            if ada:
                cur.execute("SELECT * FROM local_business.sale_return WHERE id=%s", (ada["id"],))
                r = cur.fetchone()
                r["duplicate"] = True
                c.commit()
                return r

        cur.execute(
            "SELECT * FROM local_business.sale WHERE id=%s AND business_id=%s FOR UPDATE",
            (sale_id, business_id))
        s = cur.fetchone()
        if not s:
            raise KeyError(f"sale {sale_id} tidak ada")
        if s["status"] != "COMPLETED":
            raise ValueError(f"sale {sale_id} status {s['status']} tidak bisa diretur")
        cur.execute(
            """SELECT 1 FROM local_business.branch
               WHERE id=%s AND business_id=%s AND warehouse_id=%s""",
            (branch_id, business_id, warehouse_id))
        if not cur.fetchone():
            raise KeyError("branch/warehouse bukan milik business")

        cur.execute(
            "SELECT nextval('local_business.return_seq') AS n")
        n = cur.fetchone()["n"]
        return_number = f"RET-{branch_id}-{n:06d}"

        # resolve lines to return (default: all lines)
        cur.execute(
            "SELECT * FROM local_business.sale_line WHERE sale_id=%s ORDER BY line_no", (sale_id,))
        sale_lines = cur.fetchall()
        if lines is None:
            lines = [{"sale_line_id": sl["id"], "quantity": sl["quantity"]} for sl in sale_lines]

        total_refund = 0
        cur.execute(
            """INSERT INTO local_business.sale_return
               (sale_id, branch_id, return_number, reason, total_refund, status,
                client_event_id, device_id)
               VALUES (%s,%s,%s,%s,0,'COMPLETED',%s,%s) RETURNING id""",
            (sale_id, branch_id, return_number, reason, client_event_id, device_id))
        return_id = cur.fetchone()["id"]

        for rl in lines:
            sl = next((x for x in sale_lines if x["id"] == rl["sale_line_id"]), None)
            if not sl:
                raise KeyError(f"sale_line {rl['sale_line_id']} tidak ada")
            qty = int(rl["quantity"])
            if qty <= 0 or qty > sl["quantity"]:
                raise ValueError(f"qty retur {qty} tidak valid (max {sl['quantity']})")
            line_total = qty * float(sl["unit_price"])
            total_refund += line_total
            cur.execute(
                """INSERT INTO local_business.sale_return_line
                   (return_id, sale_line_id, master_sku_id, quantity, unit_price, line_total)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (return_id, sl["id"], sl["master_sku_id"], qty, sl["unit_price"], line_total))
            # restock location
            inv.return_location(
                tenant_id=tenant_id, business_id=business_id, branch_id=branch_id,
                warehouse_id=warehouse_id, master_sku_id=sl["master_sku_id"],
                sku=sl["sku"], quantity=qty,
                reference=f"return:{return_number}:{sl['master_sku_id']}",
                note=f"return {return_number}", actor=actor, device_id=device_id,
                idempotency_key=f"return:{return_number}:{sl['master_sku_id']}",
                source_document=return_number, cur=cur)

        cur.execute(
            "UPDATE local_business.sale_return SET total_refund=%s WHERE id=%s",
            (total_refund, return_id))
        cur.execute(
            "UPDATE local_business.sale SET status='RETURNED' WHERE id=%s", (sale_id,))
        core.catat_audit("sale_returned", actor=actor, tenant_id=tenant_id,
                         business_id=business_id, branch_id=branch_id,
                         payload={"return": return_number, "sale": s["receipt_number"],
                                  "refund": str(total_refund)})
        c.commit()

        # Reverse Finance Core posting if present. Failure is recorded but does not break the return.
        from . import finance as lb_finance
        try:
            lb_finance.reverse_retail_sale_finance(
                sale_id=sale_id, reference=f"return:{return_number}", reason=reason)
        except Exception as exc:
            core.catat_audit("sale_finance_reversal_deferred", actor=actor,
                             tenant_id=tenant_id, business_id=business_id,
                             branch_id=branch_id,
                             payload={"sale_id": sale_id, "return": return_number,
                                      "error": str(exc)[:500]})

        return {"duplicate": False, "return_id": return_id,
                "return_number": return_number, "total_refund": total_refund}
