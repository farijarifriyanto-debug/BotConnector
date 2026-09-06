"""Central Product/SKU Master + Central Inventory Core.

Keberadaan stok hanya di sini. Marketplace hanyalah proyeksi dari
AVAILABLE_TO_PROMISE melalui channel_sku_map + outbox.
"""

from . import service  # noqa
