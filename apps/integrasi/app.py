"""Server Integrasi — multi-provider + pusat inventory.

Endpoint:
  GET /integrasi/       halaman HTML kartu provider + stok pusat
  GET /api/public/state JSON keadaan multi-provider
  GET /api/public/inventory JSON stok pusat

Read-only. Tidak memanggil keluar. Tidak membuka token.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import multichannel as _multichannel
sys.modules.setdefault("botconnector_multichannel", _multichannel)

from botconnector_multichannel.persistence import repo  # noqa
from botconnector_multichannel.workflow import shop_binding  # noqa
from botconnector_multichannel.connector import registry as conn_registry  # noqa

APP = FastAPI(title="BotConnector Integrasi", version="1.0.0")
APP.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])

_TENANT = "default-tenant"
_PROVIDERS = [
    ("shopee", "Shopee"),
    ("tokopedia", "Tokopedia"),
    ("tiktok_shop", "TikTok Shop"),
    ("blibli", "Blibli"),
    ("lazada", "Lazada"),
]


def _kartu(tenant_id: str, provider: str) -> dict:
    k = shop_binding.keadaan(tenant_id, provider)
    c = conn_registry.get(provider)
    if c:
        k["readiness"] = c.status_report().get("readiness", "unknown")
        k["blocker"] = c.status_report().get("blocker", "")
    else:
        k["readiness"] = "unknown"
        k["blocker"] = ""
    return k


@APP.get("/api/public/state")
def state():
    """Public-safe state: public catalog + public status only. No internal
    blockers, no pilot operational counts."""
    return {
        "ok": True,
        "integrations": [
            {"provider": prov, "name": name, "status": "SEGERA_HADIR",
             "description": desc}
            for prov, name, desc in _PUBLIC_CATALOG
        ],
    }


@APP.get("/api/public/inventory")
def inventory():
    """Public-safe: no pilot inventory rows exposed publicly."""
    return {"ok": True, "skus": [], "channel_mappings": []}


@APP.get("/integrasi/", response_class=HTMLResponse)
@APP.get("/integrasi", response_class=HTMLResponse)
def halaman():
    return _html(_TENANT)


@APP.get("/health")
def health():
    return {"ok": True, "service": "botconnector-integrasi"}


def _html(tenant_id: str) -> str:
    """Public-safe marketing integration catalog. No internal labels, no pilot
    operational counts, no fake connection buttons. Status only public-safe."""
    cards = []
    for prov, name, desc in _PUBLIC_CATALOG:
        status = "SEGERA_HADIR"  # no real external connection yet
        badge = '<span class="badge soon">Segera Hadir</span>'
        cards.append(
            f'<div class="band"><div class="label">Integrasi</div>'
            f'<h2>{name}</h2>'
            f'<p>{desc}</p>'
            f'<p>{badge}</p>'
            f'</div>'
        )
    cards_html = "\n".join(cards)
    return _TEMPLATE.replace("{{CARDS}}", cards_html)


_PUBLIC_CATALOG = [
    ("shopee", "Shopee", "Konektor marketplace dengan proyeksi stok dari inventori pusat."),
    ("tokopedia", "Tokopedia", "Konektor marketplace dengan proyeksi stok dari inventori pusat."),
    ("tiktok_shop", "TikTok Shop", "Konektor marketplace dengan proyeksi stok dari inventori pusat."),
    ("blibli", "Blibli", "Konektor marketplace dengan proyeksi stok dari inventori pusat."),
    ("lazada", "Lazada", "Konektor marketplace dengan proyeksi stok dari inventori pusat."),
    ("gofood", "GoFood", "Integrasi food delivery — menu, order, KDS, dan settlement."),
    ("grabfood", "GrabFood", "Integrasi food delivery — order, mark ready, dan settlement."),
    ("shopeefood", "ShopeeFood", "Integrasi food delivery — menu sync dan order."),
]


_TEMPLATE = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Integrasi — BotConnector</title>
<link rel="stylesheet" href="/integrasi-assets-v1/site.css">
</head><body>
<header class="top"><div class="wrap top-in">
<a class="brand" href="/"><span class="plug">BC</span> BotConnector</a>
<nav><a href="/bisnis/">Business Suite</a><a href="/konektor/">Konektor</a>
<a href="/integrasi/">Integrasi</a><a href="/resep/">Template</a></nav>
</div></header>
<main>
<section class="hero"><div class="wrap">
<h1>Integrasi BotConnector</h1>
<p>Hubungkan operasional bisnis, POS, restoran, marketplace, dan food delivery dari satu tempat.</p>
</div></section>
<section class="section"><div class="wrap grid">
{{CARDS}}
</div></section>
<section class="section"><div class="wrap">
<p class="dim">Status integrasi ditampilkan berdasarkan kemampuan yang tersedia saat ini.
Integrasi yang membutuhkan kredensial atau persetujuan pihak ketiga ditandai
"Segera Hadir" sampai koneksi eksternal benar-benar aktif.</p>
</div></section>
</main>
<footer><div class="wrap footer-grid">
<div><a class="brand" href="/"><span class="plug">BC</span> BotConnector</a>
<div class="footer-copy">Hubungkan sistem. Jalankan bisnis dari satu tempat.</div></div>
<div class="footer-links"><a href="/bisnis/">Business Suite</a>
<a href="/konektor/">Konektor</a><a href="/integrasi/">Integrasi</a>
<a href="/resep/">Template</a></div>
</div></footer>
</body></html>
"""
