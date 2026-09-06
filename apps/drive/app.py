from __future__ import annotations

import os
import re
import secrets
import shutil
import sqlite3
import time

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

from typing import Annotated

from uuid import (
    UUID,
    uuid4,
)

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from fastapi.responses import (
    FileResponse,
)

from pydantic import (
    BaseModel,
    Field,
)


APP_VERSION = "0.2.0"

ROOT = Path(
    os.environ.get(
        "DRIVE_ROOT",
        "/data/drive",
    )
).resolve()

USERS_ROOT = (
    ROOT / "users"
).resolve()

TRASH_ROOT = (
    ROOT / "trash"
).resolve()

META_DB = Path(
    os.environ.get(
        "DRIVE_META_DB",
        "/data/meta/drive.sqlite3",
    )
)

INTERNAL_TOKEN = (
    os.environ[
        "DRIVE_INTERNAL_TOKEN"
    ]
)

MAX_UPLOAD_MB = int(
    os.environ.get(
        "DRIVE_MAX_UPLOAD_MB",
        "512",
    )
)

MAX_UPLOAD_BYTES = (
    MAX_UPLOAD_MB
    * 1024
    * 1024
)

QUOTA_BYTES = int(
    os.environ.get(
        "DRIVE_QUOTA_BYTES",
        "0",
    )
)

_CONTROL = re.compile(
    r"[\x00-\x1f\x7f]"
)


app = FastAPI(
    title=(
        "BotConnector Drive "
        "Internal API"
    ),
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class FolderCreate(BaseModel):
    path: str = ""

    name: str = Field(
        min_length=1,
        max_length=180,
    )


class RenameRequest(BaseModel):
    path: str

    new_name: str = Field(
        min_length=1,
        max_length=180,
    )


class MoveRequest(BaseModel):
    path: str
    destination: str = ""


class StarRequest(BaseModel):
    path: str
    starred: bool = True


class TrashRequest(BaseModel):
    path: str


class RestoreRequest(BaseModel):
    trash_id: str


def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def canonical_user_id(
    raw: str,
) -> str:
    try:
        return str(UUID(raw))

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "User ID tidak valid."
            ),
        ) from exc


def internal_identity(
    x_bc_drive_token: Annotated[
        str | None,
        Header(
            alias="X-BC-Drive-Token"
        ),
    ] = None,

    x_bc_user_id: Annotated[
        str | None,
        Header(
            alias="X-BC-User-ID"
        ),
    ] = None,
) -> str:

    if (
        not x_bc_drive_token
        or not secrets.compare_digest(
            x_bc_drive_token,
            INTERNAL_TOKEN,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "Internal token "
                "tidak valid."
            ),
        )

    if not x_bc_user_id:
        raise HTTPException(
            status_code=400,
            detail="User ID wajib.",
        )

    return canonical_user_id(
        x_bc_user_id
    )


