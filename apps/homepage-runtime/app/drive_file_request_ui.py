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
    File,
    Form,
    Request,
    UploadFile,
)

from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from .core_bridge import (
    CoreAPIError,
    api_request,
)


def register_drive_file_request_ui(
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


    def clean_path(
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

        query = {
            "path": path,
        }

        if notice:
            query[
                "notice"
            ] = notice

        if error:
            query[
                "error"
            ] = error

        return (
            "/drive/file-request?"
            + urlencode(
                query
            )
        )


    def request_url(
        token: str,
    ) -> str:

        return (
            "https://botconnector.id/r/"
            + token
        )


    def load_requests(
        request: Request,
        folder_path: str,
    ) -> list[
        dict[str, Any]
    ]:

        response = api_request(
            request,
            settings,
            "GET",
            "/v1/drive/file-requests",
        )

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            return []

        rows = payload.get(
            "requests"
        )

        if not isinstance(
            rows,
            list,
        ):
            return []

        result: list[
            dict[str, Any]
        ] = []

        for item in rows:

            if not isinstance(
                item,
                dict,
            ):
                continue

            if (
                item.get(
                    "folder_path"
                )
                != folder_path
            ):
                continue

            result.append(
                item
            )

        return result


    def render_owner(
        request: Request,
        *,
        folder_path: str,
        notice: str = "",
        error: str = "",
        created_link: str = "",
    ):

        rows: list[
            dict[str, Any]
        ] = []

        load_error = error

        try:

            rows = load_requests(
                request,
                folder_path,
            )

        except CoreAPIError as exc:

            if not load_error:
                load_error = (
                    exc.detail
                )


        folder_name = (
            folder_path.rsplit(
                "/",
                1,
            )[-1]
            if folder_path
            else ""
        )


        return templates.TemplateResponse(
            request,
            "drive_file_request.html",
            {
                "user":
                    current_user(
                        request
                    ),

                "folder_path":
                    folder_path,

                "folder_name":
                    folder_name,

                "requests":
                    rows,

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
        "/drive/file-request",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def file_request_manage(
        request: Request,

        path: str = "",

        notice: str = "",

        error: str = "",
    ):

        if not current_user(
            request
        ):

            return login_redirect()


        folder_path = clean_path(
            path
        )


        if not folder_path:

            return RedirectResponse(
                "/drive",
                status_code=303,
            )


        return render_owner(
            request,
            folder_path=folder_path,
            notice=notice,
            error=error,
        )


    @app.post(
        "/drive/file-request",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def create_file_request(
        request: Request,

        folder_path: str = Form(
            default=""
        ),

        request_name: str = Form(
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


        folder_path = clean_path(
            folder_path
        )

        request_name = (
            request_name
            .strip()
        )

        expires_in_days = (
            expires_in_days
            .strip()
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not folder_path:

            return RedirectResponse(
                "/drive",
                status_code=303,
            )


        if len(
            request_name
        ) > 160:

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=(
                        "Nama File Request "
                        "terlalu panjang."
                    ),
                ),
                status_code=303,
            )


        allowed_expiry = {
            "",
            "1",
            "7",
            "30",
            "90",
        }


        if (
            expires_in_days
            not in allowed_expiry
        ):

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=(
                        "Masa berlaku "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        payload: dict[
            str,
            Any,
        ] = {
            "folder_path":
                folder_path,
        }


        if request_name:

            payload[
                "request_name"
            ] = request_name


        if expires_in_days:

            payload[
                "expires_in_days"
            ] = int(
                expires_in_days
            )


        try:

            response = api_request(
                request,
                settings,
                "POST",
                "/v1/drive/file-requests",
                json_data=payload,
                csrf=True,
            )

            data = response.json()


            if not isinstance(
                data,
                dict,
            ):

                raise CoreAPIError(
                    502,
                    (
                        "Respons File Request "
                        "tidak valid."
                    ),
                )


            token = data.get(
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
                    (
                        "Token File Request "
                        "tidak tersedia."
                    ),
                )


        except CoreAPIError as exc:

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return render_owner(
            request,
            folder_path=folder_path,
            notice=(
                "File Request berhasil dibuat. "
                "Salin link sebelum meninggalkan "
                "halaman ini."
            ),
            created_link=request_url(
                token
            ),
        )


    @app.post(
        "/drive/file-request/revoke",
        include_in_schema=False,
    )
    def revoke_file_request(
        request: Request,

        request_id: str = Form(
            default=""
        ),

        folder_path: str = Form(
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


        folder_path = clean_path(
            folder_path
        )

        request_id = (
            request_id
            .strip()
        )


        if not valid_csrf(
            request,
            csrf_token,
        ):

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=(
                        "Token keamanan "
                        "tidak valid."
                    ),
                ),
                status_code=303,
            )


        if not request_id:

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=(
                        "Request ID "
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
                    "/v1/drive/file-requests/"
                    + request_id
                ),
                csrf=True,
            )


        except CoreAPIError as exc:

            return RedirectResponse(
                manage_url(
                    path=folder_path,
                    error=exc.detail,
                ),
                status_code=303,
            )


        return RedirectResponse(
            manage_url(
                path=folder_path,
                notice=(
                    "File Request "
                    "berhasil dicabut."
                ),
            ),
            status_code=303,
        )


    def render_public(
        request: Request,
        *,
        request_data: (
            dict[str, Any] | None
        ),
        error: str = "",
        success: str = "",
        uploaded_name: str = "",
        status_code: int = 200,
    ):

        return templates.TemplateResponse(
            request,
            "drive_file_request_public.html",
            {
                "request_data":
                    request_data,

                "error":
                    error,

                "success":
                    success,

                "uploaded_name":
                    uploaded_name,
            },
            status_code=status_code,
            headers={
                "X-Robots-Tag":
                    "noindex, nofollow, noarchive",

                "Cache-Control":
                    "private, no-store",

                "X-Content-Type-Options":
                    "nosniff",
            },
        )


    def load_public_info(
        request: Request,
        token: str,
    ) -> dict[str, Any]:

        response = api_request(
            request,
            settings,
            "GET",
            (
                "/v1/public/file-request/"
                + token
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
                    "Respons File Request "
                    "tidak valid."
                ),
            )


        data = payload.get(
            "request"
        )


        if not isinstance(
            data,
            dict,
        ):

            raise CoreAPIError(
                502,
                (
                    "File Request "
                    "tidak valid."
                ),
            )


        return data


    @app.get(
        "/r/{token}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def public_file_request(
        request: Request,
        token: str,
    ):

        try:

            data = load_public_info(
                request,
                token,
            )


        except CoreAPIError:

            return render_public(
                request,
                request_data=None,
                error=(
                    "File Request tidak ditemukan, "
                    "sudah kedaluwarsa, atau "
                    "akses telah dicabut."
                ),
                status_code=404,
            )


        return render_public(
            request,
            request_data=data,
        )


    @app.post(
        "/r/{token}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def public_file_request_upload(
        request: Request,

        token: str,

        upload: UploadFile = File(
            ...
        ),
    ):

        try:

            data = load_public_info(
                request,
                token,
            )


        except CoreAPIError:

            await upload.close()

            return render_public(
                request,
                request_data=None,
                error=(
                    "File Request tidak ditemukan, "
                    "sudah kedaluwarsa, atau "
                    "akses telah dicabut."
                ),
                status_code=404,
            )


        await upload.seek(0)


        filename = (
            upload.filename
            or "file"
        )


        media_type = (
            upload.content_type
            or "application/octet-stream"
        )


        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                None,
                connect=5.0,
            )
        )


        try:

            response = await client.post(
                (
                    settings
                    .core_api_url
                    .rstrip("/")
                    + "/v1/public/file-request/"
                    + token
                    + "/upload"
                ),

                files={
                    "upload": (
                        filename,
                        upload.file,
                        media_type,
                    ),
                },

                headers={
                    "Accept":
                        "application/json",

                    "User-Agent":
                        request.headers.get(
                            "user-agent",
                            (
                                "BotConnector "
                                "File Request"
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
            )


        except httpx.RequestError:

            return render_public(
                request,
                request_data=data,
                error=(
                    "Upload sedang tidak "
                    "dapat diproses."
                ),
                status_code=502,
            )


        finally:

            await upload.close()
            await client.aclose()


        if response.status_code >= 400:

            detail = (
                "Upload gagal."
            )

            try:

                payload = response.json()

                candidate = payload.get(
                    "detail"
                )

                if isinstance(
                    candidate,
                    str,
                ):
                    detail = candidate

            except Exception:
                pass


            return render_public(
                request,
                request_data=data,
                error=detail,
                status_code=(
                    response.status_code
                    if response.status_code
                    in (
                        400,
                        404,
                        409,
                        413,
                    )
                    else 502
                ),
            )


        try:

            payload = response.json()

        except ValueError:

            return render_public(
                request,
                request_data=data,
                error=(
                    "Respons upload "
                    "tidak valid."
                ),
                status_code=502,
            )


        uploaded_name = ""

        if isinstance(
            payload,
            dict,
        ):

            candidate = payload.get(
                "name"
            )

            if isinstance(
                candidate,
                str,
            ):
                uploaded_name = candidate


        return render_public(
            request,
            request_data=data,
            success=(
                "File berhasil dikirim."
            ),
            uploaded_name=
                uploaded_name,
            status_code=201,
        )
