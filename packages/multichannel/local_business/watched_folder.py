"""Watched-folder automation.

Controlled local/server file intake: incoming/ -> processing/ -> processed/
-> error/ -> archive/. Detects CSV/XLSX files. Uses content/file fingerprint
+ import batch id. The same file copied repeatedly must not duplicate business
data. Provides manual retry, error report, audit history.

Does not scan arbitrary filesystem paths outside configured connector folders.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..persistence.db import koneksi as _pg
from . import file_connector


def _now():
    return datetime.now(timezone.utc)


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def register_watched_folder(*, business_id: int, folder_path: str,
                            import_type: str = "SALES") -> dict:
    """Register a watched folder (must be under a configured connector root)."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            """INSERT INTO local_business.watched_folder
               (business_id, folder_path, import_type)
               VALUES (%s,%s,%s)
               ON CONFLICT (business_id, folder_path) DO UPDATE SET
                 import_type=EXCLUDED.import_type, status='ACTIVE'
               RETURNING id, folder_path, import_type""",
            (business_id, folder_path, import_type))
        r = cur.fetchone()
        c.commit()
        return r


def scan_watched_folder(*, watched_folder_id: int, root: str) -> dict:
    """Scan a watched folder for new files. Idempotent per fingerprint."""
    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM local_business.watched_folder WHERE id=%s", (watched_folder_id,))
        wf = cur.fetchone()
        if not wf:
            raise KeyError(f"watched_folder {watched_folder_id} tidak ada")
        c.commit()

    base = Path(root) / wf["folder_path"]
    incoming = base / "incoming"
    processing = base / "processing"
    processed = base / "processed"
    error = base / "error"
    archive = base / "archive"
    for d in (incoming, processing, processed, error, archive):
        d.mkdir(parents=True, exist_ok=True)

    results = {"found": 0, "processed": 0, "duplicates": 0, "errors": 0}
    for f in sorted(incoming.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".csv", ".xlsx"):
            continue
        results["found"] += 1
        fp = _fingerprint(f)
        # idempotency: same fingerprint -> skip
        with _pg() as c:
            cur = c.cursor()
            cur.execute(
                """SELECT id, status FROM local_business.watched_file
                   WHERE watched_folder_id=%s AND file_fingerprint=%s""",
                (watched_folder_id, fp))
            ada = cur.fetchone()
            if ada:
                results["duplicates"] += 1
                # move to archive
                shutil.move(str(f), str(archive / f.name))
                c.commit()
                continue
            cur.execute(
                """INSERT INTO local_business.watched_file
                   (watched_folder_id, filename, file_fingerprint, status)
                   VALUES (%s,%s,%s,'PROCESSING') RETURNING id""",
                (watched_folder_id, f.name, fp))
            wfid = cur.fetchone()["id"]
            c.commit()

        # move to processing
        proc_path = processing / f.name
        shutil.move(str(f), str(proc_path))

        # import
        try:
            content = proc_path.read_bytes()
            fmt = "XLSX" if proc_path.suffix.lower() == ".xlsx" else "CSV"
            res = file_connector.import_file(
                business_id=wf["business_id"], import_type=wf["import_type"],
                filename=proc_path.name, content=content, format=fmt,
                dry_run=False, idempotency_key=f"wf:{fp}")
            if res.get("duplicate"):
                results["duplicates"] += 1
            elif res.get("ok"):
                results["processed"] += 1
            else:
                results["errors"] += 1
            # move to processed or error
            if res.get("ok") and not res.get("duplicate"):
                shutil.move(str(proc_path), str(processed / proc_path.name))
                status = "PROCESSED"
            else:
                shutil.move(str(proc_path), str(error / proc_path.name))
                status = "ERROR"
            with _pg() as c:
                cur = c.cursor()
                cur.execute(
                    """UPDATE local_business.watched_file
                       SET status=%s, import_id=%s, error=%s, processed_at=now()
                       WHERE id=%s""",
                    (status, res.get("import_id"), res.get("error", ""), wfid))
                c.commit()
        except Exception as e:
            results["errors"] += 1
            shutil.move(str(proc_path), str(error / proc_path.name))
            with _pg() as c:
                cur = c.cursor()
                cur.execute(
                    """UPDATE local_business.watched_file
                       SET status='ERROR', error=%s, processed_at=now() WHERE id=%s""",
                    (f"{type(e).__name__}: {e}", wfid))
                c.commit()

    with _pg() as c:
        cur = c.cursor()
        cur.execute(
            "UPDATE local_business.watched_folder SET last_scan_at=now() WHERE id=%s",
            (watched_folder_id,))
        c.commit()
    return results
