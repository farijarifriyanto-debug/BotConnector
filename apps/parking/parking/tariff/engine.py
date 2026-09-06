"""Pure, deterministic tariff engine (M3).

`calculate()` is a pure function of its inputs: the same inputs always yield
the same amount — no browser time, no randomness, no global state. All money
values are integers (IDR minor units).

Rule precedence (highest first):
  1. GRACE_PERIOD  -> amount 0 when inside the grace window
  2. base rule (exactly one of FLAT / HOURLY / PROGRESSIVE per vehicle type)
  3. DAILY_MAXIMUM -> cap applied after base calculation
LOST_TICKET_FEE and COMPLIMENTARY are applied by the service layer as explicit
overrides that preserve the original calculated amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import BASE_TARIFF_TYPES
from parking.domain.money import DEFAULT_CURRENCY, validate_amount

_ZERO = Decimal(0)


@dataclass(frozen=True)
class RuleView:
    rule_type: str
    config: dict


@dataclass(frozen=True)
class BreakdownItem:
    label: str
    amount: int
    detail: dict | None = None


@dataclass(frozen=True)
class TariffResult:
    amount: int
    currency: str
    breakdown: tuple[BreakdownItem, ...] = field(default_factory=tuple)


def apply_rounding(hours: Decimal, policy: str) -> int:
    if policy == "FLOOR":
        q = hours.to_integral_value(rounding=ROUND_FLOOR)
    elif policy == "ROUND":
        q = hours.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        q = hours.to_integral_value(rounding=ROUND_CEILING)
    return int(q)


def _compute_flat(cfg: dict, minutes: int) -> tuple[int, tuple[BreakdownItem, ...]]:
    amount = validate_amount(cfg["amount"])
    return amount, (BreakdownItem("flat", amount),)


def _compute_hourly(cfg: dict, minutes: int) -> tuple[int, tuple[BreakdownItem, ...]]:
    policy = cfg["rounding"]
    if cfg["mode"] == "PER_STARTED_HOUR":
        rate = validate_amount(cfg["amount"])
        hours = apply_rounding(Decimal(minutes) / Decimal(60), policy)
        amount = validate_amount(hours * rate)
        return amount, (BreakdownItem("per_started_hour", amount, {"minutes": minutes, "hours": hours}),)

    first_amount = validate_amount(cfg["first_hour_amount"])
    extra_amount = validate_amount(cfg["additional_hour_amount"])
    first_minutes = int(cfg["first_hour_minutes"])
    if minutes <= first_minutes:
        return first_amount, (BreakdownItem("first_hour", first_amount),)
    extra_hours = apply_rounding(Decimal(max(0, minutes - first_minutes)) / Decimal(60), policy)
    extra = validate_amount(extra_hours * extra_amount)
    amount = validate_amount(first_amount + extra)
    return amount, (
        BreakdownItem("first_hour", first_amount, {"minutes": first_minutes}),
        BreakdownItem("additional_hours", extra, {"started_hours": extra_hours}),
    )


def _compute_progressive(cfg: dict, minutes: int) -> tuple[int, tuple[BreakdownItem, ...]]:
    policy = cfg["rounding"]
    total = 0
    parts: list[BreakdownItem] = []
    for tier in cfg["tiers"]:
        lower = int(tier["lower_minutes"])
        if minutes <= lower:
            break
        upper = tier["upper_minutes"]
        band_end = minutes if upper is None else min(minutes, int(upper))
        band = band_end - lower
        if band <= 0:
            continue
        if tier["mode"] == "FIXED":
            total = validate_amount(total + tier["amount"])
            label = f"tier_fixed_{lower}_{upper}"
            parts.append(BreakdownItem(label, tier["amount"], {"band_minutes": band}))
        else:
            hours = apply_rounding(Decimal(band) / Decimal(60), policy)
            part = validate_amount(hours * tier["amount"])
            total = validate_amount(total + part)
            label = f"tier_hourly_{lower}_{upper}"
            parts.append(BreakdownItem(label, part, {"band_minutes": band, "started_hours": hours}))
    return total, tuple(parts)


def _compute_base(rule: RuleView, minutes: int) -> tuple[int, tuple[BreakdownItem, ...]]:
    if rule.rule_type == "FLAT":
        return _compute_flat(rule.config, minutes)
    if rule.rule_type == "HOURLY":
        return _compute_hourly(rule.config, minutes)
    if rule.rule_type == "PROGRESSIVE":
        return _compute_progressive(rule.config, minutes)
    raise ParkingError(ErrorCode.TARIFF_CONFIGURATION_INVALID, f"not a base tariff rule: {rule.rule_type}")


def calculate(
    *,
    vehicle_type: str,
    duration_minutes: int,
    grace_period_minutes: int = 0,
    daily_max_amount: int | None = None,
    currency: str = DEFAULT_CURRENCY,
    rules: list[RuleView],
) -> TariffResult:
    if duration_minutes < 0:
        raise ParkingError(ErrorCode.TARIFF_CONFIGURATION_INVALID, "duration cannot be negative")
    duration_minutes = int(duration_minutes)

    # 1. GRACE PERIOD
    if grace_period_minutes and duration_minutes <= grace_period_minutes:
        return TariffResult(
            amount=0,
            currency=currency,
            breakdown=(
                BreakdownItem(
                    "grace_period",
                    0,
                    {"duration_minutes": duration_minutes, "grace_minutes": grace_period_minutes},
                ),
            ),
        )

    # 2. BASE RULE (exactly one of FLAT/HOURLY/PROGRESSIVE)
    base = next((r for r in rules if r.rule_type in BASE_TARIFF_TYPES), None)
    if base is None:
        raise ParkingError(
            ErrorCode.TARIFF_CONFIGURATION_INVALID,
            f"no base tariff rule for vehicle type {vehicle_type}",
        )
    amount, parts = _compute_base(base, duration_minutes)

    # 3. DAILY MAXIMUM
    items = list(parts)
    if daily_max_amount is not None:
        cap = validate_amount(daily_max_amount)
        if amount > cap:
            items.append(BreakdownItem("daily_maximum", cap, {"capped_from": amount}))
            amount = cap

    return TariffResult(amount=validate_amount(amount), currency=currency, breakdown=tuple(items))
