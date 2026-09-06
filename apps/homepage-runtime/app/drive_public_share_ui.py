from __future__ import annotations

import secrets

from typing import (
    Any,
    Callable,
)

from urllib.parse import (
    urlencode,
)

import httpx

from fastapi import (
    Form,
    Request,
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)

from starlette.background import (
    BackgroundTask,
)

from .core_bridge import (
    CoreAPIError,
    api_request,
)


def register_drive_public_share_ui(
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


    def clean_item_path(
        value: str,
    ) -> str:

        return (
            value
            .strip()
            .strip("/")
        )


    def manage_url(
        *,
        path: str,
        notice: str = "",
        error: str = "",
    ) -> str:

        params: dict[
            str,
            str,
        ] = {
            "path": path,
        }

        if notice:
            params["notice"] = notice

        if error:
            params["error"] = error

        return (
            "/drive/public-share?"
            + urlencode(
                params
            )
        )


    def public_url(
        token: str,
    ) -> str:

        return (
            "https://botconnector.id/s/"
            + token
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


    def load_links(
        request: Request,
        item_path: str,
    ) -> list[
        dict[str, Any]
    ]:

        response = api_request(
            request,
            settings,
            "GET",
            "/v1/drive/public-links",
        )

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            return []

        links = payload.get(
            "links"
        )

        if not isinstance(
            links,
            list,
        ):
            return []

        result: list[
            dict[str, Any]
        ] = []

        for item in links:

            if not isinstance(
                item,
                dict,
            ):
                continue

            if (
                item.get("item_path")
                != item_path
            ):
                continue

            result.append(
                item
            )

        return result


    def render_manage(
        request: Request,
        *,
        item_path: str,
        notice: str = "",
        error: str = "",
        created_link: str = "",
    ):

        load_error = error

        links: list[
            dict[str, Any]
        ] = []

        try:

            links = load_links(
                request,
                item_path,
            )

        except CoreAPIError as exc:

            if not load_error:
                load_error = exc.detail


        item_name = (
            item_path.rsplit(
                "/",
                1,
            )[-1]
            if item_path
            else ""
        )


        return templates.TemplateResponse(
            request,
            "drive_public_share.html",
            {
                "user":
                    current_user(
                        request
                    ),

                "item_path":
                    item_path,

                "item_name":
                    item_name,

                "links":
                    links,

                "notice":
                    notice,

                "error":
                    load_error,

                "created_link":
                    created_link,

                "csrf_token":
                    csrf_value(
                        request
                    ),
            },
        )


    @app.get(
        "/drive/public-share",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def public_share_manage(
        request: Request,

        path: str = "",

        notice: str = "",

        error: str = "",
    ):

        if not current_user(
            request
        ):

            return login_redirect()


        item_path = clean_item_path(
            path
        )


        if not item_path:

            return RedirectResponse(
                "/drive",
                status_code=303,
            )


        return render_manage(
            request,
            item_path=item_path,
            notice=notice,
            error=error,
        )


    @app.post(
        "/drive/public-share",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def create_public_share(
        request: Request,

        item_path: str = Form(
            default=""
        ),

        expires_in_days: str = Form(
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


        item_path = clean_item_path(
            item_path
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not item_path:

            return RedirectResponse(
                "/drive",
                status_code=303,
            )


        expires_in_days = (
            expires_in_days
            .strip()
        )


        allowed = {
            "",
            "1",
            "7",
            "30",
            "90",
        }


        if (
            expires_in_days
            not in allowed
        ):

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=(
                        "Masa berlaku link "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        data: dict[
            str,
            Any,
        ] = {
            "path":
                item_path,
        }


        if expires_in_days:

            data[
                "expires_in_days"
            ] = int(
                expires_in_days
            )


        try:

            response = api_request(
                request,
                settings,
                "POST",
                "/v1/drive/public-links",
                json_data=data,
                csrf=True,
            )

            payload = response.json()


            if not isinstance(
                payload,
                dict,
            ):

                raise CoreAPIError(
                    502,
                    "Respons Public Share tidak valid.",
                )


            token = payload.get(
                "token"
            )


            if (
                not isinstance(
                    token,
                    str,
                )
                or not token
            ):

                raise CoreAPIError(
                    502,
                    "Token Public Share tidak tersedia.",
                )


        except CoreAPIError as exc:

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return render_manage(
            request,
            item_path=item_path,
            notice=(
                "Link publik berhasil dibuat. "
                "Salin link sebelum meninggalkan "
                "halaman ini."
            ),
            created_link=public_url(
                token
            ),
        )


    @app.post(
        "/drive/public-share/revoke",
        include_in_schema=False,
    )
    def revoke_public_share(
        request: Request,

        link_id: str = Form(
            default=""
        ),

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


        item_path = clean_item_path(
            item_path
        )

        link_id = (
            link_id
            .strip()
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not link_id:

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=(
                        "Link ID "
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
                    "/v1/drive/public-links/"
                    + link_id
                ),
                csrf=True,
            )


        except CoreAPIError as exc:

            return RedirectResponse(
                manage_url(
                    path=item_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            manage_url(
                path=item_path,
                notice=(
                    "Link publik "
                    "berhasil dicabut."
                ),
            ),
            status_code=303,
        )


    def public_error_page(
        request: Request,
        *,
        message: str,
        status_code: int = 404,
    ):

        return templates.TemplateResponse(
            request,
            "drive_public_view.html",
            {
                "link":
                    None,

                "entries":
                    [],

                "path":
                    "",

                "parent_url":
                    "",

                "root_download_url":
                    "",

                "error":
                    message,
            },
            status_code=status_code,
            headers={
                "X-Robots-Tag":
                    "noindex, nofollow, noarchive",

                "Cache-Control":
                    "private, no-store",
            },
        )


    @app.get(
        "/s/{token}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def public_share_view(
        request: Request,

        token: str,

        path: str = "",

        error: str = "",
    ):

        params: dict[
            str,
            str,
        ] = {}


        if path:
            params["path"] = path


        try:

            response = api_request(
                request,
                settings,
                "GET",
                (
                    "/v1/public/drive/"
                    + token
                ),
                params=params,
            )

            payload = response.json()


        except CoreAPIError:

            return public_error_page(
                request,
                message=(
                    "Link tidak ditemukan, "
                    "sudah kedaluwarsa, "
                    "atau akses telah dicabut."
                ),
            )


        if not isinstance(
            payload,
            dict,
        ):

            return public_error_page(
                request,
                message=(
                    "Link tidak dapat "
                    "ditampilkan."
                ),
                status_code=502,
            )


        link = payload.get(
            "link"
        )


        if not isinstance(
            link,
            dict,
        ):

            return public_error_page(
                request,
                message=(
                    "Link tidak dapat "
                    "ditampilkan."
                ),
                status_code=502,
            )


        current_path = payload.get(
            "path"
        )


        if not isinstance(
            current_path,
            str,
        ):
            current_path = ""


        raw_entries = payload.get(
            "entries"
        )


        if not isinstance(
            raw_entries,
            list,
        ):
            raw_entries = []


        entries: list[
            dict[str, Any]
        ] = []


        for item in raw_entries:

            if not isinstance(
                item,
                dict,
            ):
                continue


            item_path = item.get(
                "path"
            )

            item_type = item.get(
                "type"
            )


            if not isinstance(
                item_path,
                str,
            ):
                continue


            entry = dict(
                item
            )


            if item_type == "folder":

                entry[
                    "open_url"
                ] = (
                    "/s/"
                    + token
                    + "?"
                    + urlencode(
                        {
                            "path":
                                item_path
                        }
                    )
                )


            elif item_type == "file":

                entry[
                    "download_url"
                ] = (
                    "/s/"
                    + token
                    + "/download?"
                    + urlencode(
                        {
                            "path":
                                item_path
                        }
                    )
                )


            entries.append(
                entry
            )


        parent = parent_path(
            current_path
        )

        parent_url = ""


        if current_path:

            if parent:

                parent_url = (
                    "/s/"
                    + token
                    + "?"
                    + urlencode(
                        {
                            "path":
                                parent
                        }
                    )
                )

            else:

                parent_url = (
                    "/s/"
                    + token
                )


        root_download_url = ""


        if (
            link.get(
                "item_type"
            )
            == "file"
        ):

            root_download_url = (
                "/s/"
                + token
                + "/download"
            )


        return templates.TemplateResponse(
            request,
            "drive_public_view.html",
            {
                "link":
                    link,

                "entries":
                    entries,

                "path":
                    current_path,

                "parent_url":
                    parent_url,

                "root_download_url":
                    root_download_url,

                "error":
                    error,
            },
            headers={
                "X-Robots-Tag":
                    "noindex, nofollow, noarchive",

                "Cache-Control":
                    "private, no-store",

                "X-Content-Type-Options":
                    "nosniff",
            },
        )


    async def close_stream(
        response: httpx.Response,
        client: httpx.AsyncClient,
    ) -> None:

        await response.aclose()
        await client.aclose()


    @app.get(
        "/s/{token}/download",
        include_in_schema=False,
    )
    async def public_share_download(
        request: Request,

        token: str,

        path: str = "",
    ):

        params: dict[
            str,
            str,
        ] = {}


        if path:
            params["path"] = path


        headers = {
            "Accept":
                "*/*",

            "User-Agent":
                request.headers.get(
                    "user-agent",
                    "BotConnector Public Share",
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


        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                None,
                connect=5.0,
            )
        )


        try:

            core_request = (
                client.build_request(
                    "GET",
                    (
                        settings
                        .core_api_url
                        .rstrip("/")
                        + "/v1/public/drive/"
                        + token
                        + "/download"
                    ),
                    headers=headers,
                    params=params,
                )
            )


            response = (
                await client.send(
                    core_request,
                    stream=True,
                )
            )


        except httpx.RequestError:

            await client.aclose()

            query: dict[
                str,
                str,
            ] = {
                "error":
                    (
                        "Download sedang "
                        "tidak tersedia."
                    )
            }

            if path:
                query["path"] = path

            return RedirectResponse(
                (
                    "/s/"
                    + token
                    + "?"
                    + urlencode(
                        query
                    )
                ),
                status_code=303,
            )


        if response.status_code >= 400:

            await response.aclose()
            await client.aclose()

            query = {
                "error":
                    (
                        "File tidak tersedia "
                        "atau akses link "
                        "sudah berakhir."
                    )
            }

            if path:
                query["path"] = path

            return RedirectResponse(
                (
                    "/s/"
                    + token
                    + "?"
                    + urlencode(
                        query
                    )
                ),
                status_code=303,
            )


        output_headers: dict[
            str,
            str,
        ] = {
            "Cache-Control":
                "private, no-store",

            "X-Content-Type-Options":
                "nosniff",
        }


        for key in (
            "content-disposition",
            "content-length",
            "etag",
            "last-modified",
        ):

            value = (
                response.headers.get(
                    key
                )
            )

            if value:
                output_headers[
                    key
                ] = value


        return StreamingResponse(
            response.aiter_raw(),
            status_code=200,
            media_type=(
                response.headers.get(
                    "content-type",
                    "application/octet-stream",
                )
            ),
            headers=output_headers,
            background=BackgroundTask(
                close_stream,
                response,
                client,
            ),
        )
