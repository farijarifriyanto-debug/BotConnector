"""Typed tariff rule configuration with deterministic validation.

Rule configs are stored as JSONB but parsed/validated through these Pydantic
models so the engine never trusts raw JSON. Validation rejects overlapping
progressive tiers, negative amounts, and invalid boundaries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from parking.domain.errors import ErrorCode, ParkingError

RoundingPolicy = Literal["CEIL", "FLOOR", "ROUND"]


class FlatConfig(BaseModel):
    amount: int = Field(0, ge=0)


class HourlyConfig(BaseModel):
    mode: Literal["FIRST_HOUR_THEN_EACH_HOUR", "PER_STARTED_HOUR"] = "FIRST_HOUR_THEN_EACH_HOUR"
    rounding: RoundingPolicy = "CEIL"
    # PER_STARTED_HOUR
    amount: int = Field(0, ge=0)
    # FIRST_HOUR_THEN_EACH_HOUR
    first_hour_amount: int = Field(0, ge=0)
    additional_hour_amount: int = Field(0, ge=0)
    first_hour_minutes: int = Field(60, ge=1)


class ProgressiveTier(BaseModel):
    lower_minutes: int = Field(0, ge=0)
    upper_minutes: int | None = Field(None)
    amount: int = Field(0, ge=0)
    mode: Literal["FIXED", "PER_STARTED_HOUR"] = "FIXED"


class ProgressiveConfig(BaseModel):
    rounding: RoundingPolicy = "CEIL"
    tiers: list[ProgressiveTier] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_tiers(self) -> "ProgressiveConfig":
        tiers = self.tiers
        if tiers[0].lower_minutes != 0:
            raise ValueError("first progressive tier must start at 0 minutes")
        prev_upper: int | None = None
        for i, tier in enumerate(tiers):
            if tier.upper_minutes is not None and tier.upper_minutes <= tier.lower_minutes:
                raise ValueError(f"tier {i}: upper_minutes must be greater than lower_minutes")
            if tier.upper_minutes is None and i != len(tiers) - 1:
                raise ValueError("only the last progressive tier may be open-ended")
            if i > 0:
                if tier.lower_minutes != prev_upper:
                    raise ValueError(
                        f"progressive tiers must be contiguous without gaps/overlaps (tier {i} starts at "
                        f"{tier.lower_minutes}, expected {prev_upper})"
                    )
            prev_upper = tier.upper_minutes
        return self


class LostTicketConfig(BaseModel):
    amount: int = Field(0, ge=0)


_VALIDATORS = {
    "FLAT": FlatConfig,
    "HOURLY": HourlyConfig,
    "PROGRESSIVE": ProgressiveConfig,
    "LOST_TICKET_FEE": LostTicketConfig,
}


def validate_config(rule_type: str, raw: dict) -> dict:
    """Validate raw rule config and return a canonical (deterministic) dict."""
    validator = _VALIDATORS.get(rule_type)
    if validator is None:
        raise ParkingError(ErrorCode.TARIFF_CONFIGURATION_INVALID, f"unknown tariff rule type: {rule_type}")
    try:
        parsed = validator.model_validate(raw or {})
    except ValidationError as exc:
        issues = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise ParkingError(
            ErrorCode.TARIFF_CONFIGURATION_INVALID,
            f"invalid tariff config for {rule_type}: {'; '.join(issues)}",
            status=400,
            details={"rule_type": rule_type, "issues": issues},
        )
    return parsed.model_dump()
