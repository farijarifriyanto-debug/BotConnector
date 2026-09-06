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
    Response,
)

from .core_bridge import (
    CoreAPIError,
    api_request,
)


def register_drive_shared_ui(
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


    def shared_url(
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

            return "/drive/shared"


        return (
            "/drive/shared?"
            + urlencode(
                params
            )
        )


    def parent_path(
        value: str,
    ) -> str:

        value = (
            value
            .strip()
            .strip("/")
        )


        if not value:
            return ""


        if "/" not in value:
            return ""


        return value.rsplit(
            "/",
            1,
        )[0]


    def load_shared_root(
        request: Request,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:

        incoming_response = api_request(
            request,
            settings,
            "GET",
            "/v1/drive/shared",
        )


        outgoing_response = api_request(
            request,
            settings,
            "GET",
            "/v1/drive/shares/outgoing",
        )


        incoming_payload = (
            incoming_response.json()
        )

        outgoing_payload = (
            outgoing_response.json()
        )


        incoming = (
            incoming_payload.get(
                "items",
                [],
            )
            if isinstance(
                incoming_payload,
                dict,
            )
            else []
        )


        outgoing = (
            outgoing_payload.get(
                "items",
                [],
            )
            if isinstance(
                outgoing_payload,
                dict,
            )
            else []
        )


        return (
            [
                item
                for item in incoming
                if isinstance(
                    item,
                    dict,
                )
            ],
            [
                item
                for item in outgoing
                if isinstance(
                    item,
                    dict,
                )
            ],
        )


    @app.get(
        "/drive/shared",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def shared_page(

        request: Request,

        share_id: str = "",

        path: str = "",

        notice: str = "",

        error: str = "",

    ):

        user = current_user(
            request
        )


        if not user:

            return login_redirect()


        folder_payload = None
        incoming: list[
            dict[str, Any]
        ] = []

        outgoing: list[
            dict[str, Any]
        ] = []

        load_error = error


        try:

            if share_id:

                query = urlencode(
                    {
                        "share_id":
                            share_id,

                        "path":
                            path,
                    }
                )


                response = api_request(
                    request,
                    settings,
                    "GET",
                    (
                        "/v1/drive/shared/list?"
                        + query
                    ),
                )


                payload = response.json()


                if isinstance(
                    payload,
                    dict,
                ):

                    folder_payload = (
                        payload
                    )


            else:

                (
                    incoming,
                    outgoing,
                ) = load_shared_root(
                    request
                )


        except CoreAPIError as exc:

            load_error = (
                exc.detail
            )


        return templates.TemplateResponse(
            request,
            "drive_shared.html",
            {
                "user":
                    user,

                "incoming":
                    incoming,

                "outgoing":
                    outgoing,

                "folder":
                    folder_payload,

                "share_id":
                    share_id,

                "path":
                    path,

                "parent_path":
                    parent_path(
                        path
                    ),

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


    @app.get(
        "/drive/share",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def share_item_page(

        request: Request,

        path: str = "",

        error: str = "",

    ):

        user = current_user(
            request
        )


        if not user:

            return login_redirect()


        item_path = (
            path
            .strip()
            .strip("/")
        )


        return templates.TemplateResponse(
            request,
            "drive_share.html",
            {
                "user":
                    user,

                "item_path":
                    item_path,

                "error":
                    error,

                "csrf_token":
                    csrf_value(
                        request
                    ),
            },
        )


    @app.post(
        "/drive/share",
        include_in_schema=False,
    )
    def share_item(

        request: Request,

        item_path: str = Form(
            default=""
        ),

        recipient_email: str = Form(
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


        recipient_email = (
            recipient_email
            .strip()
            .lower()
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                (
                    "/drive/share?"
                    + urlencode(
                        {
                            "path":
                                item_path,

                            "error":
                                (
                                    "Token keamanan "
                                    "tidak valid."
                                ),
                        }
                    )
                ),
                status_code=303,
            )


        if not item_path:

            return RedirectResponse(
                shared_url(
                    error=(
                        "Path item "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not recipient_email:

            return RedirectResponse(
                (
                    "/drive/share?"
                    + urlencode(
                        {
                            "path":
                                item_path,

                            "error":
                                (
                                    "Email penerima "
                                    "wajib diisi."
                                ),
                        }
                    )
                ),
                status_code=303,
            )


        try:

            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/shares",
                json_data={
                    "path":
                        item_path,

                    "recipient_email":
                        recipient_email,
                },
                csrf=True,
            )


        except CoreAPIError as exc:

            return RedirectResponse(
                (
                    "/drive/share?"
                    + urlencode(
                        {
                            "path":
                                item_path,

                            "error":
                                exc.detail,
                        }
                    )
                ),
                status_code=303,
            )


        return RedirectResponse(
            shared_url(
                notice=(
                    "Akses viewer berhasil "
                    "dibagikan ke "
                    + recipient_email
                    + "."
                ),
            ),
            status_code=303,
        )


    @app.post(
        "/drive/share/revoke",
        include_in_schema=False,
    )
    def revoke_share(

        request: Request,

        share_id: str = Form(
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


        share_id = (
            share_id
            .strip()
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                shared_url(
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not share_id:

            return RedirectResponse(
                shared_url(
                    error=(
                        "Share ID "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        try:

            api_request(
                request,
                settings,
                "DELETE",
                (
                    "/v1/drive/shares/"
                    + share_id
                ),
                csrf=True,
            )


        except CoreAPIError as exc:

            return RedirectResponse(
                shared_url(
                    error=
                        exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            shared_url(
                notice=(
                    "Akses shared "
                    "berhasil dicabut."
                ),
            ),
            status_code=303,
        )


    @app.get(
        "/drive/shared/download",
        include_in_schema=False,
    )
    def shared_download(

        request: Request,

        share_id: str = "",

        path: str = "",

    ):

        if not current_user(
            request
        ):

            return login_redirect()


        share_id = (
            share_id
            .strip()
        )


        if not share_id:

            return RedirectResponse(
                shared_url(
                    error=(
                        "Share ID "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        query = {
            "share_id":
                share_id,
        }


        if path:

            query[
                "path"
            ] = path


        try:

            response = api_request(
                request,
                settings,
                "GET",
                (
                    "/v1/drive/shared/download?"
                    + urlencode(
                        query
                    )
                ),
            )


        except CoreAPIError as exc:

            return RedirectResponse(
                shared_url(
                    error=
                        exc.detail,
                ),
                status_code=303,
            )


        headers: dict[
            str,
            str,
        ] = {}


        for header in (
            "content-type",
            "content-length",
            "content-disposition",
            "etag",
            "last-modified",
        ):

            value = response.headers.get(
                header
            )


            if value:

                headers[
                    header
                ] = value


        return Response(
            content=
                response.content,

            status_code=
                response.status_code,

            headers=
                headers,
        )
