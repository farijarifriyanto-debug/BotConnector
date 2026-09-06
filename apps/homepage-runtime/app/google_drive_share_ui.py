from __future__ import annotations

import secrets

from typing import (
    Any,
    Callable,
)

from urllib.parse import (
    urlencode,
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


def register_google_drive_share_ui(
    *,
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable,
) -> None:


    def login_redirect():

        return RedirectResponse(
            "/login",
            status_code=303,
        )


    def csrf_value(
        request: Request,
    ) -> str:

        raw = request.session.get(
            "core_csrf_token"
        )

        return (
            raw
            if isinstance(
                raw,
                str,
            )
            else ""
        )


    def valid_csrf(
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


    def share_url(
        *,
        path: str,
        notice: str = "",
        error: str = "",
    ) -> str:

        params = {
            "path":
                path,
        }

        if notice:
            params["notice"] = notice

        if error:
            params["error"] = error

        return (
            "/drive/google/share?"
            + urlencode(params)
        )


    def get_status(
        request: Request,
        item_path: str,
    ) -> dict[str, Any]:

        response = api_request(
            request,
            settings,
            "GET",
            (
                "/v1/integrations/"
                "google/share/status?"
                + urlencode(
                    {
                        "path":
                            item_path,
                    }
                )
            ),
        )

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            raise CoreAPIError(
                502,
                (
                    "Respons Google Drive "
                    "tidak valid."
                ),
            )

        return payload


    @app.get(
        "/drive/google/share",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def google_share_page(
        request: Request,

        path: str = "",

        notice: str = "",

        error: str = "",
    ):

        user = current_user(
            request
        )

        if not user:
            return login_redirect()


        item_path = (
            path.strip().strip("/")
        )

        google = None
        load_error = error


        if not item_path:

            load_error = (
                "Path file tidak valid."
            )

        else:

            try:

                google = get_status(
                    request,
                    item_path,
                )

            except CoreAPIError as exc:

                load_error = (
                    exc.detail
                )


        return templates.TemplateResponse(
            request,
            "google_drive_share.html",
            {
                "user":
                    user,

                "item_path":
                    item_path,

                "google":
                    google,

                "notice":
                    notice,

                "error":
                    load_error,

                "csrf_token":
                    csrf_value(
                        request
                    ),
            },
        )


    @app.post(
        "/drive/actions/google-share-public",
        include_in_schema=False,
    )
    def google_share_public(
        request: Request,

        item_path: str = Form(
            default=""
        ),

        csrf_token: str = Form(
            default=""
        ),
    ):

        if not current_user(
            request
        ):
            return login_redirect()


        item_path = (
            item_path
            .strip()
            .strip("/")
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                share_url(
                    path=item_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        try:

            api_request(
                request,
                settings,
                "POST",
                (
                    "/v1/integrations/"
                    "google/share/public"
                ),
                json_data={
                    "path":
                        item_path,
                },
                csrf=True,
            )

        except CoreAPIError as exc:

            return RedirectResponse(
                share_url(
                    path=item_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            share_url(
                path=item_path,
                notice=(
                    "Link Google Drive "
                    "sudah aktif untuk siapa "
                    "saja yang memiliki link."
                ),
            ),
            status_code=303,
        )


    @app.post(
        "/drive/actions/google-share-private",
        include_in_schema=False,
    )
    def google_share_private(
        request: Request,

        item_path: str = Form(
            default=""
        ),

        csrf_token: str = Form(
            default=""
        ),
    ):

        if not current_user(
            request
        ):
            return login_redirect()


        item_path = (
            item_path
            .strip()
            .strip("/")
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                share_url(
                    path=item_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        try:

            api_request(
                request,
                settings,
                "POST",
                (
                    "/v1/integrations/"
                    "google/share/private"
                ),
                json_data={
                    "path":
                        item_path,
                },
                csrf=True,
            )

        except CoreAPIError as exc:

            return RedirectResponse(
                share_url(
                    path=item_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            share_url(
                path=item_path,
                notice=(
                    "Link publik Google Drive "
                    "sudah dinonaktifkan."
                ),
            ),
            status_code=303,
        )
