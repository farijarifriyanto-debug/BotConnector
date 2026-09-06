"""Registry adapter konektor + status provider NYATA.

Memetakan provider -> adapter. Menyediakan status_report gabungan yang jujur:
tidak ada PASS palsu; seluruh provider tanpa kredensial nyata tercatat
BLOCKED_EXTERNAL sampai credential/approval eksternal tersedia.
"""

from __future__ import annotations

from .shopee import factory as _shopee_factory
from .tiktok_tokopedia import factory_tiktok, factory_tokopedia
from .blibli import factory as _blibli_factory
from .lazada import factory as _lazada_factory


_REGISTRY = {}


def register(connector) -> None:
    _REGISTRY[connector.provider.value] = connector


def _build():
    _REGISTRY.clear()
    for factory in (
        _shopee_factory,
        factory_tiktok,
        factory_tokopedia,
        _blibli_factory,
        _lazada_factory,
    ):
        c = factory()
        _REGISTRY[c.provider.value] = c


def get(provider: str):
    if not _REGISTRY:
        _build()
    return _REGISTRY.get(provider)


def all_providers() -> list[str]:
    if not _REGISTRY:
        _build()
    return list(_REGISTRY.keys())


def status_report_all() -> list[dict]:
    if not _REGISTRY:
        _build()
    return [c.status_report() for c in _REGISTRY.values()]


def adapter_map() -> dict[str, object]:
    """Untuk worker outbox: provider -> adapter (yang mungkin memblokir tulis)."""
    if not _REGISTRY:
        _build()
    return dict(_REGISTRY)
