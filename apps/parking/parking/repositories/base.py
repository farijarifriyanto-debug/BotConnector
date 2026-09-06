"""Tenant-scoped repository base.

Every object lookup carries the authorized tenant scope; a foreign-tenant
object is indistinguishable from a missing one (404 semantics).
"""

from __future__ import annotations

from parking.domain.errors import ErrorCode, ParkingError


class ScopedRepository:
    def __init__(self, session, tenant_id: int):
        self.session = session
        self.tenant_id = tenant_id

    @staticmethod
    def not_found(code: str, message: str) -> ParkingError:
        return ParkingError(code, message, status=404)

    def not_found_tenant_scoped(self, code: str, label: str) -> ParkingError:
        return ParkingError(
            code, f"{label} not found for this tenant", status=404, details={"tenant_id": self.tenant_id}
        )
