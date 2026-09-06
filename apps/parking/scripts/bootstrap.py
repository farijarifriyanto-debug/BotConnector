"""Bootstrap: create the first Parking tenant and an ADMIN operator.

Usage:
    .venv/bin/python scripts/bootstrap.py <tenant_code> <tenant_name> <admin_username>

The generated admin API token is written (root/home-only) to
~/.botconnector/parking.dev.operator.token and is never printed.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from parking.config import database_url
from parking.db import make_session_factory
from parking.domain.enums import OperatorRole
from parking.repositories.registry import OperatorRepository, TenantRepository
from parking.services.auth import hash_api_key


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    tenant_code, tenant_name, admin_username = sys.argv[1:4]

    engine, factory = make_session_factory(database_url())
    with factory() as session:
        tenants = TenantRepository(session)
        tenant = tenants.get_by_code(tenant_code)
        if tenant is None:
            tenant = tenants.create(code=tenant_code, name=tenant_name)
            print(f"tenant created: {tenant.code} (id={tenant.id})")
        else:
            print(f"tenant exists: {tenant.code} (id={tenant.id})")

        token = secrets.token_urlsafe(24)
        operators = OperatorRepository(session, tenant.id)
        existing = operators.get_by_api_key_hash(hash_api_key(token))
        if existing is None:
            operators.create(
                username=admin_username,
                display_name=admin_username,
                role=OperatorRole.ADMIN.value,
                api_key_hash=hash_api_key(token),
            )
        session.commit()

    token_path = Path.home() / ".botconnector" / "parking.dev.operator.token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token + "\n")
    token_path.chmod(0o600)
    print(f"admin token written to {token_path} (chmod 600, never printed)")


if __name__ == "__main__":
    main()