def init_db() -> None:
    META_DB.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    last_error: Exception | None = None

    for _ in range(50):

        connection = None

        try:
            connection = sqlite3.connect(
                META_DB,
                timeout=10,
            )

            connection.execute(
                "PRAGMA busy_timeout=10000"
            )

            connection.execute(
                "PRAGMA journal_mode=WAL"
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS starred (
                    user_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    starred_at TEXT NOT NULL,
                    PRIMARY KEY (
                        user_id,
                        path
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trash_items (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    trash_path TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_trash_user_deleted
                ON trash_items (
                    user_id,
                    deleted_at DESC
                )
                """
            )

            connection.commit()

            return

        except sqlite3.OperationalError as exc:
            last_error = exc

            if "locked" not in str(
                exc
            ).lower():
                raise

            time.sleep(0.1)

        finally:
            if connection is not None:
                connection.close()

    if last_error:
        raise last_error


def db_connect() -> sqlite3.Connection:
    connection = sqlite3.connect(
        META_DB,
        timeout=10,
    )

    connection.row_factory = (
        sqlite3.Row
    )

    connection.execute(
        "PRAGMA busy_timeout=10000"
    )

    return connection


init_db()


def ensure_roots() -> None:
    USERS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    TRASH_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


def user_root(
    user_id: str,
) -> Path:
    ensure_roots()

    root = (
        USERS_ROOT / user_id
    ).resolve()

    try:
        root.relative_to(
            USERS_ROOT
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "User storage path "
                "tidak valid."
            ),
        ) from exc

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return root


def trash_user_root(
    user_id: str,
) -> Path:
    ensure_roots()

    root = (
        TRASH_ROOT / user_id
    ).resolve()

    try:
        root.relative_to(
            TRASH_ROOT
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Trash path "
                "tidak valid."
            ),
        ) from exc

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return root


def resolve_user_path(
    user_id: str,
    relative: str | None,
    *,
    must_exist: bool = False,
) -> Path:

    root = user_root(user_id)

    rel = (
        relative or ""
    ).strip()

    if "\x00" in rel:
        raise HTTPException(
            status_code=400,
            detail="Path tidak valid.",
        )

    candidate = (
        root / rel
    ).resolve()

    try:
        candidate.relative_to(
            root
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Path keluar dari "
                "drive user."
            ),
        ) from exc

    if (
        must_exist
        and not candidate.exists()
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "File atau folder "
                "tidak ditemukan."
            ),
        )

    return candidate


def resolve_trash_path(
    user_id: str,
    relative: str,
    *,
    must_exist: bool = False,
) -> Path:

    root = trash_user_root(
        user_id
    )

    candidate = (
        root / relative
    ).resolve()

    try:
        candidate.relative_to(
            root
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Trash path "
                "tidak valid."
            ),
        ) from exc

    if (
        must_exist
        and not candidate.exists()
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Item Trash "
                "tidak ditemukan."
            ),
        )

    return candidate


def forbid_root(
    user_id: str,
    path: Path,
) -> None:
    if path == user_root(
        user_id
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Root My Drive "
                "tidak dapat diubah."
            ),
        )


def safe_name(
    raw: str | None,
) -> str:

    candidate = Path(
        raw or "file"
    ).name

    candidate = _CONTROL.sub(
        "_",
        candidate,
    )

    candidate = (
        candidate
        .strip()
        .strip(".")
    )

    if (
        not candidate
        or candidate
        in {".", ".."}
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Nama file/folder "
                "tidak valid."
            ),
        )

    if (
        "/" in candidate
        or "\\" in candidate
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Nama file/folder "
                "tidak valid."
            ),
        )

    return candidate[:180]


def unique_target(
    directory: Path,
    filename: str,
) -> Path:

    target = (
        directory / filename
    )

    if not target.exists():
        return target

    original = Path(filename)

    stem = original.stem
    suffix = original.suffix

    for number in range(
        1,
        10000,
    ):
        candidate = (
            directory
            / (
                f"{stem} "
                f"({number})"
                f"{suffix}"
            )
        )

        if not candidate.exists():
            return candidate

    raise HTTPException(
        status_code=409,
        detail=(
            "Tidak dapat menentukan "
            "nama file unik."
        ),
    )


def path_size(
    path: Path,
) -> int:

    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total = 0

    for base, _, files in os.walk(
        path
    ):
        for filename in files:

            candidate = (
                Path(base)
                / filename
            )

            try:
                total += (
                    candidate
                    .stat()
                    .st_size
                )

            except OSError:
                continue

    return total



# BOTCONNECTOR_DRIVE_DYNAMIC_QUOTA_V010
def effective_quota_bytes(
    raw: str | None,
) -> int:

    if raw is None or raw == "":
        return QUOTA_BYTES

    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Quota internal tidak valid.",
        )

    if value < 0:
        raise HTTPException(
            status_code=400,
            detail="Quota internal tidak valid.",
        )

    return value


def usage_stats(
    user_id: str,
    quota_bytes: int | None = None,
) -> dict:

    limit_bytes = (
        QUOTA_BYTES
        if quota_bytes is None
        else quota_bytes
    )

    root = user_root(
        user_id
    )

    trash = trash_user_root(
        user_id
    )

    active_bytes = 0
    trash_bytes = 0

    files = 0
    folders = 0

    for base, dirs, names in os.walk(
        root
    ):
        folders += len(dirs)

        for filename in names:
            candidate = (
                Path(base)
                / filename
            )

            try:
                active_bytes += (
                    candidate
                    .stat()
                    .st_size
                )

                files += 1

            except OSError:
                continue

    for base, _, names in os.walk(
        trash
    ):
        for filename in names:
            candidate = (
                Path(base)
                / filename
            )

            try:
                trash_bytes += (
                    candidate
                    .stat()
                    .st_size
                )

            except OSError:
                continue

    used = (
        active_bytes
        + trash_bytes
    )

    remaining = None

    if limit_bytes > 0:
        remaining = max(
            limit_bytes - used,
            0,
        )

    return {
        "used_bytes": used,
        "active_bytes":
            active_bytes,
        "trash_bytes":
            trash_bytes,
        "file_count": files,
        "folder_count":
            folders,
        "limit_bytes": (
            limit_bytes
            if limit_bytes > 0
            else None
        ),
        "remaining_bytes":
            remaining,
    }


def starred_paths(
    user_id: str,
) -> set[str]:

    with db_connect() as db:
        rows = db.execute(
            """
            SELECT path
            FROM starred
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

    return {
        str(row["path"])
        for row in rows
    }


def item_info(
    root: Path,
    item: Path,
    *,
    stars: set[str]
    | None = None,
) -> dict:

    stat = item.stat()

    relative = (
        item
        .relative_to(root)
        .as_posix()
    )

    return {
        "name": item.name,
        "path": relative,
        "type": (
            "folder"
            if item.is_dir()
            else "file"
        ),
        "size_bytes": (
            stat.st_size
            if item.is_file()
            else None
        ),
        "modified_at":
            datetime.fromtimestamp(
                stat.st_mtime,
                tz=timezone.utc,
            ).isoformat(),

        "starred": (
            relative in stars
            if stars is not None
            else False
        ),
    }


def rewrite_starred_prefix(
    user_id: str,
    old_prefix: str,
    new_prefix: str,
) -> None:

    with db_connect() as db:

        rows = db.execute(
            """
            SELECT path, starred_at
            FROM starred
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

        for row in rows:

            current = str(
                row["path"]
            )

            if not (
                current
                == old_prefix
                or current.startswith(
                    old_prefix + "/"
                )
            ):
                continue

            suffix = current[
                len(old_prefix):
            ]

            rewritten = (
                new_prefix
                + suffix
            )

            db.execute(
                """
                DELETE FROM starred
                WHERE user_id = ?
                AND path = ?
                """,
                (
                    user_id,
                    current,
                ),
            )

            db.execute(
                """
                INSERT OR REPLACE
                INTO starred (
                    user_id,
                    path,
                    starred_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    rewritten,
                    str(
                        row[
                            "starred_at"
                        ]
                    ),
                ),
            )

        db.commit()


def remove_starred_prefix(
    user_id: str,
    prefix: str,
) -> None:

    with db_connect() as db:

        rows = db.execute(
            """
            SELECT path
            FROM starred
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

        for row in rows:

            value = str(
                row["path"]
            )

            if (
                value == prefix
                or value.startswith(
                    prefix + "/"
                )
            ):
                db.execute(
                    """
                    DELETE FROM starred
                    WHERE user_id = ?
                    AND path = ?
                    """,
                    (
                        user_id,
                        value,
                    ),
                )

        db.commit()


def recent_items(
    user_id: str,
    limit: int,
) -> list[dict]:

    root = user_root(
        user_id
    )

    stars = starred_paths(
        user_id
    )

    found: list[
        tuple[float, Path]
    ] = []

    for base, dirs, files in os.walk(
        root
    ):

        base_path = Path(base)

        for name in dirs + files:

            if name.startswith(
                ".bc_"
            ):
                continue

            candidate = (
                base_path / name
            )

            try:
                mtime = (
                    candidate
                    .stat()
                    .st_mtime
                )

            except OSError:
                continue

            found.append(
                (
                    mtime,
                    candidate,
                )
            )

    found.sort(
        key=lambda row: row[0],
        reverse=True,
    )

    result = []

    for _, item in found[
        :limit
    ]:
        try:
            result.append(
                item_info(
                    root,
                    item,
                    stars=stars,
                )
            )

        except OSError:
            continue

    return result


@app.get("/health")
def health() -> dict:

    try:
        stat = os.statvfs(
            ROOT
        )

        with db_connect() as db:
            db.execute(
                "SELECT 1"
            ).fetchone()

        return {
            "status": "ok",
            "version":
                APP_VERSION,
            "storage":
                "available",
            "metadata":
                "available",
            "free_bytes":
                (
                    stat.f_bavail
                    * stat.f_frsize
                ),
            "max_upload_mb":
                MAX_UPLOAD_MB,
        }

    except (
        OSError,
        sqlite3.Error,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Drive unavailable: "
                f"{exc}"
            ),
        ) from exc


@app.get(
    "/internal/v1/drive/info"
)
def drive_info(
    x_bc_quota_bytes: Annotated[
        str | None,
        Header(
            alias="X-BC-Quota-Bytes"
        ),
    ] = None,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    usage = usage_stats(
        user_id,
        effective_quota_bytes(
            x_bc_quota_bytes
        ),
    )

    return {
        "user_id": user_id,
        "drive_root_ready":
            root.is_dir(),
        "max_upload_mb":
            MAX_UPLOAD_MB,
        **usage,
    }


@app.get(
    "/internal/v1/drive/quota"
)
def drive_quota(
    x_bc_quota_bytes: Annotated[
        str | None,
        Header(
            alias="X-BC-Quota-Bytes"
        ),
    ] = None,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    return usage_stats(
        user_id,
        effective_quota_bytes(
            x_bc_quota_bytes
        ),
    )


@app.get(
    "/internal/v1/drive/list"
)
def list_items(
    path: str = Query(
        default=""
    ),

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    directory = resolve_user_path(
        user_id,
        path,
        must_exist=True,
    )

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "Path bukan folder."
            ),
        )

    stars = starred_paths(
        user_id
    )

    entries = []

    for item in directory.iterdir():

        if item.name.startswith(
            ".bc_"
        ):
            continue

        try:
            entries.append(
                item_info(
                    root,
                    item,
                    stars=stars,
                )
            )

        except OSError:
            continue

    entries.sort(
        key=lambda item: (
            item["type"]
            != "folder",

            item["name"]
            .lower(),
        )
    )

    return {
        "path": (
            directory
            .relative_to(root)
            .as_posix()
            if directory != root
            else ""
        ),
        "items": entries,
    }


@app.post(
    "/internal/v1/drive/folders",
    status_code=201,
)
def create_folder(
    payload: FolderCreate,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    parent = resolve_user_path(
        user_id,
        payload.path,
        must_exist=True,
    )

    if not parent.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "Folder induk "
                "tidak valid."
            ),
        )

    name = safe_name(
        payload.name
    )

    target = (
        parent / name
    )

    try:
        target.relative_to(
            root
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Path tidak valid."
            ),
        ) from exc

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "Nama folder "
                "sudah ada."
            ),
        )

    target.mkdir()

    return item_info(
        root,
        target,
        stars=starred_paths(
            user_id
        ),
    )


@app.post(
    "/internal/v1/drive/upload",
    status_code=201,
)
async def upload_file(
    path: Annotated[
        str,
        Form(),
    ] = "",

    upload: UploadFile = File(
        ...
    ),

    x_bc_quota_bytes: Annotated[
        str | None,
        Header(
            alias="X-BC-Quota-Bytes"
        ),
    ] = None,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    quota_bytes = (
        effective_quota_bytes(
            x_bc_quota_bytes
        )
    )

    root = user_root(
        user_id
    )

    directory = resolve_user_path(
        user_id,
        path,
        must_exist=True,
    )

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "Tujuan upload "
                "bukan folder."
            ),
        )

    filename = safe_name(
        upload.filename
    )

    target = unique_target(
        directory,
        filename,
    )

    size = 0

    used_before = None

    if quota_bytes > 0:
        used_before = (
            usage_stats(
                user_id
            )[
                "used_bytes"
            ]
        )

    try:
        with target.open(
            "xb"
        ) as handle:

            while True:

                chunk = await upload.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                size += len(
                    chunk
                )

                if (
                    MAX_UPLOAD_BYTES > 0
                    and size
                    > MAX_UPLOAD_BYTES
                ):
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "File melebihi "
                            f"{MAX_UPLOAD_MB} MB."
                        ),
                    )

                if (
                    quota_bytes > 0
                    and used_before
                    is not None
                    and (
                        used_before
                        + size
                    )
                    > quota_bytes
                ):
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Kuota Drive "
                            "tidak mencukupi."
                        ),
                    )

                handle.write(
                    chunk
                )

    except Exception:
        target.unlink(
            missing_ok=True
        )

        raise

    finally:
        await upload.close()

    return item_info(
        root,
        target,
        stars=starred_paths(
            user_id
        ),
    )


@app.get(
    "/internal/v1/drive/download"
)
def download_file(
    path: str,

    user_id: str = Depends(
        internal_identity
    ),
) -> FileResponse:

    target = resolve_user_path(
        user_id,
        path,
        must_exist=True,
    )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail=(
                "Path bukan file."
            ),
        )

    return FileResponse(
        target,
        filename=target.name,
        media_type=(
            "application/"
            "octet-stream"
        ),
    )


@app.post(
    "/internal/v1/drive/rename"
)
def rename_item(
    payload: RenameRequest,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    source = resolve_user_path(
        user_id,
        payload.path,
        must_exist=True,
    )

    forbid_root(
        user_id,
        source,
    )

    new_name = safe_name(
        payload.new_name
    )

    target = (
        source.parent
        / new_name
    ).resolve()

    try:
        target.relative_to(
            root
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Tujuan rename "
                "tidak valid."
            ),
        ) from exc

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "Nama tujuan "
                "sudah digunakan."
            ),
        )

    old_relative = (
        source
        .relative_to(root)
        .as_posix()
    )

    new_relative = (
        target
        .relative_to(root)
        .as_posix()
    )

    source.rename(
        target
    )

    rewrite_starred_prefix(
        user_id,
        old_relative,
        new_relative,
    )

    return item_info(
        root,
        target,
        stars=starred_paths(
            user_id
        ),
    )


@app.post(
    "/internal/v1/drive/move"
)
def move_item(
    payload: MoveRequest,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    source = resolve_user_path(
        user_id,
        payload.path,
        must_exist=True,
    )

    forbid_root(
        user_id,
        source,
    )

    destination = resolve_user_path(
        user_id,
        payload.destination,
        must_exist=True,
    )

    if not destination.is_dir():
        raise HTTPException(
            status_code=400,
            detail=(
                "Tujuan move "
                "bukan folder."
            ),
        )

    if source.is_dir():
        if (
            destination == source
            or destination.is_relative_to(
                source
            )
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Folder tidak dapat "
                    "dipindah ke dirinya "
                    "sendiri."
                ),
            )

    target = (
        destination
        / source.name
    ).resolve()

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "Item dengan nama "
                "yang sama sudah ada "
                "di tujuan."
            ),
        )

    old_relative = (
        source
        .relative_to(root)
        .as_posix()
    )

    new_relative = (
        target
        .relative_to(root)
        .as_posix()
    )

    source.rename(
        target
    )

    rewrite_starred_prefix(
        user_id,
        old_relative,
        new_relative,
    )

    return item_info(
        root,
        target,
        stars=starred_paths(
            user_id
        ),
    )


@app.post(
    "/internal/v1/drive/star"
)
def star_item(
    payload: StarRequest,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    target = resolve_user_path(
        user_id,
        payload.path,
        must_exist=True,
    )

    forbid_root(
        user_id,
        target,
    )

    relative = (
        target
        .relative_to(root)
        .as_posix()
    )

    with db_connect() as db:

        if payload.starred:

            db.execute(
                """
                INSERT OR REPLACE
                INTO starred (
                    user_id,
                    path,
                    starred_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    user_id,
                    relative,
                    now_iso(),
                ),
            )

        else:
            db.execute(
                """
                DELETE FROM starred
                WHERE user_id = ?
                AND path = ?
                """,
                (
                    user_id,
                    relative,
                ),
            )

        db.commit()

    return {
        "path": relative,
        "starred":
            payload.starred,
    }


@app.get(
    "/internal/v1/drive/starred"
)
def list_starred(
    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    with db_connect() as db:

        rows = db.execute(
            """
            SELECT path, starred_at
            FROM starred
            WHERE user_id = ?
            ORDER BY starred_at DESC
            """,
            (user_id,),
        ).fetchall()

    result = []

    stale = []

    for row in rows:

        relative = str(
            row["path"]
        )

        target = resolve_user_path(
            user_id,
            relative,
            must_exist=False,
        )

        if not target.exists():
            stale.append(
                relative
            )
            continue

        try:
            result.append(
                item_info(
                    root,
                    target,
                    stars={
                        relative
                    },
                )
            )

        except OSError:
            stale.append(
                relative
            )

    if stale:
        with db_connect() as db:

            for relative in stale:
                db.execute(
                    """
                    DELETE FROM starred
                    WHERE user_id = ?
                    AND path = ?
                    """,
                    (
                        user_id,
                        relative,
                    ),
                )

            db.commit()

    return {
        "items": result
    }


@app.get(
    "/internal/v1/drive/recent"
)
def list_recent(
    limit: int = Query(
        default=100,
        ge=1,
        le=200,
    ),

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    return {
        "items":
            recent_items(
                user_id,
                limit,
            )
    }


@app.post(
    "/internal/v1/drive/trash"
)
def move_to_trash(
    payload: TrashRequest,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    source = resolve_user_path(
        user_id,
        payload.path,
        must_exist=True,
    )

    forbid_root(
        user_id,
        source,
    )

    original_path = (
        source
        .relative_to(root)
        .as_posix()
    )

    trash_id = uuid4().hex

    trash_root = (
        trash_user_root(
            user_id
        )
    )

    trash_container = (
        trash_root
        / trash_id
    )

    trash_container.mkdir(
        parents=False,
        exist_ok=False,
    )

    target = (
        trash_container
        / source.name
    )

    source.rename(
        target
    )

    try:
        size = path_size(
            target
        )

        relative_trash = (
            target
            .relative_to(
                trash_root
            )
            .as_posix()
        )

        with db_connect() as db:

            db.execute(
                """
                INSERT INTO
                trash_items (
                    id,
                    user_id,
                    original_path,
                    trash_path,
                    item_name,
                    item_type,
                    size_bytes,
                    deleted_at
                )
                VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    trash_id,
                    user_id,
                    original_path,
                    relative_trash,
                    target.name,
                    (
                        "folder"
                        if target.is_dir()
                        else "file"
                    ),
                    size,
                    now_iso(),
                ),
            )

            db.commit()

    except Exception:

        if (
            target.exists()
            and not source.exists()
        ):
            target.rename(
                source
            )

        try:
            trash_container.rmdir()
        except OSError:
            pass

        raise

    remove_starred_prefix(
        user_id,
        original_path,
    )

    return {
        "id": trash_id,
        "name": target.name,
        "original_path":
            original_path,
        "type": (
            "folder"
            if target.is_dir()
            else "file"
        ),
        "size_bytes": size,
    }


@app.get(
    "/internal/v1/drive/trash"
)
def list_trash(
    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    with db_connect() as db:

        rows = db.execute(
            """
            SELECT *
            FROM trash_items
            WHERE user_id = ?
            ORDER BY deleted_at DESC
            """,
            (user_id,),
        ).fetchall()

    items = []

    stale = []

    for row in rows:

        trash_id = str(
            row["id"]
        )

        relative = str(
            row["trash_path"]
        )

        target = resolve_trash_path(
            user_id,
            relative,
            must_exist=False,
        )

        if not target.exists():
            stale.append(
                trash_id
            )
            continue

        items.append(
            {
                "id":
                    trash_id,
                "name":
                    str(
                        row[
                            "item_name"
                        ]
                    ),
                "original_path":
                    str(
                        row[
                            "original_path"
                        ]
                    ),
                "type":
                    str(
                        row[
                            "item_type"
                        ]
                    ),
                "size_bytes":
                    int(
                        row[
                            "size_bytes"
                        ]
                    ),
                "deleted_at":
                    str(
                        row[
                            "deleted_at"
                        ]
                    ),
            }
        )

    if stale:
        with db_connect() as db:

            for trash_id in stale:
                db.execute(
                    """
                    DELETE FROM
                    trash_items
                    WHERE id = ?
                    AND user_id = ?
                    """,
                    (
                        trash_id,
                        user_id,
                    ),
                )

            db.commit()

    return {
        "items": items
    }


@app.post(
    "/internal/v1/drive/restore"
)
def restore_from_trash(
    payload: RestoreRequest,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    root = user_root(
        user_id
    )

    with db_connect() as db:

        row = db.execute(
            """
            SELECT *
            FROM trash_items
            WHERE id = ?
            AND user_id = ?
            """,
            (
                payload.trash_id,
                user_id,
            ),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Item Trash "
                "tidak ditemukan."
            ),
        )

    source = resolve_trash_path(
        user_id,
        str(
            row[
                "trash_path"
            ]
        ),
        must_exist=True,
    )

    target = resolve_user_path(
        user_id,
        str(
            row[
                "original_path"
            ]
        ),
        must_exist=False,
    )

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                "Lokasi restore "
                "sudah berisi item "
                "dengan nama yang sama."
            ),
        )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source.rename(
        target
    )

    try:
        with db_connect() as db:

            db.execute(
                """
                DELETE FROM trash_items
                WHERE id = ?
                AND user_id = ?
                """,
                (
                    payload.trash_id,
                    user_id,
                ),
            )

            db.commit()

    except Exception:

        if (
            target.exists()
            and not source.exists()
        ):
            source.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.rename(
                source
            )

        raise

    try:
        source.parent.rmdir()
    except OSError:
        pass

    return item_info(
        root,
        target,
        stars=starred_paths(
            user_id
        ),
    )


@app.delete(
    "/internal/v1/drive/trash/{trash_id}"
)
def purge_trash_item(
    trash_id: str,

    user_id: str = Depends(
        internal_identity
    ),
) -> dict:

    with db_connect() as db:

        row = db.execute(
            """
            SELECT trash_path
            FROM trash_items
            WHERE id = ?
            AND user_id = ?
            """,
            (
                trash_id,
                user_id,
            ),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Item Trash "
                "tidak ditemukan."
            ),
        )

    target = resolve_trash_path(
        user_id,
        str(
            row[
                "trash_path"
            ]
        ),
        must_exist=False,
    )

    container = target.parent

    if target.exists():

        if target.is_dir():
            shutil.rmtree(
                target
            )
        else:
            target.unlink()

    with db_connect() as db:

        db.execute(
            """
            DELETE FROM trash_items
            WHERE id = ?
            AND user_id = ?
            """,
            (
                trash_id,
                user_id,
            ),
        )

        db.commit()

    try:
        container.rmdir()
    except OSError:
        pass

    return {
        "deleted": True,
        "id": trash_id,
    }
