"""M5: exit quote repository (tenant-scoped)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from parking.domain.errors import ErrorCode, ParkingError
from parking.domain.enums import ExitQuoteStatus
from parking.models import ParkingExitQuote
from parking.repositories.base import ScopedRepository


def make_quote_reference() -> str:
    return f"Q-{secrets.token_hex(5).upper()}"


class ExitQuoteRepository(ScopedRepository):
    def create(
        self,
        *,
        site_id: int,
        session_id: int,
        tariff_version: int | None,
        tariff_snapshot: dict | None,
        entry_at: datetime,
        calculated_at: datetime,
        amount: int,
        currency: str,
        expires_at: datetime,
    ) -> ParkingExitQuote:
        quote = ParkingExitQuote(
            public_reference=make_quote_reference(),
            tenant_id=self.tenant_id,
            site_id=site_id,
            session_id=session_id,
            tariff_version=tariff_version,
            tariff_snapshot=tariff_snapshot,
            entry_at=entry_at,
            calculated_at=calculated_at,
            amount=amount,
            currency=currency,
            expires_at=expires_at,
            status=ExitQuoteStatus.ACTIVE.value,
        )
        self.session.add(quote)
        self.session.flush()
        return quote

    def get(self, quote_id: int) -> ParkingExitQuote:
        quote = self.session.scalar(
            select(ParkingExitQuote).where(
                ParkingExitQuote.id == quote_id, ParkingExitQuote.tenant_id == self.tenant_id
            )
        )
        if quote is None:
            raise ParkingError(ErrorCode.QUOTE_EXPIRED, "exit quote not found", status=404)
        return quote

    def get_by_public_reference(self, public_reference: str) -> ParkingExitQuote:
        quote = self.session.scalar(
            select(ParkingExitQuote).where(
                ParkingExitQuote.public_reference == public_reference,
                ParkingExitQuote.tenant_id == self.tenant_id,
            )
        )
        if quote is None:
            raise ParkingError(ErrorCode.QUOTE_EXPIRED, "exit quote not found", status=404)
        return quote

    def get_active_for_session(self, session_id: int) -> ParkingExitQuote | None:
        return self.session.scalar(
            select(ParkingExitQuote)
            .where(
                ParkingExitQuote.tenant_id == self.tenant_id,
                ParkingExitQuote.session_id == session_id,
                ParkingExitQuote.status == ExitQuoteStatus.ACTIVE.value,
            )
            .order_by(ParkingExitQuote.id.desc())
            .limit(1)
        )

    def set_status(self, quote: ParkingExitQuote, status: str) -> ParkingExitQuote:
        quote.status = status
        self.session.flush()
        return quote
