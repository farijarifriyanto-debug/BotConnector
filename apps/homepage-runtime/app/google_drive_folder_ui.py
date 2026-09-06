from __future__ import annotations

import os
import secrets

from typing import (
    Any,
    Callable,
)

from urllib.parse import urlencode

from fastapi import (
    Form,
    Request,
)

from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from .core_bridge import (
    CoreAPIError,
    api_request,
)


def register_google_drive_folder_ui(
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

        value = request.session.get(
            "core_csrf_token"
        )

        if isinstance(
            value,
            str,
        ):
            return value

        return ""


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


    def picker_config() -> tuple[
        str,
        str,
    ]:

        key = (
            os.environ.get(
                "GOOGLE_PICKER_API_KEY",
                "",
            )
            .strip()
        )

        project = (
            os.environ.get(
                "GOOGLE_CLOUD_PROJECT_NUMBER",
                "",
            )
            .strip()
        )

        if not key:

            raise RuntimeError(
                "Google Picker API key "
                "belum tersedia."
            )

        if (
            not project
            or not project.isdigit()
        ):

            raise RuntimeError(
                "Google Cloud Project Number "
                "belum tersedia."
            )

        return (
            key,
            project,
        )


    def page_url(
        *,
        notice: str = "",
        error: str = "",
    ) -> str:

        params: dict[
            str,
            str,
        ] = {}

        if notice:
            params["notice"] = notice

        if error:
            params["error"] = error

        if not params:
            return "/drive/google/folder"

        return (
            "/drive/google/folder?"
            + urlencode(params)
        )


    @app.get(
        "/drive/google/folder",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def folder_page(
        request: Request,
        notice: str = "",
        error: str = "",
    ):

        user = current_user(
            request
        )

        if not user:
            return login_redirect()


        destination: dict[
            str,
            Any,
        ] = {
            "mode":
                "root",

            "folder_id":
                None,

            "folder_name":
                "My Drive",
        }

        load_error = error


        try:

            response = api_request(
                request,
                settings,
                "GET",
                (
                    "/v1/integrations/"
                    "google/folder"
                ),
            )

            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):
                destination = payload

        except CoreAPIError as exc:

            load_error = exc.detail


        try:

            picker_config()
            picker_ready = True

        except RuntimeError as exc:

            picker_ready = False

            if not load_error:
                load_error = str(exc)


        return templates.TemplateResponse(
            request,
            "google_drive_folder.html",
            {
                "user":
                    user,

                "destination":
                    destination,

                "notice":
                    notice,

                "error":
                    load_error,

                "picker_ready":
                    picker_ready,

                "csrf_token":
                    csrf_value(
                        request
                    ),
            },
        )


    @app.post(
        "/drive/google/picker-session",
        include_in_schema=False,
    )
    def picker_session(
        request: Request,
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

            return JSONResponse(
                {
                    "detail":
                        (
                            "Token keamanan "
                            "tidak valid."
                        ),
                },
                status_code=403,
                headers={
                    "Cache-Control":
                        "no-store",
                },
            )


        try:

            developer_key, app_id = (
                picker_config()
            )

            response = api_request(
                request,
                settings,
                "POST",
                (
                    "/v1/integrations/"
                    "google/picker-token"
                ),
                csrf=True,
            )

            payload = response.json()

        except CoreAPIError as exc:

            return JSONResponse(
                {
                    "detail":
                        exc.detail,
                },
                status_code=
                    exc.status_code,
                headers={
                    "Cache-Control":
                        "no-store",
                },
            )

        except RuntimeError as exc:

            return JSONResponse(
                {
                    "detail":
                        str(exc),
                },
                status_code=503,
                headers={
                    "Cache-Control":
                        "no-store",
                },
            )


        if not isinstance(
            payload,
            dict,
        ):

            return JSONResponse(
                {
                    "detail":
                        (
                            "Respons Google "
                            "tidak valid."
                        ),
                },
                status_code=502,
                headers={
                    "Cache-Control":
                        "no-store",
                },
            )


        oauth_token = str(
            payload.get(
                "access_token"
            )
            or ""
        )


        if not oauth_token:

            return JSONResponse(
                {
                    "detail":
                        (
                            "Access token Google "
                            "tidak tersedia."
                        ),
                },
                status_code=502,
                headers={
                    "Cache-Control":
                        "no-store",
                },
            )


        return JSONResponse(
            {
                "oauth_token":
                    oauth_token,

                "developer_key":
                    developer_key,

                "app_id":
                    app_id,
            },
            headers={
                "Cache-Control":
                    "no-store, private",

                "Pragma":
                    "no-cache",

                "X-Content-Type-Options":
                    "nosniff",
            },
        )


    @app.post(
        "/drive/google/folder/select",
        include_in_schema=False,
    )
    def folder_select(
        request: Request,
        folder_id: str = Form(
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

            return JSONResponse(
                {
                    "detail":
                        (
                            "Token keamanan "
                            "tidak valid."
                        ),
                },
                status_code=403,
            )


        folder_id = (
            folder_id
            .strip()
        )


        if not folder_id:

            return JSONResponse(
                {
                    "detail":
                        (
                            "Folder ID "
                            "tidak valid."
                        ),
                },
                status_code=400,
            )


        try:

            response = api_request(
                request,
                settings,
                "POST",
                (
                    "/v1/integrations/"
                    "google/folder"
                ),
                json_data={
                    "folder_id":
                        folder_id,
                },
                csrf=True,
            )

            payload = response.json()

        except CoreAPIError as exc:

            return JSONResponse(
                {
                    "detail":
                        exc.detail,
                },
                status_code=
                    exc.status_code,
            )


        if not isinstance(
            payload,
            dict,
        ):

            return JSONResponse(
                {
                    "detail":
                        (
                            "Respons folder "
                            "tidak valid."
                        ),
                },
                status_code=502,
            )


        return JSONResponse(
            payload
        )


    @app.post(
        "/drive/google/folder/reset",
        include_in_schema=False,
    )
    def folder_reset(
        request: Request,
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
                page_url(
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
                    "google/folder/reset"
                ),
                csrf=True,
            )

        except CoreAPIError as exc:

            return RedirectResponse(
                page_url(
                    error=
                        exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            page_url(
                notice=(
                    "Folder tujuan kembali "
                    "ke My Drive."
                ),
            ),
            status_code=303,
        )
