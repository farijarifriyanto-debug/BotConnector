"""M6: provider-neutral payment adapter contract.

Adapters are pluggable. The domain never hardcodes a specific PJP. For M6 the
only concrete adapter is the deterministic simulator; real providers (Midtrans,
Xendit, etc.) plug in later without touching domain logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaymentInitiation:
    provider_reference: str
    status: str  # PENDING / SUCCEEDED / FAILED
    payload: dict = field(default_factory=dict)  # e.g. dynamic QR payload


@dataclass(frozen=True)
class CallbackVerification:
    valid: bool
    reason: str = ""
    provider_reference: str | None = None
    amount: int | None = None
    currency: str | None = None
    status: str | None = None


class PaymentAdapter(ABC):
    """Contract every provider adapter must implement."""

    provider_name: str = "abstract"

    @abstractmethod
    def initiate(self, *, amount: int, currency: str, reference: str, metadata: dict | None = None) -> PaymentInitiation:
        """Create a payment intent with the provider (e.g. generate dynamic QR)."""

    @abstractmethod
    def verify_callback_authenticity(self, raw: dict) -> bool:
        """Validate signature/auth of an incoming provider callback."""

    @abstractmethod
    def parse_callback(self, raw: dict) -> CallbackVerification:
        """Parse and verify a callback against expected order/reference/amount."""

    @abstractmethod
    def verify_transaction(self, provider_reference: str) -> CallbackVerification:
        """Server-to-server verification of a provider transaction."""
