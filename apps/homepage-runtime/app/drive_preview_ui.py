from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, urlencode

import httpx

from fastapi import (
    HTTPException,
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


PREVIEW_TYPES: dict[
    str,
    tuple[str, str],
] = {
    "pdf":
        (
            "pdf",
            "application/pdf",
        ),

    "png":
        (
            "image",
            "image/png",
        ),

    "jpg":
        (
            "image",
            "image/jpeg",
        ),

    "jpeg":
        (
            "image",
            "image/jpeg",
        ),

    "webp":
        (
            "image",
            "image/webp",
        ),

    "gif":
        (
            "image",
            "image/gif",
        ),

    "txt":
        (
            "text",
            "text/plain; charset=utf-8",
        ),

    "md":
        (
            "text",
            "text/plain; charset=utf-8",
        ),

    "csv":
        (
            "text",
            "text/plain; charset=utf-8",
        ),

    "json":
        (
            "text",
            "application/json; charset=utf-8",
        ),

    "log":
        (
            "text",
            "text/plain; charset=utf-8",
        ),
}


TEXT_PREVIEW_LIMIT = (
    5 * 1024 * 1024
)


def preview_spec(
    name: str,
    size_bytes: int = 0,
) -> tuple[str, str]:

    suffix = (
        name.rsplit(
            ".",
            1,
        )[-1].lower()
        if "." in name
        else ""
    )

    result = PREVIEW_TYPES.get(
        suffix
    )

    if result is None:

        return (
            "unsupported",
            "application/octet-stream",
        )

    kind, media_type = result

    if (
        kind == "text"
        and size_bytes
        > TEXT_PREVIEW_LIMIT
    ):

        return (
            "unsupported",
            media_type,
        )

    return (
        kind,
        media_type,
    )


def register_drive_preview_ui(
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


    def clean_path(
        value: str,
    ) -> str:

        value = (
            value
            .strip()
            .strip("/")
        )

        if not value:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Path file "
                    "tidak valid."
                ),
            )

        if (
            "\\" in value
            or "\x00" in value
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Path file "
                    "tidak valid."
                ),
            )

        pieces = value.split("/")

        if any(
            piece in (
                "",
                ".",
                "..",
            )
            for piece in pieces
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Path file "
                    "tidak valid."
                ),
            )

        return PurePosixPath(
            *pieces
        ).as_posix()


    def item_metadata(
        request: Request,
        item_path: str,
    ) -> dict[str, Any]:

        pure = PurePosixPath(
            item_path
        )

        parent = str(
            pure.parent
        )

        if parent == ".":
            parent = ""

        response = api_request(
            request,
            settings,
            "GET",
            "/v1/drive/list",
            params={
                "path":
                    parent,
            },
        )

        payload = response.json()

        items = (
            payload.get(
                "items",
                [],
            )
            if isinstance(
                payload,
                dict,
            )
            else []
        )

        for item in items:

            if not isinstance(
                item,
                dict,
            ):
                continue

            if (
                str(
                    item.get(
                        "path"
                    )
                    or ""
                )
                != item_path
            ):
                continue

            if (
                item.get(
                    "type"
                )
                != "file"
            ):

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Preview hanya "
                        "tersedia untuk file."
                    ),
                )

            return item

        raise HTTPException(
            status_code=404,
            detail=(
                "File tidak ditemukan."
            ),
        )


    @app.get(
        "/drive/preview",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def preview_page(
        request: Request,
        path: str = "",
    ):

        user = current_user(
            request
        )

        if not user:
            return login_redirect()

        try:

            item_path = clean_path(
                path
            )

            item = item_metadata(
                request,
                item_path,
            )

        except CoreAPIError as exc:

            raise HTTPException(
                status_code=getattr(
                    exc,
                    "status_code",
                    502,
                ),
                detail=exc.detail,
            ) from exc


        name = str(
            item.get(
                "name"
            )
            or PurePosixPath(
                item_path
            ).name
        )


        size_bytes = int(
            item.get(
                "size_bytes"
            )
            or 0
        )


        kind, _media_type = (
            preview_spec(
                name,
                size_bytes,
            )
        )


        pure = PurePosixPath(
            item_path
        )

        parent = str(
            pure.parent
        )

        if parent == ".":
            parent = ""


        back_params = {
            "view":
                "my",
        }

        if parent:

            back_params[
                "path"
            ] = parent


        back_url = (
            "/drive?"
            + urlencode(
                back_params
            )
        )


        content_url = (
            "/drive/preview/content?"
            + urlencode(
                {
                    "path":
                        item_path,
                }
            )
        )


        download_url = (
            "/drive/download?"
            + urlencode(
                {
                    "path":
                        item_path,
                }
            )
        )


        suffix = (
            name.rsplit(
                ".",
                1,
            )[-1].upper()
            if "." in name
            else "FILE"
        )


        return templates.TemplateResponse(
            request,
            "drive_preview.html",
            {
                "user":
                    user,

                "name":
                    name,

                "path":
                    item_path,

                "kind":
                    kind,

                "suffix":
                    suffix,

                "size_bytes":
                    size_bytes,

                "modified_at":
                    item.get(
                        "modified_at"
                    ),

                "content_url":
                    content_url,

                "download_url":
                    download_url,

                "back_url":
                    back_url,
            },
            headers={
                "Cache-Control":
                    "private, no-store",

                "X-Robots-Tag":
                    (
                        "noindex, nofollow, "
                        "noarchive"
                    ),

                "X-Content-Type-Options":
                    "nosniff",

                "Content-Security-Policy":
                    (
                        "default-src 'self'; "
                        "frame-src 'self'; "
                        "img-src 'self' data:; "
                        "style-src 'self'; "
                        "object-src 'none'; "
                        "base-uri 'none'; "
                        "form-action 'self'"
                    ),
            },
        )


    @app.get(
        "/drive/preview/content",
        include_in_schema=False,
    )
    async def preview_content(
        request: Request,
        path: str = "",
    ):

        if not current_user(
            request
        ):

            return login_redirect()


        item_path = clean_path(
            path
        )


        try:

            item = item_metadata(
                request,
                item_path,
            )

        except CoreAPIError as exc:

            raise HTTPException(
                status_code=getattr(
                    exc,
                    "status_code",
                    502,
                ),
                detail=exc.detail,
            ) from exc


        name = str(
            item.get(
                "name"
            )
            or PurePosixPath(
                item_path
            ).name
        )


        size_bytes = int(
            item.get(
                "size_bytes"
            )
            or 0
        )


        kind, media_type = (
            preview_spec(
                name,
                size_bytes,
            )
        )


        if kind == "unsupported":

            raise HTTPException(
                status_code=415,
                detail=(
                    "Format file ini "
                    "tidak mendukung preview."
                ),
            )


        session_token = (
            request.cookies.get(
                settings.core_cookie_name
            )
        )


        if not session_token:

            return login_redirect()


        client = httpx.AsyncClient(
            cookies={
                settings.core_cookie_name:
                    session_token
            },

            timeout=httpx.Timeout(
                connect=5,
                read=900,
                write=900,
                pool=5,
            ),

            follow_redirects=False,
        )


        upstream = (
            client.build_request(
                "GET",

                (
                    settings
                    .core_api_url
                    .rstrip("/")
                    + "/v1/drive/download"
                ),

                headers={
                    "Accept":
                        "*/*",

                    "User-Agent":
                        request.headers.get(
                            "user-agent",
                            (
                                "BotConnector "
                                "Drive Preview"
                            ),
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
                },

                params={
                    "path":
                        item_path,
                },
            )
        )


        try:

            response = (
                await client.send(
                    upstream,
                    stream=True,
                )
            )

        except httpx.RequestError as exc:

            await client.aclose()

            raise HTTPException(
                status_code=502,
                detail=(
                    "Preview sementara "
                    "tidak tersedia."
                ),
            ) from exc


        if response.status_code >= 400:

            await response.aread()

            code = (
                response.status_code
            )

            await response.aclose()
            await client.aclose()

            raise HTTPException(
                status_code=code,
                detail=(
                    "File tidak dapat "
                    "dipreview."
                ),
            )


        headers: dict[
            str,
            str,
        ] = {
            "Content-Disposition":
                (
                    "inline; "
                    "filename*=UTF-8''"
                    + quote(
                        name,
                        safe="",
                    )
                ),

            "Cache-Control":
                "private, no-store",

            "X-Content-Type-Options":
                "nosniff",
        }


        for key in (
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

                headers[
                    key
                ] = value


        async def close_stream() -> None:

            await response.aclose()
            await client.aclose()


        return StreamingResponse(
            response.aiter_raw(),
            status_code=200,
            media_type=media_type,
            headers=headers,
            background=BackgroundTask(
                close_stream
            ),
        )
