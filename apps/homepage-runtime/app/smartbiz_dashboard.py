from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    normalized = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return normalized[:63]


def _money(value: str) -> str:
    cleaned = value.strip().replace(".", "").replace(",", ".")
    if not cleaned:
        return "0"
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Nilai harga tidak valid.") from exc
    if amount < 0:
        raise ValueError("Nilai harga tidak boleh negatif.")
    return format(amount, "f")


def _bool(form: Any, key: str, default: bool = False) -> bool:
    value = form.get(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}



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

def register_smartbiz_dashboard(
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


    # SMARTBIZ_BARCODE_PLATFORM_V060
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

    def _render(
        request: Request,
        *,
        businesses: list[dict[str, Any]],
        selected_business: dict[str, Any] | None = None,
        dashboard: dict[str, Any] | None = None,
        products: list[dict[str, Any]] | None = None,
        customers: list[dict[str, Any]] | None = None,
        stock: list[dict[str, Any]] | None = None,
        error: str = "",
        notice: str = "",
        status_code: int = 200,
    ) -> Any:
        context = base_context(request)
        context.update(
            {
                "businesses": businesses,
                "selected_business": selected_business,
                "smartbiz_dashboard": dashboard or {},
                "smartbiz_products": products or [],
                "smartbiz_customers": customers or [],
                "smartbiz_stock": stock or [],
                "error": error,
                "notice": notice,
                "smartbiz_version": "0.3.0",
            }
        )
        return templates.TemplateResponse(
            request,
            "smartbiz_dashboard.html",
            context,
            status_code=status_code,
        )

    @app.get("/smartbiz/advanced", include_in_schema=False)
    def smartbiz_home(
        request: Request,
        notice: str = "",
        error: str = "",
    ) -> Any:
        if not current_user(request):
            return _login_redirect()
        try:
            payload = _get(request, "/v1/smartbiz/me/businesses")
            businesses = list(payload.get("items") or [])
        except CoreAPIError as exc:
            status_code = int(getattr(exc, "status_code", 502))
            if status_code == 403:
                return RedirectResponse("/onboarding/business", status_code=303)
            return _render(
                request,
                businesses=[],
                error=str(getattr(exc, "detail", str(exc))),
                status_code=status_code if status_code < 500 else 502,
            )
        if businesses:
            return RedirectResponse(
                f"/smartbiz/{businesses[0]['id']}",
                status_code=303,
            )
        return _render(
            request,
            businesses=[],
            notice=notice,
            error=error,
        )

    @app.get("/smartbiz/{business_id}", include_in_schema=False)
    def smartbiz_business(
        request: Request,
        business_id: str,
        notice: str = "",
        error: str = "",
    ) -> Any:
        if not current_user(request):
            return _login_redirect()
        try:
            business_payload = _get(request, "/v1/smartbiz/me/businesses")
            businesses = list(business_payload.get("items") or [])
            selected = next(
                (item for item in businesses if str(item.get("id")) == business_id),
                None,
            )
            if selected is None:
                return _render(
                    request,
                    businesses=businesses,
                    error="Usaha tidak ditemukan atau tidak dapat Anda akses.",
                    status_code=404,
                )
            dashboard = _get(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/dashboard",
            )
            products = _get(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/products",
                params={"limit": 100, "offset": 0},
            )
            customers = _get(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/customers",
                params={"limit": 100, "offset": 0},
            )
            stock = _get(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/stock",
                params={"limit": 200, "offset": 0},
            )
            return _render(
                request,
                businesses=businesses,
                selected_business=selected,
                dashboard=dashboard,
                products=list(products.get("items") or []),
                customers=list(customers.get("items") or []),
                stock=list(stock.get("items") or []),
                notice=notice,
                error=error,
            )
        except CoreAPIError as exc:
            status_code = int(getattr(exc, "status_code", 502))
            return _render(
                request,
                businesses=[],
                error=str(getattr(exc, "detail", str(exc))),
                status_code=status_code if status_code < 500 else 502,
            )

    @app.post("/smartbiz/businesses", include_in_schema=False)
    async def smartbiz_create_business(request: Request) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        name = str(form.get("name", "")).strip()
        slug = _slug(str(form.get("slug", "")) or name)
        if len(name) < 2 or len(slug) < 3:
            return _redirect(
                "/smartbiz",
                "error",
                "Nama usaha atau slug belum valid.",
            )
        payload = {
            "name": name,
            "slug": slug,
            "business_type": str(form.get("business_type", "retail")).strip() or "retail",
            "currency": "IDR",
            "timezone": "Asia/Jakarta",
            "settings": {},
        }
        try:
            row = _post(request, "/v1/smartbiz/me/businesses", payload)
        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                "/smartbiz",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{row['id']}",
            "notice",
            "Usaha berhasil dibuat.",
        )

    @app.post("/smartbiz/{business_id}/products", include_in_schema=False)
    async def smartbiz_create_product(request: Request, business_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        try:
            payload = {
                "sku": str(form.get("sku", "")).strip() or None,
                "name": str(form.get("name", "")).strip(),
                "product_type": str(form.get("product_type", "goods")).strip() or "goods",
                "unit": str(form.get("unit", "pcs")).strip() or "pcs",
                "cost_price": _money(str(form.get("cost_price", "0"))),
                "sell_price": _money(str(form.get("sell_price", "0"))),
                "track_stock": _bool(form, "track_stock", False),
                "allow_negative_stock": False,
                "metadata": {},
            }
            if not payload["name"]:
                raise ValueError("Nama produk wajib diisi.")
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/products",
                payload,
            )
        except (CoreAPIError, ValueError) as exc:
            return _redirect(
                f"/smartbiz/{business_id}",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}",
            "notice",
            "Produk berhasil ditambahkan.",
        )


    @app.post(
        (
            "/smartbiz/{business_id}/products/"
            "{product_id}/barcode"
        ),
        include_in_schema=False,
    )
    async def smartbiz_update_product_barcode(
        request: Request,
        business_id: str,
        product_id: str,
    ) -> Any:
        if not current_user(request):
            return _login_redirect()

        form = await request.form()

        barcode = (
            str(form.get("barcode", "")).strip()
            or None
        )

        try:
            _patch(
                request,
                (
                    f"/v1/smartbiz/me/businesses/"
                    f"{business_id}/products/"
                    f"{product_id}/barcode"
                ),
                {
                    "barcode": barcode,
                },
            )

        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )

        return _redirect(
            f"/smartbiz/{business_id}",
            "notice",
            "Barcode produk berhasil disimpan.",
        )

    @app.post("/smartbiz/{business_id}/customers", include_in_schema=False)
    async def smartbiz_create_customer(request: Request, business_id: str) -> Any:
        if not current_user(request):
            return _login_redirect()
        form = await request.form()
        payload = {
            "name": str(form.get("name", "")).strip(),
            "phone": str(form.get("phone", "")).strip() or None,
            "email": str(form.get("email", "")).strip().lower() or None,
            "address": {},
            "notes": str(form.get("notes", "")).strip() or None,
            "external_ref": None,
        }
        if not payload["name"]:
            return _redirect(
                f"/smartbiz/{business_id}",
                "error",
                "Nama pelanggan wajib diisi.",
            )
        try:
            _post(
                request,
                f"/v1/smartbiz/me/businesses/{business_id}/customers",
                payload,
            )
        except CoreAPIError as exc:
            return _redirect(
                f"/smartbiz/{business_id}",
                "error",
                str(getattr(exc, "detail", str(exc))),
            )
        return _redirect(
            f"/smartbiz/{business_id}",
            "notice",
            "Pelanggan berhasil ditambahkan.",
        )
