"""Admin routes: sites, gates, lanes, operators — all tenant-scoped."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends

from parking.api.deps import get_db, get_scope
from parking.api.schemas import (
    GateCreate,
    GateRead,
    LaneCreate,
    LaneRead,
    OperatorCreate,
    OperatorRead,
    SiteCreate,
    SiteRead,
)
from parking.domain.errors import ErrorCode, ParkingError
from parking.repositories.registry import (
    GateRepository,
    LaneRepository,
    OperatorRepository,
    SiteRepository,
)
from parking.services.auth import Scope, _ROLE_RANK, hash_api_key, require_role

router = APIRouter()


def _site_repo(db, scope: Scope) -> SiteRepository:
    return SiteRepository(db, scope.tenant_id)


@router.post("/sites", response_model=SiteRead, status_code=201)
def create_site(body: SiteCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "ADMIN")
    site = _site_repo(db, scope).create(**body.model_dump())
    db.commit()
    db.refresh(site)
    return site


@router.get("/sites", response_model=list[SiteRead])
def list_sites(db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return _site_repo(db, scope).list()


@router.get("/sites/{site_id}", response_model=SiteRead)
def get_site(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return _site_repo(db, scope).get(site_id)


@router.post("/sites/{site_id}/gates", response_model=GateRead, status_code=201)
def create_gate(site_id: int, body: GateCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    gate = GateRepository(db, scope.tenant_id).create(site_id=site_id, **body.model_dump())
    db.commit()
    db.refresh(gate)
    return gate


@router.get("/sites/{site_id}/gates", response_model=list[GateRead])
def list_gates(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return GateRepository(db, scope.tenant_id).list(site_id)


@router.post("/sites/{site_id}/lanes", response_model=LaneRead, status_code=201)
def create_lane(site_id: int, body: LaneCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    payload = body.model_dump()
    payload["vehicle_types"] = [v.value if hasattr(v, "value") else v for v in payload["vehicle_types"]]
    lane = LaneRepository(db, scope.tenant_id).create(site_id=site_id, **payload)
    db.commit()
    db.refresh(lane)
    return lane


@router.get("/sites/{site_id}/lanes", response_model=list[LaneRead])
def list_lanes(site_id: int, gate_id: int | None = None, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return LaneRepository(db, scope.tenant_id).list(site_id, gate_id)


@router.post("/operators", response_model=OperatorRead, status_code=201)
def create_operator(body: OperatorCreate, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "ADMIN")
    target_role = body.role.value if hasattr(body.role, "value") else body.role
    if _ROLE_RANK.get(target_role, 0) > _ROLE_RANK.get(scope.role, 0):
        raise ParkingError(
            ErrorCode.UNAUTHORIZED,
            f"role escalation prohibited: cannot create operator with higher role {target_role}",
            status=403,
        )
    token = secrets.token_urlsafe(24)
    operator = OperatorRepository(db, scope.tenant_id).create(
        username=body.username,
        display_name=body.display_name,
        role=target_role,
        api_key_hash=hash_api_key(token),
    )
    db.commit()
    db.refresh(operator)
    result = OperatorRead.model_validate(operator)
    result.api_token = token  # plaintext returned exactly once
    return result
