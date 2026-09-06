"""M10-M11: Dashboard & Reports API routes (tenant-scoped, role-aware)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query

from parking.api.deps import get_db, get_scope
from parking.ops.dashboard import DashboardService
from parking.ops.reports import ReportService
from parking.services.auth import Scope, can_manage, require_role

router = APIRouter()


@router.get("/sites/{site_id}/dashboard")
def dashboard(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return DashboardService(db, scope).site_summary(site_id)


@router.get("/sites/{site_id}/live")
def live_parking(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return DashboardService(db, scope).live_parking(site_id)


@router.get("/sites/{site_id}/devices")
def device_health(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return DashboardService(db, scope).device_health(site_id)


@router.get("/sites/{site_id}/edges")
def edge_status(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    return DashboardService(db, scope).edge_status(site_id)


@router.get("/sites/{site_id}/reports/daily")
def daily_report(site_id: int, day: date, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).daily_operations(site_id, day)


@router.get("/sites/{site_id}/reports/revenue")
def revenue_report(site_id: int, start: datetime, end: datetime,
                   db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).revenue_report(site_id, start, end)


@router.get("/sites/{site_id}/reports/payments")
def payment_report(site_id: int, start: datetime, end: datetime,
                   db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).payment_report(site_id, start, end)


@router.get("/sites/{site_id}/reports/gates")
def gate_report(site_id: int, start: datetime, end: datetime,
                db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).gate_report(site_id, start, end)


@router.get("/sites/{site_id}/reports/anpr")
def anpr_report(site_id: int, start: datetime, end: datetime,
                db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).anpr_report(site_id, start, end)


@router.get("/sites/{site_id}/reports/edge")
def edge_report(site_id: int, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).edge_report(site_id)


@router.get("/audit")
def audit(site_id: int | None = None, actor: str | None = None, action: str | None = None,
          limit: int = Query(200, le=1000), db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    return ReportService(db, scope).audit(site_id=site_id, actor=actor, action=action, limit=limit)


@router.get("/sites/{site_id}/reports/daily/export")
def daily_export(site_id: int, day: date, db=Depends(get_db), scope: Scope = Depends(get_scope)):
    require_role(scope, "MANAGER")
    from fastapi.responses import PlainTextResponse
    svc = ReportService(db, scope)
    data = svc.daily_operations(site_id, day)
    csv_text = svc.export_csv([data], ["date", "site_id", "entries", "exits", "revenue", "manual_review"])
    return PlainTextResponse(csv_text, media_type="text/csv")
