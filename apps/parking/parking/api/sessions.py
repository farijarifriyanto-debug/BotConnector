"""Session routes: entry, scoped reads, and controlled lifecycle commands.

No generic PATCH /session/{id} endpoint exists — every mutation goes through
a named domain command.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from parking.api.deps import get_db, get_scope
from parking.api.schemas import (
    CalculateResponse,
    CancelRequest,
    CommandResponse,
    ComplimentaryRequest,
    EntryRequest,
    EntryResponse,
    EventRead,
    ExitRequest,
    LostTicketRequest,
    SessionRead,
)
from parking.services.auth import Scope, require_role
from parking.services.entry import EntryService
from parking.services.session_service import SessionService

router = APIRouter()


@router.post("/sessions/entry", response_model=EntryResponse, status_code=201)
def vehicle_entry(body: EntryRequest, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    payload = body.model_dump()
    payload["vehicle_type"] = payload["vehicle_type"].value if hasattr(payload["vehicle_type"], "value") else payload["vehicle_type"]
    session = EntryService(db, scope).create_entry(**payload)
    return EntryResponse(
        public_reference=session.public_reference,
        state=session.state,
        site_id=session.site_id,
        vehicle_type=session.vehicle_type,
        plate_normalized=session.plate_normalized,
        plate_display=session.plate_display,
        entry_at=session.entry_at,
    )


@router.get("/sessions/{public_reference}", response_model=SessionRead)
def get_session(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return SessionService(db, scope).get(public_reference)


@router.get("/sites/{site_id}/sessions", response_model=list[SessionRead])
def list_site_sessions(
    site_id: int, active: bool = False, state: str | None = None, db=Depends(get_db), scope: Scope = Depends(get_scope)
):
    service = SessionService(db, scope)
    if active:
        return [s for s in service.list_active(site_id)]
    return service.repo.list_by_site(site_id, state)


@router.post("/sessions/{public_reference}/calculate", response_model=CalculateResponse)
def calculate_tariff(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    result = SessionService(db, scope).calculate(public_reference)
    return CalculateResponse(
        public_reference=result["public_reference"],
        state=result["state"],
        duration_minutes=result["duration_minutes"],
        amount=result["amount"],
        currency=result["currency"],
        breakdown=result["breakdown"],
        plan=result["plan"],
    )


@router.post("/sessions/{public_reference}/initiate-payment", response_model=CommandResponse)
def initiate_payment(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    return _command_response(SessionService(db, scope).initiate_payment(public_reference))


@router.post("/sessions/{public_reference}/confirm-payment", response_model=CommandResponse)
def confirm_payment(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    return _command_response(SessionService(db, scope).confirm_payment(public_reference))


@router.post("/sessions/{public_reference}/authorize-exit", response_model=CommandResponse)
def authorize_exit(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    return _command_response(SessionService(db, scope).authorize_exit(public_reference))


@router.post("/sessions/{public_reference}/exit", response_model=CommandResponse)
def process_exit(public_reference: str, body: ExitRequest, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "OPERATOR")
    return _command_response(
        SessionService(db, scope).process_exit(
            public_reference, exit_gate_id=body.exit_gate_id, exit_lane_id=body.exit_lane_id, exit_at=body.exit_at
        )
    )


@router.post("/sessions/{public_reference}/cancel", response_model=CommandResponse)
def cancel_session(public_reference: str, body: CancelRequest | None = None, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "SUPERVISOR")
    return _command_response(SessionService(db, scope).cancel(public_reference, reason=body.reason if body else None))


@router.post("/sessions/{public_reference}/lost-ticket", response_model=CommandResponse)
def declare_lost_ticket(
    public_reference: str, body: LostTicketRequest | None = None, db=Depends(get_db), scope: Scope = Depends(get_scope)
):
    require_role(scope, "OPERATOR")
    return _command_response(
        SessionService(db, scope).declare_lost_ticket(public_reference, reason=body.reason if body else None)
    )


@router.post("/sessions/{public_reference}/complimentary", response_model=CommandResponse)
def apply_complimentary(
    public_reference: str, body: ComplimentaryRequest, db=Depends(get_db), scope: Scope = Depends(get_scope)
):
    require_role(scope, "SUPERVISOR")
    return _command_response(SessionService(db, scope).apply_complimentary(public_reference, body.reason))


@router.get("/sessions/{public_reference}/events", response_model=list[EventRead])
def list_events(public_reference: str, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    service = SessionService(db, scope)
    session = service.get(public_reference)
    return service.list_events(session)


def _command_response(session) -> CommandResponse:
    return CommandResponse(
        public_reference=session.public_reference,
        state=session.state,
        payment_state=session.payment_state,
        calculated_amount=session.calculated_amount,
        paid_amount=session.paid_amount,
        lost_ticket=session.lost_ticket,
    )
