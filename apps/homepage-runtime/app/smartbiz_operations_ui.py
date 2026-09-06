from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import quote
from uuid import uuid4

from fastapi import Request
from fastapi.responses import RedirectResponse


def _decimal(value: str, *, positive: bool = False) -> str:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    if not cleaned:
        raise ValueError("Jumlah wajib diisi.")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Nilai angka tidak valid.") from exc
    if positive and amount <= 0:
        raise ValueError("Jumlah harus lebih besar dari nol.")
    return format(amount, "f")



def _smart_number(
    value: Any,
    subtract: Any | None = None,
) -> str:
    if value is None or value == "":
        return "0"

    try:
        amount = Decimal(str(value))

        if subtract is not None and subtract != "":
            amount -= Decimal(str(subtract))

    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    if not amount.is_finite():
        return str(value)

    text = format(amount, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    if text in {"", "-0"}:
        text = "0"

    return text.replace(".", ",")

def register_smartbiz_operations(
    *,
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable[..., dict[str, Any] | None],
    core_api_request: Callable[..., Any],
    CoreAPIError: type[Exception],
    base_context: Callable[[Request], dict[str, Any]],
) -> None:
    templates.env.filters["smart_number"] = _smart_number

    def _login_redirect() -> RedirectResponse:
        return RedirectResponse("/login?product=business", status_code=303)

    def _get(request: Request, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return core_api_request(
            request,
            settings,
            "GET",
            path,
            params=params,
        ).json()

    def _post(request: Request, path: str, payload: dict[str, Any]) -> Any:
        return core_api_request(
            request,
            settings,
            "POST",
            path,
            json_data=payload,
            csrf=True,
        ).json()


    def _patch(
        request: Request,
        path: str,
        payload: dict[str, Any],
    ) -> Any:
        return core_api_request(
            request,
            settings,
            "PATCH",
            path,
            json_data=payload,
            csrf=True,
        ).json()

    def _redirect(path: str, key: str, message: str) -> RedirectResponse:
        separator = "&" if "?" in path else "?"
        return RedirectResponse(
            f"{path}{separator}{key}={quote(message)}",
            status_code=303,
        )

    def _load_businesses(request: Request) -> list[dict[str, Any]]:
        payload = _get(request, "/v1/smartbiz/me/businesses")
        return list(payload.get("items") or [])

    @app.get("/smartbiz/{business_id}/operations", include_in_schema=False)
    def smartbiz_operations_page(
        request: Request,
        business_id: str,
        notice: str = "",
        error: str = "",
    ) -> Any:
        if not current_user(request):
            return _login_redirect()
        try:
            businesses = _load_businesses(request)
            selected = next(
                (item for item in businesses if str(item.get("id")) == business_id),
                None,
            )
            if selected is None:
                return RedirectResponse("/smartbiz?error=Usaha%20tidak%20ditemukan", status_code=303)
            prefix = f"/v1/smartbiz/me/businesses/{business_id}"
            products = _get(request, f"{prefix}/products", params={"limit": 200, "offset": 0})
            customers = _get(request, f"{prefix}/customers", params={"limit": 200, "offset": 0})
            locations = _get(request, f"{prefix}/locations")
            movements = _get(request, f"{prefix}/stock/movements", params={"limit": 50, "offset": 0})
            orders = _get(request, f"{prefix}/orders", params={"limit": 50, "offset": 0})
            invoices = _get(request, f"{prefix}/invoices", params={"limit": 50, "offset": 0})
            payments = _get(request, f"{prefix}/payments", params={"limit": 50, "offset": 0})
            actions = _get(request, f"{prefix}/action-requests", params={"limit": 50})
            context = base_context(request)
            context.update(
                {
                    "businesses": businesses,
                    "selected_business": selected,
                    "smartbiz_products": list(products.get("items") or []),
                    "smartbiz_customers": list(customers.get("items") or []),
                    "smartbiz_locations": list(locations.get("items") or []),
                    "smartbiz_movements": list(movements.get("items") or []),
                    "smartbiz_orders": list(orders.get("items") or []),
                    "smartbiz_invoices": list(invoices.get("items") or []),
                    "smartbiz_payments": list(payments.get("items") or []),
                    "smartbiz_actions": list(actions.get("items") or []),
                    "notice": notice,
                    "error": error,
                    "smartbiz_operations_version": "0.6.0",
                    "external_actions_enabled": False,
                    "whatsapp_send_enabled": False,
                }
            )
            return templates.TemplateResponse(
                request,
                "smartbiz_operations.html",
                context,
            )
        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )

    @app.post("/smartbiz/{business_id}/stock-movements", include_in_schema=False)
    async def smartbiz_stock_movement(request: Request, business_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        try:
            payload = {
                "product_id": str(form.get("product_id", "")).strip(),
                "location_id": str(form.get("location_id", "")).strip() or None,
                "movement_type": str(form.get("movement_type", "purchase")).strip(),
                "quantity": _decimal(str(form.get("quantity", "")), positive=True),
                "unit_cost": _decimal(str(form.get("unit_cost", "0"))) if str(form.get("unit_cost", "")).strip() else None,
                "notes": str(form.get("notes", "")).strip() or None,
                "idempotency_key": f"ui-stock-{uuid4().hex}",
            }
            if not payload["product_id"]:
                raise ValueError("Pilih produk terlebih dahulu.")
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/stock/movements",
                payload,
            )
        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Pergerakan stok berhasil dicatat.",
        )

    @app.post("/smartbiz/{business_id}/orders", include_in_schema=False)
    async def smartbiz_create_order(request: Request, business_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        product_ids = [str(value).strip() for value in form.getlist("product_id")]
        quantities = [str(value).strip() for value in form.getlist("quantity")]
        try:
            items = []
            for product_id, quantity in zip(product_ids, quantities):
                if not product_id:
                    continue
                items.append(
                    {
                        "product_id": product_id,
                        "quantity": _decimal(quantity, positive=True),
                    }
                )
            if not items:
                raise ValueError("Tambahkan minimal satu item pesanan.")
            payload = {
                "customer_id": str(form.get("customer_id", "")).strip() or None,
                "notes": str(form.get("notes", "")).strip() or None,
                "idempotency_key": f"ui-order-{uuid4().hex}",
                "items": items,
            }
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/orders/draft",
                payload,
            )
        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Draft pesanan berhasil dibuat.",
        )


    @app.get(
        "/smartbiz/{business_id}/orders/{order_id}/edit",
        include_in_schema=False,
    )
    def smartbiz_edit_order_page(
        request: Request,
        business_id: str,
        order_id: str,
        notice: str = "",
        error: str = "",
    ) -> Any:
        if not current_user(request):
            return _login_redirect()

        try:
            businesses = _load_businesses(request)

            selected = next(
                (
                    item
                    for item in businesses
                    if str(item.get("id")) == business_id
                ),
                None,
            )

            if selected is None:
                return _redirect(
                    "/smartbiz",
                    "error",
                    "Usaha tidak ditemukan.",
                )

            prefix = (
                f"/v1/smartbiz/me/businesses/"
                f"{business_id}"
            )

            products = _get(
                request,
                f"{prefix}/products",
                params={
                    "limit": 200,
                    "offset": 0,
                },
            )

            customers = _get(
                request,
                f"{prefix}/customers",
                params={
                    "limit": 200,
                    "offset": 0,
                },
            )

            order_payload = _get(
                request,
                f"{prefix}/orders/{order_id}",
            )

            order = dict(
                order_payload.get("order") or {}
            )

            items = list(
                order_payload.get("items") or []
            )

            if order.get("status") not in {
                "draft",
                "pending",
            }:
                return _redirect(
                    f"/smartbiz/{business_id}/operations",
                    "error",
                    (
                        "Hanya draft atau pesanan pending "
                        "yang dapat diubah."
                    ),
                )

            context = base_context(request)

            context.update(
                {
                    "businesses": businesses,
                    "selected_business": selected,
                    "smartbiz_products": list(
                        products.get("items") or []
                    ),
                    "smartbiz_customers": list(
                        customers.get("items") or []
                    ),
                    "smartbiz_order": order,
                    "smartbiz_order_items": items,
                    "notice": notice,
                    "error": error,
                    "smartbiz_operations_version": "0.6.0",
                }
            )

            return templates.TemplateResponse(
                request,
                "smartbiz_order_edit.html",
                context,
            )

        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )


    @app.post(
        "/smartbiz/{business_id}/orders/{order_id}/edit",
        include_in_schema=False,
    )
    async def smartbiz_update_order(
        request: Request,
        business_id: str,
        order_id: str,
    ) -> Any:
        if not current_user(request):
            return _login_redirect()

        form = await request.form()

        product_ids = [
            str(value).strip()
            for value in form.getlist("product_id")
        ]

        quantities = [
            str(value).strip()
            for value in form.getlist("quantity")
        ]

        try:
            items = []

            for product_id, quantity in zip(
                product_ids,
                quantities,
            ):
                if not product_id:
                    continue

                items.append(
                    {
                        "product_id": product_id,
                        "quantity": _decimal(
                            quantity,
                            positive=True,
                        ),
                    }
                )

            if not items:
                raise ValueError(
                    "Tambahkan minimal satu item pesanan."
                )

            payload = {
                "customer_id": (
                    str(
                        form.get("customer_id", "")
                    ).strip()
                    or None
                ),
                "notes": (
                    str(
                        form.get("notes", "")
                    ).strip()
                    or None
                ),
                "items": items,
            }

            _patch(
                request,
                (
                    f"/v1/smartbiz/me/businesses/"
                    f"{business_id}/orders/"
                    f"{order_id}/draft"
                ),
                payload,
            )

        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                (
                    f"/smartbiz/{business_id}/orders/"
                    f"{order_id}/edit"
                ),
                "error",
                str(getattr(exc, "detail", str(exc))),
            )

        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Draft pesanan berhasil diperbarui.",
        )


    @app.post(
        "/smartbiz/{business_id}/orders/{order_id}/cancel",
        include_in_schema=False,
    )
    async def smartbiz_cancel_order(
        request: Request,
        business_id: str,
        order_id: str,
    ) -> Any:
        if not current_user(request):
            return _login_redirect()

        try:
            _post(
                request,
                (
                    f"/v1/smartbiz/me/businesses/"
                    f"{business_id}/orders/"
                    f"{order_id}/cancel"
                ),
                {},
            )

        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )

        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Draft pesanan dibatalkan.",
        )

    # SMARTBIZ_AUTO_INVOICE_V060
    @app.post(
        (
            "/smartbiz/{business_id}/orders/"
            "{order_id}/confirm"
        ),
        include_in_schema=False,
    )
    async def smartbiz_confirm_order(
        request: Request,
        business_id: str,
        order_id: str,
    ) -> Any:
        if not current_user(request):
            return _login_redirect()

        prefix = (
            f"/v1/smartbiz/me/businesses/"
            f"{business_id}/orders/{order_id}"
        )

        try:
            _post(
                request,
                f"{prefix}/confirm",
                {},
            )

        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )

        try:
            _post(
                request,
                f"{prefix}/invoice",
                {
                    "due_at": None,
                    "notes": (
                        "Invoice dibuat otomatis ketika "
                        "pesanan dikonfirmasi."
                    ),
                },
            )

        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                (
                    "Pesanan sudah dikonfirmasi, tetapi "
                    "invoice belum berhasil dibuat: "
                    f"{getattr(exc, 'detail', str(exc))}. "
                    "Gunakan tombol Buat invoice untuk mencoba lagi."
                ),
            )

        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            (
                "Pesanan dikonfirmasi, stok diperbarui, "
                "dan invoice berhasil dibuat."
            ),
        )


    @app.post("/smartbiz/{business_id}/orders/{order_id}/invoice", include_in_schema=False)
    async def smartbiz_create_invoice(request: Request, business_id: str, order_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        try:
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/orders/{order_id}/invoice",
                {
                    "due_at": None,
                    "notes": str(form.get("notes", "")).strip() or None,
                },
            )
        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Invoice draft berhasil dibuat.",
        )

    @app.post("/smartbiz/{business_id}/payments", include_in_schema=False)
    async def smartbiz_create_payment(request: Request, business_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        try:
            invoice_id = str(form.get("invoice_id", "")).strip()
            if not invoice_id:
                raise ValueError("Pilih invoice terlebih dahulu.")
            payload = {
                "invoice_id": invoice_id,
                "payment_method": str(form.get("payment_method", "cash")).strip() or "cash",
                "amount": _decimal(str(form.get("amount", "")), positive=True),
                "external_ref": str(form.get("external_ref", "")).strip() or None,
                "idempotency_key": f"ui-payment-{uuid4().hex}",
            }
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/payments",
                payload,
            )
        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            "Pembayaran berhasil dicatat.",
        )

    @app.post("/smartbiz/{business_id}/actions/{request_id}/review", include_in_schema=False)
    async def smartbiz_review_action(
        request: Request,
        business_id: str,
        request_id: str,
    ) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        decision = str(form.get("decision", "reject")).strip().lower()
        try:
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/action-requests/{request_id}/review",
                {
                    "decision": decision,
                    "notes": str(form.get("notes", "")).strip() or None,
                },
            )
        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}/operations",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        message = "Permintaan disetujui untuk tindak lanjut manual." if decision == "approve" else "Permintaan ditolak."
        return _redirect(
            f"/smartbiz/{business_id}/operations",
            "notice",
            message,
        )
