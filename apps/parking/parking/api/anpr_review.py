"""M10: ANPR Review API routes (operator workflow, role-aware)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from parking.api.deps import get_db, get_scope
from parking.anpr.service import AnprService
from parking.services.auth import Scope, require_role

router = APIRouter()


@router.get("/anpr/review")
def anpr_review(site_id: int | None = None, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    return AnprService(db, scope).list_review(site_id=site_id)


@router.post("/anpr/{event_id}/correct")
def anpr_correct(event_id: str, corrected_plate: str, reason: str | None = None,
                 db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    event = AnprService(db, scope).correct_plate(
        event_id, corrected_plate=corrected_plate, actor=scope.actor, reason=reason
    )
    return {"event_id": event.event_id, "plate_normalized": event.plate_normalized, "state": event.state}
