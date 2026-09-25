# BotConnector Static Model → Provider Routing

Snapshot awal: **2026-09-18**

Tujuan implementasi ini:

1. **Satu model hanya punya satu provider aktif.**
2. Mapping provider bersifat **static/locked**.
3. Harga tepercaya disimpan terpisah di `price-registry.json`.
4. Registry harga boleh diperbarui kapan saja.
5. Perubahan harga **tidak pernah otomatis mengubah provider**.
6. Jika ada provider lain lebih murah, `check-price-drift.mjs` hanya menghasilkan warning `CHEAPER_PROVIDER_DETECTED`.
7. Perpindahan provider harus dilakukan eksplisit dengan mengubah `static-model-routes.json`.

## File

- `config/static-model-routes.json` — source of truth model → provider.
- `config/price-registry.json` — offer provider, eligibility, region, context, cache, tier, promotion, dan metadata sumber.
- `src/model-routing.ts` — resolver route, estimator biaya, drift detector.
- `scripts/validate-registry.mjs` — validasi integritas.
- `scripts/check-price-drift.mjs` — deteksi harga lebih murah tanpa auto-switch.

## Integrasi

Salin folder ini ke repo BotConnector, lalu pastikan TypeScript project mengaktifkan:

```json
{
  "compilerOptions": {
    "resolveJsonModule": true,
    "esModuleInterop": true
  }
}
```

Contoh runtime:

```ts
import { getStaticRoute, estimateCostUsd } from "./src/model-routing";

const route = getStaticRoute("qwen3.8-flash");
// route.provider === "alibaba_global"

const estimated = estimateCostUsd("qwen3.8-flash", 100_000, 5_000, { region: "global" });
```

Adapter provider cukup membaca:

```ts
const route = getStaticRoute(modelId);
providerClient(route.provider).chat({
  model: route.providerModelId,
  messages
});
```

## Update harga

Jangan edit `static-model-routes.json` hanya karena harga berubah.

Update atau tambahkan offer di:

`config/price-registry.json`

Lalu jalankan:

```bash
node scripts/validate-registry.mjs
node scripts/check-price-drift.mjs
```

Jika hasil:

```text
CHEAPER_PROVIDER_DETECTED ... action=REVIEW_ONLY
```

maka lakukan review manual. Tidak ada perpindahan backend otomatis.

## Drift traffic profile

Detector membandingkan biaya untuk `INPUT_TOKENS`, `OUTPUT_TOKENS`, region, context, dan capability yang dinyatakan. Hanya offer yang eligible dan fresh yang dibandingkan.

Bisa diubah:

```bash
INPUT_TOKENS=100000 OUTPUT_TOKENS=25000 REGION=global MIN_SAVINGS_PCT=10 node scripts/check-price-drift.mjs
```

Hasilnya selalu `ACTION=REVIEW_ONLY`; route JSON tidak pernah dimutasi.

## Tier pricing

Alibaba/Qwen tertentu memakai harga berdasarkan panjang input. Tiers disimpan di `offers[].pricing.tiers`, dan harga region di `offers[].pricing.regionalPrices`.

Estimator memilih tier berdasarkan `inputTokens`, bukan hanya harga headline.

## Verified vs seed

`actualProviderPrice` adalah harga provider yang sedang berlaku. `standardReferencePrice` hanya safety/reference rate dan tidak boleh dipakai sebagai actual settlement.

`verified: true` berarti harga tersebut dicek kembali dari sumber resmi pada 2026-09-18.

`verified: false` berarti angka berasal dari snapshot riset perbandingan yang sama tetapi **harus diverifikasi ulang sebelum dijadikan dasar commitment/budget produksi**.

Ini sengaja dibuat fail-visible, bukan menyamarkan angka lama sebagai harga live.
