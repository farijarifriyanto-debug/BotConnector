"""BotConnector Parking — Customer portal service.

Handles user session resolution, product entitlement check, first-run idempotent
provisioning for FULL_STACK / EXISTING_HARDWARE / PAYMENT_ONLY profiles, safe
sandbox simulator triggers, and deployment profile upgrades.
"""

from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from parking.domain.enums import OperatorRole, OperatorStatus, TenantStatus
from parking.domain.errors import ErrorCode, ParkingError
from parking.gate.runtime import GateRuntimeService
from parking.gate.runtime_repo import GateRuntimeRepository, LaneRuntimeRepository
from parking.models import (
    ParkingGate,
    ParkingLane,
    ParkingOperator,
    ParkingSite,
    ParkingTariffPlan,
    ParkingTariffRule,
    ParkingTenant,
)
from parking.repositories.registry import (
    GateRepository,
    LaneRepository,
    OperatorRepository,
    SiteRepository,
    TenantRepository,
)
from parking.repositories.session_repo import SessionRepository
from parking.repositories.tariff_repo import TariffPlanRepository
from parking.services.auth import (
    Scope,
    fetch_core_entitled,
    fetch_core_session_info,
    fetch_core_user,
    hash_api_key,
)
from parking.services.entry import EntryService
from parking.services.session_service import SessionService


