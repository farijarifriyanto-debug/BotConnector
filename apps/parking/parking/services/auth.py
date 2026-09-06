"""Server-derived authorization scope.

Client-supplied tenant_id is never treated as authority. The bearer token is
resolved to an operator, and the operator's tenant becomes the authorized
scope for every query.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import OperatorStatus
from parking.models import ParkingOperator


def hash_api_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def fetch_core_session_info(cookie_token: str | None) -> tuple[dict | None, str | None]:
    """Validate bc_session cookie against BotConnector Core API and return (user, csrf_token)."""
    if not cookie_token:
        return None, None
    import json
    import os
    import urllib.error
    import urllib.request

    core_url = os.environ.get("BC_CORE_API_URL", "http://127.0.0.1:8050").rstrip("/")
    req = urllib.request.Request(
        f"{core_url}/v1/me",
        headers={"Cookie": f"bc_session={cookie_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            user = payload.get("user")
            csrf_token = payload.get("csrf_token")
            return (
                user if isinstance(user, dict) else None,
                csrf_token if isinstance(csrf_token, str) else None,
            )
    except Exception:
        return None, None


def fetch_core_user(cookie_token: str | None) -> dict | None:
    """Validate bc_session cookie against BotConnector Core API."""
    user, _ = fetch_core_session_info(cookie_token)
    return user


def fetch_core_entitled(cookie_token: str | None, product_slug: str = "parking") -> bool:
    """Check if bc_session has active access to the given product slug."""
    if not cookie_token:
        return False
    import json
    import os
    import urllib.error
    import urllib.request

    core_url = os.environ.get("BC_CORE_API_URL", "http://127.0.0.1:8050").rstrip("/")
    req = urllib.request.Request(
        f"{core_url}/v1/me/products",
        headers={"Cookie": f"bc_session={cookie_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            products = json.loads(resp.read().decode("utf-8"))
            if isinstance(products, list):
                for p in products:
                    if (
                        p.get("slug") == product_slug
                        and p.get("product_status") == "active"
                        and p.get("access_status") in ("active", "trial")
                    ):
                        return True
    except Exception:
        pass
    return False


def tenant_code_for_user(user_id: str) -> str:
    clean = user_id.replace("-", "").replace("_", "")
    return f"USER-{clean[-10:].upper()}" if len(clean) >= 10 else f"USER-{clean.upper()}"


def resolve_core_operator(session, cookie_token: str | None) -> ParkingOperator | None:
    """Resolve an authenticated, entitled BotConnector user to their ParkingOperator."""
    user = fetch_core_user(cookie_token)
    if not user:
        return None
    user_id = str(user.get("id", ""))
    if not user_id:
        return None
    if not fetch_core_entitled(cookie_token, "parking"):
        return None
    
    tenant_code = tenant_code_for_user(user_id)
    from parking.models import ParkingTenant
    tenant = session.scalar(select(ParkingTenant).where(ParkingTenant.code == tenant_code))
    if tenant is None:
        return None

    # Find the operator for this tenant
    operator = session.scalar(
        select(ParkingOperator).where(
            ParkingOperator.tenant_id == tenant.id,
            ParkingOperator.status == OperatorStatus.ACTIVE.value,
        ).order_by(ParkingOperator.id.asc())
    )
    return operator


def resolve_operator(session, token: str | None) -> ParkingOperator:
    if not token:
        raise ParkingError(ErrorCode.UNAUTHORIZED, "missing bearer token", status=401)
    operator = session.scalar(select(ParkingOperator).where(ParkingOperator.api_key_hash == hash_api_key(token)))
    if operator is None or operator.status != OperatorStatus.ACTIVE.value:
        raise ParkingError(ErrorCode.UNAUTHORIZED, "invalid or disabled credentials", status=401)
    return operator


@dataclass(frozen=True)
class Scope:
    tenant_id: int
    actor: str
    role: str = "OPERATOR"


def scope_from_operator(operator: ParkingOperator) -> Scope:
    return Scope(tenant_id=operator.tenant_id, actor=f"operator:{operator.username}", role=operator.role)


# Role hierarchy: higher index = more privilege.
_ROLE_RANK = {
    "VIEWER": 0,
    "OPERATOR": 1,
    "SUPERVISOR": 2,
    "MANAGER": 3,
    "ADMIN": 4,
    "OWNER": 5,
}

# Actions that require at least a given role.
_MUTATING_ROLES = {"OPERATOR", "SUPERVISOR", "MANAGER", "ADMIN", "OWNER"}
_MANAGER_ROLES = {"MANAGER", "ADMIN", "OWNER"}
_ADMIN_ROLES = {"ADMIN", "OWNER"}


def require_role(scope: Scope, minimum: str) -> None:
    """Enforce a minimum role server-side. VIEWER cannot mutate."""
    if _ROLE_RANK.get(scope.role, -1) < _ROLE_RANK.get(minimum, 0):
        raise ParkingError(ErrorCode.UNAUTHORIZED, f"role {scope.role} lacks permission", status=403)


def can_mutate(scope: Scope) -> bool:
    return scope.role in _MUTATING_ROLES


def can_manage(scope: Scope) -> bool:
    return scope.role in _MANAGER_ROLES


def can_admin(scope: Scope) -> bool:
    return scope.role in _ADMIN_ROLES
