"""Tariff snapshots: freeze the exact plan/rule inputs that produced an amount
so historical sessions stay explainable and deterministic even after the live
plan is edited."""

from __future__ import annotations

import math
from datetime import datetime

from parking.tariff.config import validate_config
from parking.tariff.engine import BreakdownItem, RuleView, TariffResult, calculate

SNAPSHOT_SCHEMA = "parking.tariff_snapshot.v1"


def build_snapshot(
    *,
    plan_id: int,
    plan_code: str,
    plan_name: str,
    plan_version: int,
    site_id: int,
    rules: list,
    vehicle_type: str,
    entry_at: datetime,
    calculation_at: datetime,
    duration_minutes: int,
    grace_period_minutes: int,
    daily_max_amount: int | None,
    currency: str,
    result: TariffResult,
) -> dict:
    return {
        "schema": SNAPSHOT_SCHEMA,
        "plan": {
            "id": plan_id,
            "code": plan_code,
            "name": plan_name,
            "version": plan_version,
            "site_id": site_id,
        },
        "rules": [
            {
                "vehicle_type": r.vehicle_type,
                "rule_type": r.rule_type,
                "precedence": r.precedence,
                "config": validate_config(r.rule_type, r.config),
            }
            for r in rules
        ],
        "inputs": {
            "vehicle_type": vehicle_type,
            "entry_at": entry_at.isoformat(),
            "calculation_at": calculation_at.isoformat(),
            "duration_minutes": duration_minutes,
            "grace_period_minutes": grace_period_minutes,
            "daily_max_amount": daily_max_amount,
            "currency": currency,
        },
        "result": {
            "amount": result.amount,
            "currency": result.currency,
            "breakdown": [
                {"label": item.label, "amount": item.amount, "detail": item.detail} for item in result.breakdown
            ],
        },
    }


def reproduce(snapshot: dict, calculation_at: datetime) -> TariffResult:
    """Re-run the engine from a stored snapshot at a given calculation time.
    Deterministic: same (snapshot, calculation_at) -> same amount."""
    rules = [
        RuleView(rule_type=r["rule_type"], config=validate_config(r["rule_type"], r["config"]))
        for r in snapshot["rules"]
    ]
    entry_at = datetime.fromisoformat(snapshot["inputs"]["entry_at"])
    seconds = max(0, (calculation_at - entry_at).total_seconds())
    duration_minutes = math.ceil(seconds / 60)
    result = calculate(
        vehicle_type=snapshot["inputs"]["vehicle_type"],
        duration_minutes=duration_minutes,
        grace_period_minutes=int(snapshot["inputs"]["grace_period_minutes"]),
        daily_max_amount=snapshot["inputs"].get("daily_max_amount"),
        currency=snapshot["inputs"].get("currency") or "IDR",
        rules=rules,
    )
    return result


def to_result(snapshot: dict) -> TariffResult:
    bd = snapshot["result"]["breakdown"]
    return TariffResult(
        amount=int(snapshot["result"]["amount"]),
        currency=snapshot["result"]["currency"],
        breakdown=tuple(BreakdownItem(item["label"], int(item["amount"]), item.get("detail")) for item in bd),
    )
