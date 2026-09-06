"""Configuration for the Parking application.

Credentials live in root-only env files (/etc/botconnector/parking.env for
systemd-style deployments, ~/.botconnector/parking.env for shell/test runs).
They are never committed to source and never logged.
"""

from __future__ import annotations

import os
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    data[key.strip()] = value.strip()
    except OSError:
        pass
    return data


def _env_urls() -> tuple[str | None, str | None]:
    if os.environ.get("PARKING_DATABASE_URL"):
        return os.environ["PARKING_DATABASE_URL"], os.environ.get("PARKING_TEST_DATABASE_URL")
    candidates = [
        Path.home() / ".botconnector" / "parking.env",
        Path("/etc/botconnector/parking.env"),
    ]
    for cand in candidates:
        env = _read_env_file(cand)
        if env.get("PARKING_DATABASE_URL"):
            return env["PARKING_DATABASE_URL"], env.get("PARKING_TEST_DATABASE_URL")
    raise RuntimeError(
        "PARKING_DATABASE_URL is not configured. Set the environment variable or "
        "create ~/.botconnector/parking.env / /etc/botconnector/parking.env"
    )


def database_url() -> str:
    url, _ = _env_urls()
    assert url is not None
    return url


def test_database_url() -> str:
    """Test database URL. Never silently falls back to the production DB: the
    suffix `_test` is enforced so destructive test bootstrap cannot hit prod."""
    _, url = _env_urls()
    if not url:
        base = database_url()
        head, sep, db = base.rpartition("/")
        if not db.endswith("_test"):
            db = db + "_test"
        url = f"{head}{sep}{db}"
    return url
