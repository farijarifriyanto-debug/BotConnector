from __future__ import annotations

import secrets

from typing import (
    Any,
    Callable,
)

from urllib.parse import (
    urlencode,
    urlparse,
)

from fastapi import (
    Form,
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


def register_google_drive_ui(
    *,
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable[
        [Request],
        dict[str, Any] | None,
    ],
) -> None:

    def login_redirect() -> RedirectResponse:

        return RedirectResponse(
            "/login",
            status_code=303,
        )


    def csrf_value(
        request: Request,
    ) -> str:

        value = request.session.get(
            "core_csrf_token"
        )

        return (
            value
            if isinstance(
                value,
                str,
            )
            else ""
        )


    def require_local_csrf(
        request: Request,
        supplied: str,
    ) -> bool:

        expected = csrf_value(
            request
        )

        return bool(
            supplied
            and expected
            and secrets.compare_digest(
                supplied,
                expected,
            )
        )


    def integrations_url(
        *,
        notice: str = "",
        error: str = "",
    ) -> str:

        params: dict[
            str,
            str,
        ] = {}

        if notice:
            params[
                "notice"
            ] = notice

        if error:
            params[
                "error"
            ] = error

        if not params:
            return (
                "/settings/integrations"
            )

        return (
            "/settings/integrations?"
            + urlencode(params)
        )


    def safe_google_url(
        value: str,
    ) -> bool:

        try:

            parsed = urlparse(
                value
            )

        except Exception:
            return False

        return (
            parsed.scheme == "https"
            and parsed.hostname
                == "accounts.google.com"
            and parsed.path
                == "/o/oauth2/v2/auth"
        )


    @app.get(
        "/settings/integrations",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def integrations_page(
        request: Request,
        notice: str = "",
        error: str = "",
    ):

        user = current_user(
            request
        )

        if not user:
            return login_redirect()

        google: dict[
            str,
            Any,
        ] = {
            "connected":
                False,
        }

        load_error = error

        try:

            response = api_request(
                request,
                settings,
                "GET",
                "/v1/integrations/google/status",
            )

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):
                google = payload

        except CoreAPIError as exc:

            load_error = (
                exc.detail
            )

        return templates.TemplateResponse(
            request,
            "google_integrations.html",
            {
                "user":
                    user,

                "google":
                    google,

                "csrf_token":
                    csrf_value(
                        request
                    ),

                "notice":
                    notice,

                "error":
                    load_error,
            },
        )


    @app.post(
        "/integrations/google/start",
        include_in_schema=False,
    )
    def google_start(
        request: Request,
        csrf_token: str = Form(
            default=""
        ),
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        if not require_local_csrf(
            request,
            csrf_token,
        ):
            return RedirectResponse(
                integrations_url(
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    )
                ),
                status_code=303,
            )

        try:

            response = api_request(
                request,
                settings,
                "POST",
                "/v1/integrations/google/start",
                csrf=True,
            )

            payload = response.json()

        except CoreAPIError as exc:

            return RedirectResponse(
                integrations_url(
                    error=exc.detail,
                ),
                status_code=303,
            )

        authorization_url = str(
            payload.get(
                "authorization_url"
            )
            or ""
        )

        if not safe_google_url(
            authorization_url
        ):

            return RedirectResponse(
                integrations_url(
                    error=(
                        "URL otorisasi "
                        "Google tidak valid."
                    )
                ),
                status_code=303,
            )

        return RedirectResponse(
            authorization_url,
            status_code=303,
        )


    @app.get(
        "/integrations/google/callback",
        include_in_schema=False,
    )
    def google_callback(
        request: Request,
        code: str = "",
        state: str = "",
        error: str = "",
        error_description: str = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        if error:

            if error == "access_denied":
                message = (
                    "Izin Google Drive "
                    "dibatalkan."
                )
            else:
                message = (
                    "Google OAuth gagal: "
                    + error[:80]
                )

            return RedirectResponse(
                integrations_url(
                    error=message,
                ),
                status_code=303,
            )

        if (
            not code
            or not state
        ):
            return RedirectResponse(
                integrations_url(
                    error=(
                        "Callback Google "
                        "tidak lengkap."
                    )
                ),
                status_code=303,
            )

        try:

            api_request(
                request,
                settings,
                "POST",
                "/v1/integrations/google/callback",
                json_data={
                    "code":
                        code,

                    "state":
                        state,
                },
                csrf=True,
            )

        except CoreAPIError as exc:

            return RedirectResponse(
                integrations_url(
                    error=exc.detail,
                ),
                status_code=303,
            )

        return RedirectResponse(
            integrations_url(
                notice=(
                    "Google Drive "
                    "berhasil terhubung."
                )
            ),
            status_code=303,
        )


    @app.post(
        "/integrations/google/disconnect",
        include_in_schema=False,
    )
    def google_disconnect(
        request: Request,
        csrf_token: str = Form(
            default=""
        ),
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        if not require_local_csrf(
            request,
            csrf_token,
        ):
            return RedirectResponse(
                integrations_url(
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    )
                ),
                status_code=303,
            )

        try:

            api_request(
                request,
                settings,
                "POST",
                "/v1/integrations/google/disconnect",
                csrf=True,
            )

        except CoreAPIError as exc:

            return RedirectResponse(
                integrations_url(
                    error=exc.detail,
                ),
                status_code=303,
            )

        return RedirectResponse(
            integrations_url(
                notice=(
                    "Google Drive "
                    "sudah diputus."
                )
            ),
            status_code=303,
        )