class CustomerService:
    @staticmethod
    def core_api_url() -> str:
        return os.environ.get("BC_CORE_API_URL", "http://127.0.0.1:8050").rstrip("/")

    @classmethod
    def activate_product(cls, cookie_token: str) -> dict[str, Any]:
        """Activate parking entitlement on BotConnector Core for the user."""
        if not cookie_token:
            raise ParkingError(ErrorCode.UNAUTHORIZED, "Sesi login diperlukan untuk aktivasi", status=401)

        user, csrf_token = fetch_core_session_info(cookie_token)
        if not user or not csrf_token:
            raise ParkingError(
                ErrorCode.UNAUTHORIZED,
                "Sesi login tidak valid atau telah berakhir. Silakan login ulang.",
                status=401,
            )

        headers = {
            "Cookie": f"bc_session={cookie_token}",
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        req = urllib.request.Request(
            f"{cls.core_api_url()}/v1/me/products/parking/activate",
            data=b"{}",
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ParkingError(
                    ErrorCode.UNAUTHORIZED,
                    "Produk BotConnector Parking tidak ditemukan di katalog.",
                    status=404,
                )
            if exc.code in (401, 403):
                raise ParkingError(
                    ErrorCode.UNAUTHORIZED,
                    "Sesi autentikasi telah kedaluwarsa atau tidak memiliki izin aktivasi. Silakan masuk ulang.",
                    status=403,
                )
            raise ParkingError(
                ErrorCode.INTERNAL_ERROR,
                "Aktivasi belum berhasil. Silakan coba lagi.",
                status=502,
            )
        except Exception:
            raise ParkingError(
                ErrorCode.INTERNAL_ERROR,
                "Layanan autentikasi sedang tidak dapat dihubungi. Silakan coba lagi.",
                status=503,
            )

    @classmethod
    def get_context(cls, session, cookie_token: str | None) -> dict[str, Any]:
        """Get authenticated customer state, entitlement, tenant, and primary site."""
        user = fetch_core_user(cookie_token)
        if not user:
            return {
                "authenticated": False,
                "user": None,
                "entitled": False,
                "provisioned": False,
                "tenant": None,
                "site": None,
                "api_token": None,
                "deployment_profile": None,
            }

        user_id = str(user.get("id", ""))
        entitled = fetch_core_entitled(cookie_token, "parking")
        from parking.services.auth import tenant_code_for_user
        tenant_code = tenant_code_for_user(user_id)

        tenant = session.scalar(select(ParkingTenant).where(ParkingTenant.code == tenant_code))
        if not tenant:
            return {
                "authenticated": True,
                "user": user,
                "entitled": entitled,
                "provisioned": False,
                "tenant": None,
                "site": None,
                "api_token": None,
                "deployment_profile": None,
            }

        # Find primary site and operator
        site = session.scalar(
            select(ParkingSite).where(ParkingSite.tenant_id == tenant.id).order_by(ParkingSite.id.asc())
        )
        operator = session.scalar(
            select(ParkingOperator).where(ParkingOperator.tenant_id == tenant.id).order_by(ParkingOperator.id.asc())
        )

        return {
            "authenticated": True,
            "user": user,
            "entitled": entitled,
            "provisioned": True,
            "tenant": {
                "id": tenant.id,
                "code": tenant.code,
                "name": tenant.name,
                "status": tenant.status,
                "deployment_profile": tenant.deployment_profile,
                "webhook_url": tenant.webhook_url,
                "webhook_secret": tenant.webhook_secret,
            },
            "site": (
                {
                    "id": site.id,
                    "code": site.code,
                    "name": site.name,
                    "capacity_total": site.capacity_total,
                }
                if site
                else None
            ),
            "operator": (
                {
                    "id": operator.id,
                    "username": operator.username,
                    "role": operator.role,
                }
                if operator
                else None
            ),
            "deployment_profile": tenant.deployment_profile,
        }

    @classmethod
    def provision(cls, session, cookie_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Idempotently provision a tenant, operator, and initial infrastructure."""
        user = fetch_core_user(cookie_token)
        if not user:
            raise ParkingError(ErrorCode.UNAUTHORIZED, "Authentication required", status=401)
        user_id = str(user.get("id", ""))
        user_email = str(user.get("email") or f"user_{user_id[:8]}@botconnector.id")
        user_name = str(user.get("display_name") or user.get("name") or "Operator")

        # Auto-activate entitlement if not already active
        if not fetch_core_entitled(cookie_token, "parking"):
            try:
                cls.activate_product(cookie_token)
            except Exception:
                pass

        from parking.services.auth import tenant_code_for_user
        tenant_code = tenant_code_for_user(user_id)
        tenant_name = str(payload.get("organization_name") or f"Parking {user_name}").strip()
        deployment_profile = str(payload.get("deployment_profile") or "FULL_STACK").upper()
        if deployment_profile not in ("FULL_STACK", "EXISTING_HARDWARE", "PAYMENT_ONLY"):
            deployment_profile = "FULL_STACK"

        wh_url = payload.get("webhook_url")
        wh_token = secrets.token_hex(24)

        # 1. Create or get Tenant
        tenant = session.scalar(select(ParkingTenant).where(ParkingTenant.code == tenant_code))
        if tenant is None:
            tenant = ParkingTenant(
                code=tenant_code,
                name=tenant_name,
                status=TenantStatus.ACTIVE.value,
                deployment_profile=deployment_profile,
            )
            tenant.webhook_url = wh_url
            setattr(tenant, "webhook_secret", wh_token)
            session.add(tenant)
            session.flush()
        else:
            tenant.deployment_profile = deployment_profile
            if wh_url:
                tenant.webhook_url = wh_url
            session.flush()

        # 2. Create or get Operator
        raw_token = secrets.token_urlsafe(24)
        operator = session.scalar(
            select(ParkingOperator).where(
                ParkingOperator.tenant_id == tenant.id,
                ParkingOperator.username == user_email,
            )
        )
        if operator is None:
            operator = ParkingOperator(
                tenant_id=tenant.id,
                username=user_email,
                display_name=user_name,
                role=OperatorRole.OWNER.value,
                status=OperatorStatus.ACTIVE.value,
                api_key_hash=hash_api_key(raw_token),
            )
            session.add(operator)
            session.flush()
            api_token = raw_token
        else:
            api_token = "EXISTING_SESSION"

        site_id = None
        # 3. If FULL_STACK or EXISTING_HARDWARE, create Site, Gates, Lanes, Tariff
        if deployment_profile in ("FULL_STACK", "EXISTING_HARDWARE"):
            site_code = str(payload.get("site_code") or "SITE-01").strip().upper()
            site_name = str(payload.get("site_name") or "Area Parkir Utama").strip()
            capacity = int(payload.get("capacity") or 100)

            site = session.scalar(
                select(ParkingSite).where(
                    ParkingSite.tenant_id == tenant.id,
                    ParkingSite.code == site_code,
                )
            )
            if site is None:
                site = ParkingSite(
                    tenant_id=tenant.id,
                    code=site_code,
                    name=site_name,
                    capacity_total=capacity,
                    capacity_car=int(capacity * 0.7),
                    capacity_motorcycle=int(capacity * 0.3),
                    currency="IDR",
                    status="ACTIVE",
                )
                session.add(site)
                session.flush()

            site_id = site.id

            # Gates
            entry_gate_code = str(payload.get("entry_gate_code") or "G-ENTRY").strip().upper()
            gate_in = session.scalar(
                select(ParkingGate).where(
                    ParkingGate.tenant_id == tenant.id,
                    ParkingGate.site_id == site.id,
                    ParkingGate.code == entry_gate_code,
                )
            )
            if gate_in is None:
                gate_in = ParkingGate(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    code=entry_gate_code,
                    name="Gerbang Masuk",
                    direction="ENTRY",
                    status="ACTIVE",
                )
                session.add(gate_in)
                session.flush()

            exit_gate_code = str(payload.get("exit_gate_code") or "G-EXIT").strip().upper()
            gate_out = session.scalar(
                select(ParkingGate).where(
                    ParkingGate.tenant_id == tenant.id,
                    ParkingGate.site_id == site.id,
                    ParkingGate.code == exit_gate_code,
                )
            )
            if gate_out is None:
                gate_out = ParkingGate(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    code=exit_gate_code,
                    name="Gerbang Keluar",
                    direction="EXIT",
                    status="ACTIVE",
                )
                session.add(gate_out)
                session.flush()

            # Lanes
            lane_in = session.scalar(
                select(ParkingLane).where(
                    ParkingLane.tenant_id == tenant.id,
                    ParkingLane.site_id == site.id,
                    ParkingLane.code == "L-ENTRY",
                )
            )
            if lane_in is None:
                lane_in = ParkingLane(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    gate_id=gate_in.id,
                    code="L-ENTRY",
                    name="Lane Masuk 1",
                    direction="ENTRY",
                    vehicle_types=["CAR", "MOTORCYCLE"],
                    status="ACTIVE",
                )
                session.add(lane_in)
                session.flush()

            lane_out = session.scalar(
                select(ParkingLane).where(
                    ParkingLane.tenant_id == tenant.id,
                    ParkingLane.site_id == site.id,
                    ParkingLane.code == "L-EXIT",
                )
            )
            if lane_out is None:
                lane_out = ParkingLane(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    gate_id=gate_out.id,
                    code="L-EXIT",
                    name="Lane Keluar 1",
                    direction="EXIT",
                    vehicle_types=["CAR", "MOTORCYCLE"],
                    status="ACTIVE",
                )
                session.add(lane_out)
                session.flush()

            # Initialize Gate & Lane Runtime to ONLINE
            gate_rt_repo = GateRuntimeRepository(session, tenant.id)
            gate_rt_repo.get_or_create(site_id=site.id, gate_id=gate_in.id)
            gate_rt_repo.get_or_create(site_id=site.id, gate_id=gate_out.id)

            lane_rt_repo = LaneRuntimeRepository(session, tenant.id)
            lane_rt_repo.get_or_create(site_id=site.id, lane_id=lane_in.id)
            lane_rt_repo.get_or_create(site_id=site.id, lane_id=lane_out.id)

            # Tariff plan & rules
            tariff_plan = session.scalar(
                select(ParkingTariffPlan).where(
                    ParkingTariffPlan.tenant_id == tenant.id,
                    ParkingTariffPlan.site_id == site.id,
                    ParkingTariffPlan.code == "TARIF-01",
                )
            )
            if tariff_plan is None:
                tariff_plan = ParkingTariffPlan(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    code="TARIF-01",
                    name="Tarif Standar",
                    currency="IDR",
                    grace_period_minutes=10,
                    daily_max_amount=50000,
                    status="ACTIVE",
                )
                session.add(tariff_plan)
                session.flush()

                rule_type = str(payload.get("tariff_type") or "FLAT").upper()
                rate = int(payload.get("rate") or 5000)
                if rule_type == "HOURLY":
                    rule_config = {"first_hour_amount": rate, "subsequent_hour_amount": rate, "rounding": "CEILING"}
                else:
                    rule_type = "FLAT"
                    rule_config = {"amount": rate}

                for vtype in ("CAR", "MOTORCYCLE"):
                    rule = ParkingTariffRule(
                        tenant_id=tenant.id,
                        site_id=site.id,
                        plan_id=tariff_plan.id,
                        vehicle_type=vtype,
                        rule_type=rule_type,
                        config=rule_config if vtype == "CAR" else {"amount": max(2000, rate // 2)},
                        precedence=10,
                    )
                    session.add(rule)

        session.commit()

        return {
            "status": "ok",
            "message": "Pengaturan awal BotConnector Parking berhasil diselesaikan.",
            "tenant_id": tenant.id,
            "tenant_code": tenant.code,
            "site_id": site_id,
            "deployment_profile": tenant.deployment_profile,
            "api_token": api_token,
            "webhook_secret": tenant.webhook_secret,
        }

    @classmethod
    def update_profile(cls, session, tenant_id: int, new_profile: str, webhook_url: str | None = None) -> dict:
        tenant = session.scalar(select(ParkingTenant).where(ParkingTenant.id == tenant_id))
        if not tenant:
            raise ParkingError(ErrorCode.TENANT_NOT_FOUND, "Tenant not found", status=404)
        if new_profile.upper() not in ("FULL_STACK", "EXISTING_HARDWARE", "PAYMENT_ONLY"):
            raise ParkingError(ErrorCode.VALIDATION_ERROR, "Invalid deployment profile", status=400)

        tenant.deployment_profile = new_profile.upper()
        if webhook_url is not None:
            tenant.webhook_url = webhook_url.strip()
        session.commit()
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "deployment_profile": tenant.deployment_profile,
            "webhook_url": tenant.webhook_url,
        }
