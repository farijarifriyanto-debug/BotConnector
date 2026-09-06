"""Print / receipt support.

Robust browser-print receipt (58mm/80mm) with print CSS. Receipt: business,
branch, number, cashier, items, qty, price, discount, tax, total, tender,
change, timestamp. Future adapter boundary for ESC/POS/local printer bridge.
"""

from __future__ import annotations

from ..persistence.db import koneksi as _pg


def render_receipt_html(*, business_name: str, branch_name: str, receipt_number: str,
                        cashier: str, lines: list[dict], subtotal, discount,
                        tax_amount, total, tender_method, amount_tendered,
                        change_due, timestamp: str, width_mm: int = 80) -> str:
    """Render a printable receipt HTML (58mm/80mm friendly)."""
    rows = "".join(
        f"<tr><td>{l['description']}</td><td class='r'>{l['quantity']} x {l['unit_price']:.0f}</td>"
        f"<td class='r'>{l['line_total']:.0f}</td></tr>"
        for l in lines)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
@media print {{ @page {{ size: {width_mm}mm auto; margin: 0; }} }}
body {{ font-family: monospace; font-size: 12px; width: {width_mm}mm; margin: 0; padding: 4mm; }}
h1 {{ font-size: 14px; text-align: center; margin: 0 0 2px; }}
.meta {{ text-align: center; font-size: 11px; margin-bottom: 6px; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ padding: 1px 0; }}
.r {{ text-align: right; }}
.totals td {{ padding: 2px 0; }}
hr {{ border: 0; border-top: 1px dashed #000; margin: 4px 0; }}
</style></head><body>
<h1>{business_name}</h1>
<div class="meta">{branch_name}<br>{receipt_number}<br>Kasir: {cashier}<br>{timestamp}</div>
<hr>
<table><tr><th>Item</th><th class="r">Qty</th><th class="r">Total</th></tr>{rows}</table>
<hr>
<table class="totals">
<tr><td>Subtotal</td><td class="r">{subtotal:.0f}</td></tr>
<tr><td>Diskon</td><td class="r">{discount:.0f}</td></tr>
<tr><td>Pajak</td><td class="r">{tax_amount:.0f}</td></tr>
<tr><td><b>Total</b></td><td class="r"><b>{total:.0f}</b></td></tr>
<tr><td>{tender_method}</td><td class="r">{amount_tendered:.0f}</td></tr>
<tr><td>Kembali</td><td class="r">{change_due:.0f}</td></tr>
</table>
</body></html>"""


def get_receipt_data(sale_id: int) -> dict | None:
    """Fetch receipt data for a sale."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """SELECT s.*, b.name AS branch_name, biz.name AS business_name,
                      ca.name AS cashier_name
               FROM local_business.sale s
               JOIN local_business.branch b ON b.id=s.branch_id
               JOIN local_business.business biz ON biz.id=s.business_id
               LEFT JOIN local_business.cashier ca ON ca.id=s.cashier_id
               WHERE s.id=%s""", (sale_id,))
        s = cur.fetchone()
        if not s:
            return None
        cur.execute(
            "SELECT * FROM local_business.sale_line WHERE sale_id=%s ORDER BY line_no",
            (sale_id,))
        s["lines"] = cur.fetchall()
        return s
