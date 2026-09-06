from __future__ import annotations

import secrets

from pathlib import PurePosixPath

from typing import (
    Annotated,
    Any,
    Callable,
)

from urllib.parse import urlencode

import httpx

from fastapi import (
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
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


VALID_VIEWS = {
    "my",
    "recent",
    "starred",
    "trash",
}


def register_drive_ui(
    *,
    app: Any,
    templates: Any,
    settings: Any,
    current_user: Callable[
        [Request],
        dict[str, Any] | None,
    ],
) -> None:

    # ---------------------------------------------------------
    # AUTH / CSRF
    # ---------------------------------------------------------

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
            if isinstance(value, str)
            else ""
        )

    def require_local_csrf(
        request: Request,
        supplied: str,
    ) -> None:

        expected = csrf_value(
            request
        )

        if (
            not supplied
            or not expected
            or not secrets.compare_digest(
                supplied,
                expected,
            )
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Token CSRF tidak valid."
                ),
            )

    # ---------------------------------------------------------
    # CORE HELPERS
    # ---------------------------------------------------------

    def core_cookies(
        request: Request,
    ) -> dict[str, str]:

        token = request.cookies.get(
            settings.core_cookie_name
        )

        if not token:
            raise CoreAPIError(
                401,
                "Sesi tidak valid atau berakhir.",
            )

        return {
            settings.core_cookie_name:
                token
        }

    def core_headers(
        request: Request,
        *,
        csrf: bool = False,
    ) -> dict[str, str]:

        headers = {
            "Accept":
                "application/json",

            "User-Agent":
                request.headers.get(
                    "user-agent",
                    "BotConnector Drive UI",
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

        if csrf:

            token = csrf_value(
                request
            )

            if not token:
                raise CoreAPIError(
                    401,
                    (
                        "Sesi keamanan "
                        "tidak tersedia."
                    ),
                )

            headers[
                "X-CSRF-Token"
            ] = token

        return headers

    def core_url(
        endpoint: str,
    ) -> str:

        return (
            settings
            .core_api_url
            .rstrip("/")
            + "/"
            + endpoint.lstrip("/")
        )

    def core_error_detail(
        response: httpx.Response,
    ) -> str:

        try:
            payload = response.json()

            if isinstance(
                payload,
                dict,
            ):
                detail = payload.get(
                    "detail"
                )

                if isinstance(
                    detail,
                    str,
                ):
                    return detail

        except Exception:
            pass

        return (
            "BotConnector Drive tidak "
            "dapat memproses permintaan."
        )

    # ---------------------------------------------------------
    # DISPLAY HELPERS
    # ---------------------------------------------------------

    def human_size(
        raw: Any,
    ) -> str:

        if raw is None:
            return "—"

        try:
            value = float(raw)

        except (
            TypeError,
            ValueError,
        ):
            return "—"

        units = (
            "B",
            "KB",
            "MB",
            "GB",
            "TB",
        )

        for unit in units:

            if (
                value < 1024
                or unit == "TB"
            ):
                if unit == "B":
                    return (
                        f"{int(value)} B"
                    )

                return (
                    f"{value:.1f} "
                    f"{unit}"
                )

            value /= 1024

        return "—"

    def dirname_label(
        path: str,
    ) -> str:

        clean = path.strip("/")

        if not clean:
            return "My Drive"

        parent = str(
            PurePosixPath(clean).parent
        )

        if parent in {
            ".",
            "",
        }:
            return "My Drive"

        return parent

    def breadcrumbs(
        path: str,
    ) -> list[dict[str, str]]:

        result = [
            {
                "name":
                    "My Drive",

                "url":
                    "/drive?view=my",
            }
        ]

        clean = path.strip("/")

        if not clean:
            return result

        pieces: list[str] = []

        for part in clean.split("/"):

            if not part:
                continue

            pieces.append(
                part
            )

            result.append(
                {
                    "name":
                        part,

                    "url":
                        (
                            "/drive?"
                            + urlencode(
                                {
                                    "view":
                                        "my",

                                    "path":
                                        "/".join(
                                            pieces
                                        ),
                                }
                            )
                        ),
                }
            )

        return result

    def active_item(
        item: dict[str, Any],
    ) -> dict[str, Any]:

        result = dict(item)

        name = str(
            result.get("name")
            or "File"
        )

        path = str(
            result.get("path")
            or ""
        )

        kind = str(
            result.get("type")
            or "file"
        )

        suffix = (
            name.rsplit(
                ".",
                1,
            )[-1].lower()
            if "." in name
            else ""
        )

        if kind == "folder":
            icon = "folder"

            open_url = (
                "/drive?"
                + urlencode(
                    {
                        "view":
                            "my",

                        "path":
                            path,
                    }
                )
            )

        else:
            open_url = (
                "/drive/download?"
                + urlencode(
                    {
                        "path":
                            path,
                    }
                )
            )

            if suffix == "pdf":
                icon = "pdf"

            elif suffix in {
                "doc",
                "docx",
            }:
                icon = "document"

            elif suffix in {
                "xls",
                "xlsx",
                "csv",
            }:
                icon = "sheet"

            elif suffix in {
                "ppt",
                "pptx",
            }:
                icon = "slide"

            elif suffix in {
                "png",
                "jpg",
                "jpeg",
                "webp",
                "gif",
            }:
                icon = "image"

            else:
                icon = "file"

        result[
            "size_label"
        ] = human_size(
            result.get(
                "size_bytes"
            )
        )

        result[
            "location_label"
        ] = dirname_label(
            path
        )

        result[
            "open_url"
        ] = open_url

        # BOTCONNECTOR_DRIVE_PREVIEW_ITEM_V010
        if kind == "folder":

            result[
                "preview_url"
            ] = open_url

            result[
                "download_url"
            ] = ""

        else:

            result[
                "preview_url"
            ] = (
                "/drive/preview?"
                + urlencode(
                    {
                        "path":
                            path,
                    }
                )
            )

            result[
                "download_url"
            ] = open_url

        result[
            "icon"
        ] = icon

        result[
            "sort_size"
        ] = int(
            result.get(
                "size_bytes"
            )
            or 0
        )

        result[
            "starred"
        ] = bool(
            result.get(
                "starred",
                False,
            )
        )

        return result

    def trash_item(
        item: dict[str, Any],
    ) -> dict[str, Any]:

        result = dict(item)

        result[
            "size_label"
        ] = human_size(
            result.get(
                "size_bytes"
            )
        )

        original_path = str(
            result.get(
                "original_path"
            )
            or ""
        )

        result[
            "location_label"
        ] = dirname_label(
            original_path
        )

        result[
            "icon"
        ] = (
            "folder"
            if result.get(
                "type"
            ) == "folder"
            else "file"
        )

        result[
            "sort_size"
        ] = int(
            result.get(
                "size_bytes"
            )
            or 0
        )

        return result

    def return_url(
        *,
        view: str,
        path: str = "",
        notice: str = "",
        error: str = "",
    ) -> str:

        if view not in VALID_VIEWS:
            view = "my"

        params: dict[
            str,
            str,
        ] = {
            "view":
                view
        }

        if (
            view == "my"
            and path
        ):
            params[
                "path"
            ] = path

        if notice:
            params[
                "notice"
            ] = notice

        if error:
            params[
                "error"
            ] = error

        return (
            "/drive?"
            + urlencode(
                params
            )
        )

    def action_redirect(
        *,
        view: str,
        path: str,
        notice: str = "",
        error: str = "",
    ) -> RedirectResponse:

        return RedirectResponse(
            return_url(
                view=view,
                path=path,
                notice=notice,
                error=error,
            ),
            status_code=303,
        )


    # BOTCONNECTOR_DRIVE_FOLDER_PICKER_V022_BEGIN

    # ---------------------------------------------------------
    # SMART MOVE FOLDER PICKER
    # ---------------------------------------------------------

    def clean_drive_path(
        value: str,
    ) -> str:

        return (
            value
            .strip()
            .strip("/")
        )


    def parent_drive_path(
        value: str,
    ) -> str:

        clean = clean_drive_path(
            value
        )

        if not clean:
            return ""

        parent = str(
            PurePosixPath(
                clean
            ).parent
        )

        return (
            ""
            if parent == "."
            else parent
        )


    def folder_move_choices(
        request: Request,
        *,
        item_path: str,
        item_type: str,
    ) -> list[dict[str, Any]]:

        source = clean_drive_path(
            item_path
        )

        source_parent = (
            parent_drive_path(
                source
            )
        )

        kind = (
            item_type
            .strip()
            .lower()
        )

        result: list[
            dict[str, Any]
        ] = []

        # My Drive/root.
        # Jangan tampilkan kalau item sudah berada di root.
        if source_parent != "":

            result.append(
                {
                    "path":
                        "",

                    "name":
                        "My Drive",

                    "depth":
                        0,
                }
            )

        # Breadth-first traversal.
        #
        # Existing Core endpoint tetap menjadi sumber data,
        # sehingga tidak ada direct filesystem/NAS access
        # dari homepage.
        queue: list[
            tuple[str, int]
        ] = [
            ("", 0)
        ]

        visited = {
            ""
        }

        # Safety limit agar folder tree abnormal tidak
        # menyebabkan request tanpa batas.
        max_folders = 500
        max_depth = 20

        scanned = 0

        while (
            queue
            and scanned < max_folders
        ):

            directory, depth = (
                queue.pop(0)
            )

            if depth > max_depth:
                continue

            response = api_request(
                request,
                settings,
                "GET",
                "/v1/drive/list",
                params={
                    "path":
                        directory,
                },
            )

            payload = response.json()

            raw_items = (
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

            for item in raw_items:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                if item.get(
                    "type"
                ) != "folder":
                    continue

                folder_path = (
                    clean_drive_path(
                        str(
                            item.get(
                                "path"
                            )
                            or ""
                        )
                    )
                )

                if not folder_path:
                    continue

                if folder_path in visited:
                    continue

                visited.add(
                    folder_path
                )

                scanned += 1

                child_depth = (
                    folder_path.count(
                        "/"
                    )
                    + 1
                )

                # Tetap scan anaknya kecuali source folder
                # sendiri. Anak source folder juga tidak
                # perlu discan karena tidak boleh menjadi
                # target Move.
                is_source_tree = (
                    kind == "folder"
                    and (
                        folder_path == source
                        or folder_path.startswith(
                            source + "/"
                        )
                    )
                )

                if not is_source_tree:

                    queue.append(
                        (
                            folder_path,
                            child_depth,
                        )
                    )

                # Folder yang sekarang menjadi parent item
                # adalah no-op, jangan ditawarkan.
                if (
                    folder_path
                    == source_parent
                ):
                    continue

                # Folder tidak boleh dipindahkan ke dirinya
                # sendiri / descendant-nya.
                if is_source_tree:
                    continue

                result.append(
                    {
                        "path":
                            folder_path,

                        "name":
                            str(
                                item.get(
                                    "name"
                                )
                                or
                                PurePosixPath(
                                    folder_path
                                ).name
                            ),

                        "depth":
                            child_depth,
                    }
                )

                if scanned >= max_folders:
                    break

        result.sort(
            key=lambda row: (
                row["path"] != "",
                str(
                    row["path"]
                ).lower(),
            )
        )

        return result


    @app.get(
        "/drive/folder-options",
        include_in_schema=False,
    )
    def drive_folder_options(
        request: Request,
        item_path: str,
        item_type: str = "file",
    ):

        if not current_user(
            request
        ):
            raise HTTPException(
                status_code=401,
                detail=(
                    "Sesi tidak valid "
                    "atau berakhir."
                ),
            )

        try:

            choices = (
                folder_move_choices(
                    request,
                    item_path=item_path,
                    item_type=item_type,
                )
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

        return {
            "item_path":
                item_path,

            "item_type":
                item_type,

            "items":
                choices,

            "count":
                len(
                    choices
                ),
        }

    # BOTCONNECTOR_DRIVE_FOLDER_PICKER_V022_END

    # ---------------------------------------------------------
    # LARGE FILE FORWARDING
    # ---------------------------------------------------------

    async def upload_to_core(
        request: Request,
        *,
        path: str,
        upload: UploadFile,
    ) -> dict[str, Any]:

        await upload.seek(0)

        timeout = httpx.Timeout(
            connect=5,
            read=900,
            write=900,
            pool=5,
        )

        try:
            async with httpx.AsyncClient(
                cookies=core_cookies(
                    request
                ),
                timeout=timeout,
                follow_redirects=False,
            ) as client:

                response = await client.post(
                    core_url(
                        "/v1/drive/upload"
                    ),
                    headers=core_headers(
                        request,
                        csrf=True,
                    ),
                    data={
                        "path":
                            path,
                    },
                    files={
                        "upload":
                            (
                                (
                                    upload.filename
                                    or "file"
                                ),

                                upload.file,

                                (
                                    upload.content_type
                                    or
                                    "application/"
                                    "octet-stream"
                                ),
                            )
                    },
                )

        except httpx.RequestError as exc:
            raise CoreAPIError(
                502,
                (
                    "BotConnector Drive "
                    "sementara tidak "
                    "dapat dihubungi."
                ),
            ) from exc

        if response.status_code >= 400:
            raise CoreAPIError(
                response.status_code,
                core_error_detail(
                    response
                ),
            )

        return response.json()

    async def download_from_core(
        request: Request,
        *,
        path: str,
    ) -> StreamingResponse:

        client = httpx.AsyncClient(
            cookies=core_cookies(
                request
            ),
            timeout=httpx.Timeout(
                connect=5,
                read=900,
                write=900,
                pool=5,
            ),
            follow_redirects=False,
        )

        upstream = client.build_request(
            "GET",
            core_url(
                "/v1/drive/download"
            ),
            headers=core_headers(
                request
            ),
            params={
                "path":
                    path,
            },
        )

        try:
            response = await client.send(
                upstream,
                stream=True,
            )

        except httpx.RequestError as exc:
            await client.aclose()

            raise HTTPException(
                status_code=502,
                detail=(
                    "Download Drive "
                    "sementara tidak "
                    "tersedia."
                ),
            ) from exc

        if response.status_code >= 400:

            await response.aread()

            code = (
                response.status_code
            )

            detail = (
                core_error_detail(
                    response
                )
            )

            await response.aclose()
            await client.aclose()

            raise HTTPException(
                status_code=code,
                detail=detail,
            )

        outgoing: dict[
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
                outgoing[
                    header
                ] = value

        async def close_stream() -> None:
            await response.aclose()
            await client.aclose()

        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=outgoing,
            background=BackgroundTask(
                close_stream
            ),
        )

    # ---------------------------------------------------------
    # PAGE
    # ---------------------------------------------------------

    @app.get(
        "/drive",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def drive_page(
        request: Request,
        view: str = "my",
        path: str = "",
        notice: str = "",
        error: str = "",
    ):

        user = current_user(
            request
        )

        if not user:
            return login_redirect()

        if view not in VALID_VIEWS:
            view = "my"

        if view != "my":
            path = ""

        items: list[
            dict[str, Any]
        ] = []

        info: dict[
            str,
            Any,
        ] = {}

        load_error = error

        try:

            info_response = api_request(
                request,
                settings,
                "GET",
                "/v1/drive/info",
            )

            info_payload = (
                info_response.json()
            )

            if isinstance(
                info_payload,
                dict,
            ):
                info = info_payload

            if view == "my":

                response = api_request(
                    request,
                    settings,
                    "GET",
                    "/v1/drive/list",
                    params={
                        "path":
                            path,
                    },
                )

                payload = response.json()

                raw_items = (
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

                items = [
                    active_item(item)
                    for item in raw_items
                    if isinstance(
                        item,
                        dict,
                    )
                ]

            elif view == "recent":

                response = api_request(
                    request,
                    settings,
                    "GET",
                    "/v1/drive/recent",
                    params={
                        "limit":
                            100,
                    },
                )

                payload = response.json()

                raw_items = (
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

                items = [
                    active_item(item)
                    for item in raw_items
                    if isinstance(
                        item,
                        dict,
                    )
                ]

            elif view == "starred":

                response = api_request(
                    request,
                    settings,
                    "GET",
                    "/v1/drive/starred",
                )

                payload = response.json()

                raw_items = (
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

                items = [
                    active_item(item)
                    for item in raw_items
                    if isinstance(
                        item,
                        dict,
                    )
                ]

            elif view == "trash":

                response = api_request(
                    request,
                    settings,
                    "GET",
                    "/v1/drive/trash",
                )

                payload = response.json()

                raw_items = (
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

                items = [
                    trash_item(item)
                    for item in raw_items
                    if isinstance(
                        item,
                        dict,
                    )
                ]

        except CoreAPIError as exc:
            load_error = exc.detail

        clean = path.strip("/")

        parent_path = ""

        if "/" in clean:
            parent_path = clean.rsplit(
                "/",
                1,
            )[0]

        used_bytes = int(
            info.get(
                "used_bytes"
            )
            or 0
        )

        limit_raw = info.get(
            "limit_bytes"
        )

        limit_bytes = (
            int(limit_raw)
            if limit_raw
            else 0
        )

        usage_percent = 0

        if limit_bytes > 0:
            usage_percent = min(
                100,
                int(
                    (
                        used_bytes
                        / limit_bytes
                    )
                    * 100
                ),
            )

        title_map = {
            "my":
                "My Drive",

            "recent":
                "Recent",

            "starred":
                "Starred",

            "trash":
                "Trash",
        }

        subtitle_map = {
            "my":
                (
                    "File pribadi Anda "
                    "di BotConnector Drive."
                ),

            "recent":
                (
                    "File dan folder yang "
                    "terakhir diubah."
                ),

            "starred":
                (
                    "File dan folder penting "
                    "yang Anda tandai."
                ),

            "trash":
                (
                    "Item yang dapat "
                    "dipulihkan atau "
                    "dihapus permanen."
                ),
        }

        return templates.TemplateResponse(
            request,
            "drive.html",
            {
                "user":
                    user,

                "view":
                    view,

                "view_title":
                    title_map[view],

                "view_subtitle":
                    subtitle_map[view],

                "path":
                    path,

                "parent_path":
                    parent_path,

                "breadcrumbs":
                    (
                        breadcrumbs(
                            path
                        )
                        if view == "my"
                        else []
                    ),

                "items":
                    items,

                "drive_info":
                    info,

                "used_label":
                    human_size(
                        used_bytes
                    ),

                "limit_label":
                    (
                        human_size(
                            limit_bytes
                        )
                        if limit_bytes
                        else ""
                    ),

                "usage_percent":
                    usage_percent,

                "quota_enabled":
                    limit_bytes > 0,

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

    # ---------------------------------------------------------
    # BASIC v0.1 MUTATIONS
    # ---------------------------------------------------------

    @app.post(
        "/drive/folders",
        include_in_schema=False,
    )
    def create_folder(
        request: Request,

        path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",

        name: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/folders",
                json_data={
                    "path":
                        path,

                    "name":
                        name,
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view="my",
                path=path,
                error=exc.detail,
            )

        return action_redirect(
            view="my",
            path=path,
            notice=(
                "Folder berhasil dibuat."
            ),
        )

    @app.post(
        "/drive/upload",
        include_in_schema=False,
    )
    async def upload(
        request: Request,

        path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",

        upload: UploadFile = File(
            ...
        ),
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            await upload_to_core(
                request,
                path=path,
                upload=upload,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view="my",
                path=path,
                error=exc.detail,
            )

        finally:
            await upload.close()

        return action_redirect(
            view="my",
            path=path,
            notice=(
                "File berhasil diunggah."
            ),
        )

    @app.get(
        "/drive/download",
        include_in_schema=False,
    )
    async def download(
        request: Request,
        path: str,
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        return await download_from_core(
            request,
            path=path,
        )

    # ---------------------------------------------------------
    # v0.2 ACTIONS
    # ---------------------------------------------------------

    @app.post(
        "/drive/actions/rename",
        include_in_schema=False,
    )
    def rename(
        request: Request,

        item_path: Annotated[
            str,
            Form(),
        ],

        new_name: Annotated[
            str,
            Form(),
        ],

        return_view: Annotated[
            str,
            Form(),
        ] = "my",

        return_path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/rename",
                json_data={
                    "path":
                        item_path,

                    "new_name":
                        new_name,
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view=return_view,
                path=return_path,
                error=exc.detail,
            )

        return action_redirect(
            view=return_view,
            path=return_path,
            notice=(
                "Nama berhasil diubah."
            ),
        )

    @app.post(
        "/drive/actions/move",
        include_in_schema=False,
    )
    def move(
        request: Request,

        item_path: Annotated[
            str,
            Form(),
        ],

        destination: Annotated[
            str,
            Form(),
        ] = "",

        return_view: Annotated[
            str,
            Form(),
        ] = "my",

        return_path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/move",
                json_data={
                    "path":
                        item_path,

                    "destination":
                        (
                            ""
                            if destination == "__ROOT__"
                            else destination
                        ),
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view=return_view,
                path=return_path,
                error=exc.detail,
            )

        return action_redirect(
            view=return_view,
            path=return_path,
            notice=(
                "Item berhasil dipindahkan."
            ),
        )

    @app.post(
        "/drive/actions/star",
        include_in_schema=False,
    )
    def star(
        request: Request,

        item_path: Annotated[
            str,
            Form(),
        ],

        starred: Annotated[
            str,
            Form(),
        ] = "true",

        return_view: Annotated[
            str,
            Form(),
        ] = "my",

        return_path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        value = (
            starred
            .strip()
            .lower()
            in {
                "1",
                "true",
                "yes",
                "on",
            }
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/star",
                json_data={
                    "path":
                        item_path,

                    "starred":
                        value,
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view=return_view,
                path=return_path,
                error=exc.detail,
            )

        return action_redirect(
            view=return_view,
            path=return_path,
            notice=(
                (
                    "Ditambahkan ke Starred."
                    if value
                    else
                    "Dihapus dari Starred."
                )
            ),
        )

    @app.post(
        "/drive/actions/trash",
        include_in_schema=False,
    )
    def trash(
        request: Request,

        item_path: Annotated[
            str,
            Form(),
        ],

        return_view: Annotated[
            str,
            Form(),
        ] = "my",

        return_path: Annotated[
            str,
            Form(),
        ] = "",

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/trash",
                json_data={
                    "path":
                        item_path,
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view=return_view,
                path=return_path,
                error=exc.detail,
            )

        return action_redirect(
            view=return_view,
            path=return_path,
            notice=(
                "Item dipindahkan ke Trash."
            ),
        )

    @app.post(
        "/drive/actions/restore",
        include_in_schema=False,
    )
    def restore(
        request: Request,

        trash_id: Annotated[
            str,
            Form(),
        ],

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "POST",
                "/v1/drive/restore",
                json_data={
                    "trash_id":
                        trash_id,
                },
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view="trash",
                error=exc.detail,
            )

        return action_redirect(
            view="trash",
            notice=(
                "Item berhasil dipulihkan."
            ),
        )

    @app.post(
        "/drive/actions/purge",
        include_in_schema=False,
    )
    def purge(
        request: Request,

        trash_id: Annotated[
            str,
            Form(),
        ],

        csrf_token: Annotated[
            str,
            Form(),
        ] = "",
    ):

        if not current_user(
            request
        ):
            return login_redirect()

        require_local_csrf(
            request,
            csrf_token,
        )

        try:
            api_request(
                request,
                settings,
                "DELETE",
                (
                    "/v1/drive/trash/"
                    + trash_id
                ),
                csrf=True,
            )

        except CoreAPIError as exc:
            return action_redirect(
                view="trash",
                error=exc.detail,
            )

        return action_redirect(
            view="trash",
            notice=(
                "Item dihapus permanen."
            ),
        )
