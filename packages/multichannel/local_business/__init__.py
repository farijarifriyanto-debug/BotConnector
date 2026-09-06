"""BotConnector Local Business Suite — POS retail/restoran, multi-branch, warehouse.

Reuses Central Product/SKU + Inventory Core and Finance Core. No duplicate
product/inventory/journal/finance kernels.
"""

from . import (  # noqa: F401
    acceptance,
    barcode,
    business_reporting,
    core,
    delivery,
    finance,
    file_connector,
    intake,
    inventory,
    low_stock,
    marketplace,
    migrate,
    offline,
    procurement,
    reorder,
    reporting,
    restaurant,
    retail,
    returns,
    scenario,
    telegram_intake,
    telegram_outbound,
    transfer,
)
