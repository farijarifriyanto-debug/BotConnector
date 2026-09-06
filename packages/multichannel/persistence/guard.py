"""Shared production-safety guard for destructive acceptance suites.

This is the single reusable barrier that MUST execute before any:

- migration
- fixture setup
- DELETE
- TRUNCATE
- cleanup

in a destructive acceptance suite.

Design (fail CLOSED):
----------------------
The guard refuses destructive test work against the production database
unless ALL of the following hold:

  1. Explicit test-only mode is enabled.
     -> env BC_ACCEPTANCE_TEST=1 (or BC_BOTCONNECTOR_ACCEPTANCE=1)
  2. The resolved database name is NOT "botconnector".
  3. The connection is NOT the production endpoint.
     -> production host/port is refused.
  4. The database has an explicit isolated-test identity/marker.
     -> database name must start with the isolated-test prefix
        (e.g. "botconnector_test_").
  5. The destructive fixture is NOT using the production tenant
     LOCAL-PILOT (checked by the caller via require_test_tenant()).

On any violation the guard raises GuardError with a deterministic,
searchable message such as::

    REFUSING_DESTRUCTIVE_TEST_ON_PRODUCTION

If the database identity cannot be determined, the guard also fails
CLOSED (raises) rather than guessing safe.

Usage
-----
from botconnector_multichannel.persistence.guard import (
    assert_isolated_test_db, require_test_tenant,
)

# before ANY migration/fixture/delete/truncate/cleanup:
assert_isolated_test_db()

# before creating fixtures with a tenant:
require_test_tenant(tenant_id)  # refuses 'LOCAL-PILOT'

Helpers
-------
print_test_context()   -> prints the suite proof header:
    ACCEPTANCE_DATABASE=<db>
    ACCEPTANCE_TEST_MODE=YES/NO
    PRODUCTION_DATABASE=YES/NO
    TENANT=<tenant>

resolve_db_name()      -> the resolved database name without a live connection
                         (from env overrides) for fast pre-checks.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRODUCTION_DB_NAME = "botconnector"
PRODUCTION_TENANT = "LOCAL-PILOT"
ISOLATED_TEST_DB_PREFIX = "botconnector_test_"

# Hosts that must NEVER host destructive acceptance work.
PRODUCTION_HOST_MARKERS = ("botconnector-core-postgres", "172.19.", "127.0.0.1")

TEST_MODE_ENV_VARS = ("BC_ACCEPTANCE_TEST", "BC_BOTCONNECTOR_ACCEPTANCE")
ACCEPTANCE_DB_ENV = "BC_BOTCONNECTOR_ACCEPTANCE_DB"

DETERMINISTIC_ERROR = "REFUSING_DESTRUCTIVE_TEST_ON_PRODUCTION"


class GuardError(RuntimeError):
    """Raised when a destructive acceptance operation targets an unsafe target."""


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def resolve_db_name() -> str:
    """Resolve the database name this process would connect to.

    Prefer the env override; fall back to the production name. This mirrors
    persistence.runtime.resolved_db_name() but is standalone so the guard has
    no import cycle concerns.
    """
    from .runtime import resolved_db_name  # noqa: F401  (kept for parity)
    return os.environ.get(ACCEPTANCE_DB_ENV, PRODUCTION_DB_NAME)


def test_mode_enabled() -> bool:
    """True when an explicit test-only flag is present and truthy."""
    for var in TEST_MODE_ENV_VARS:
        val = os.environ.get(var, "").strip().lower()
        if val in ("1", "true", "yes", "on"):
            return True
    return False


def _resolved_host() -> str:
    """The host this process is configured to connect to (read-only)."""
    host = os.environ.get("BC_BOTCONNECTOR_DB_HOST", "").strip()
    if host:
        return host
    try:
        from .runtime import pg_ip
        return pg_ip()
    except Exception:
        return "unknown"


def _is_production_host(host: str) -> bool:
    return any(m in host for m in PRODUCTION_HOST_MARKERS)


def is_production_db() -> bool:
    """True if the resolved database looks like production."""
    db = resolve_db_name()
    host = _resolved_host()
    if db == PRODUCTION_DB_NAME:
        return True
    if _is_production_host(host):
        # A production host marker with the production db name is production.
        return True
    return False


# ---------------------------------------------------------------------------
# Core guard
# ---------------------------------------------------------------------------

def assert_isolated_test_db() -> None:
    """Fail CLOSED unless all production-safety requirements hold.

    Raises GuardError (REFUSING_DESTRUCTIVE_TEST_ON_PRODUCTION) on any
    violation.
    """
    db = resolve_db_name()
    host = _resolved_host()
    mode = test_mode_enabled()

    # 1. explicit test-only mode
    if not mode:
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: test-only mode not enabled "
            f"(set {' or '.join(TEST_MODE_ENV_VARS)}=1)"
        )

    # 2. database name is NOT production
    if db == PRODUCTION_DB_NAME:
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: resolved database is production "
            f"'{PRODUCTION_DB_NAME}'"
        )

    # 3. connection is NOT the production endpoint
    if _is_production_host(host):
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: connection targets production host "
            f"'{host}'"
        )

    # 4. explicit isolated-test identity/marker
    if not db.startswith(ISOLATED_TEST_DB_PREFIX):
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: database '{db}' does not carry the "
            f"isolated-test marker '{ISOLATED_TEST_DB_PREFIX}*'"
        )

    # 5. fail closed if identity cannot be determined
    if not db or not host or host == "unknown":
        raise GuardError(f"{DETERMINISTIC_ERROR}: cannot determine DB identity")


def require_test_tenant(tenant_id: Optional[str]) -> None:
    """Refuse destructive fixture work under the production tenant."""
    if tenant_id == PRODUCTION_TENANT:
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: tenant '{PRODUCTION_TENANT}' is the "
            f"production tenant; refusing destructive fixture"
        )
    if not tenant_id:
        raise GuardError(
            f"{DETERMINISTIC_ERROR}: empty tenant for destructive fixture"
        )


# ---------------------------------------------------------------------------
# Proof / context helpers
# ---------------------------------------------------------------------------

def print_test_context(tenant: Optional[str] = None) -> None:
    """Print the suite proof header used by isolated acceptance runs."""
    db = resolve_db_name()
    mode = "YES" if test_mode_enabled() else "NO"
    prod = "YES" if is_production_db() else "NO"
    print(f"ACCEPTANCE_DATABASE={db}")
    print(f"ACCEPTANCE_TEST_MODE={mode}")
    print(f"PRODUCTION_DATABASE={prod}")
    if tenant:
        print(f"TENANT={tenant}")
