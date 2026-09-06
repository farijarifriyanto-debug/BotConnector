from __future__ import annotations

import hmac
import secrets

from typing import (
    Any,
    Callable,
)

from fastapi import (
    HTTPException,
    Request,
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from .core_bridge import (
    CoreAPIError,
    api_request,
)

from .staging_control import (
    is_platform_admin,
)


def _csrf(
    request: Request,
) -> str:

    value = request.session.get(
        "admin_storage_csrf"
    )

    if not isinstance(
        value,
        str,
    ) or not value:

        value = secrets.token_urlsafe(
            32
        )

        request.session[
            "admin_storage_csrf"
        ] = value

    return value


def _bytes_label(
    value: int | None,
) -> str:

    if value is None:
        return "Unlimited"

    size = int(value)

    for unit in (
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB",
    ):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{size} {unit}"

            return (
                f"{size:.2f} {unit}"
                if isinstance(size, float)
                else f"{size} {unit}"
            )

        size = size / 1024

    return str(value)


def register_admin_storage(
    *,
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable,
) -> None:


    @app.get(
        "/admin/storage",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def admin_storage(
        request: Request,
    ):

        from starlette.responses import RedirectResponse
        return RedirectResponse(
            url="/panel/#storage",
            status_code=303,
        )


    @app.post(
        "/admin/storage/quota",
        include_in_schema=False,
    )
    async def admin_storage_quota(
        request: Request,
    ):

        from starlette.responses import RedirectResponse
        return RedirectResponse(
            url="/panel/#storage",
            status_code=303,
        )
