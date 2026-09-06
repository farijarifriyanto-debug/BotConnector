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

import httpx

from fastapi import (
    Form,
    Request,
)

from fastapi.responses import (
    RedirectResponse,
)

from .core_bridge import (
    CoreAPIError,
)


def register_google_drive_save_ui(
    *,
    app: Any,
    settings: Any,
    current_user: Callable,
) -> None:


    def login_redirect() -> RedirectResponse:

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


    def drive_return(
        *,
        view: str,
        path: str,
        notice: str = "",
    ) -> str:

        if view not in {
            "my",
            "recent",
            "starred",
            "trash",
        }:
            view = "my"

        params = {
            "view":
                view,
        }

        if path:
            params[
                "path"
            ] = path

        if notice:
            params[
                "notice"
            ] = notice

        return (
            "/drive?"
            + urlencode(
                params
            )
        )


    def integrations_error(
        message: str,
    ) -> str:

        return (
            "/settings/integrations?"
            + urlencode(
                {
                    "error":
                        message,
                }
            )
        )


    def call_core_save(
        request: Request,
        item_path: str,
    ) -> dict[str, Any]:

        csrf = csrf_value(
            request
        )

        if not csrf:

            raise CoreAPIError(
                401,
                (
                    "Sesi keamanan tidak "
                    "tersedia. Silakan masuk ulang."
                ),
            )

        cookie_token = (
            request.cookies.get(
                settings.core_cookie_name
            )
        )

        if not cookie_token:

            raise CoreAPIError(
                401,
                (
                    "Sesi tidak valid "
                    "atau berakhir."
                ),
            )

        headers = {
            "Accept":
                "application/json",

            "Content-Type":
                "application/json",

            "X-CSRF-Token":
                csrf,

            "User-Agent":
                request.headers.get(
                    "user-agent",
                    "BotConnector",
                ),

            "X-Forwarded-For":
                request.headers.get(
                    "x-forwarded-for",
                    (
                        request.client.host
                        if request.client
                        else "127.0.0.1"
                    ),
                ),
        }


        try:

            response = httpx.post(
                (
                    settings
                    .core_api_url
                    .rstrip("/")
                    + "/v1/integrations/"
                      "google/save"
                ),
                headers=headers,
                cookies={
                    settings.core_cookie_name:
                        cookie_token,
                },
                json={
                    "path":
                        item_path,
                },
                timeout=httpx.Timeout(
                    900.0,
                    connect=5.0,
                ),
                follow_redirects=False,
            )

        except httpx.RequestError as exc:

            raise CoreAPIError(
                502,
                (
                    "Proses simpan ke "
                    "Google Drive terputus."
                ),
            ) from exc


        if response.status_code >= 400:

            detail = (
                "Simpan ke Google Drive "
                "tidak berhasil."
            )

            try:

                payload = response.json()

                if isinstance(
                    payload,
                    dict,
                ):

                    raw = payload.get(
                        "detail"
                    )

                    if isinstance(
                        raw,
                        str,
                    ):
                        detail = raw

            except ValueError:
                pass

            raise CoreAPIError(
                response.status_code,
                detail,
            )


        try:

            payload = response.json()

        except ValueError as exc:

            raise CoreAPIError(
                502,
                (
                    "Respons Google Drive "
                    "tidak valid."
                ),
            ) from exc


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


    @app.post(
        "/drive/actions/google-save",
        include_in_schema=False,
    )
    def google_save_action(
        request: Request,

        item_path: str = Form(
            default=""
        ),

        return_view: str = Form(
            default="my"
        ),

        return_path: str = Form(
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


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                drive_return(
                    view=
                        return_view,

                    path=
                        return_path,

                    notice=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        item_path = (
            item_path
            .strip()
            .strip("/")
        )

        if not item_path:

            return RedirectResponse(
                drive_return(
                    view=
                        return_view,

                    path=
                        return_path,

                    notice=(
                        "File tidak valid."
                    ),
                ),
                status_code=303,
            )


        try:

            result = call_core_save(
                request,
                item_path,
            )

        except CoreAPIError as exc:

            if exc.status_code in {
                401,
                409,
            }:

                return RedirectResponse(
                    integrations_error(
                        exc.detail
                    ),
                    status_code=303,
                )

            return RedirectResponse(
                drive_return(
                    view=
                        return_view,

                    path=
                        return_path,

                    notice=
                        exc.detail,
                ),
                status_code=303,
            )


        web_view_link = str(
            result.get(
                "web_view_link"
            )
            or ""
        )


        if web_view_link:

            try:

                parsed = urlparse(
                    web_view_link
                )

            except Exception:

                parsed = None


            if (
                parsed
                and parsed.scheme == "https"
                and parsed.hostname in {
                    "drive.google.com",
                    "docs.google.com",
                }
            ):

                return RedirectResponse(
                    web_view_link,
                    status_code=303,
                )


        return RedirectResponse(
            drive_return(
                view=
                    return_view,

                path=
                    return_path,

                notice=(
                    "File berhasil disimpan "
                    "ke Google Drive."
                ),
            ),
            status_code=303,
        )
