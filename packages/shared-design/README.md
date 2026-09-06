# BOTCONNECTOR DESIGN MASTER

Master reference untuk menerjemahkan export visual BotConnector ke implementasi VPS.

## Evidence boundary

Source yang tersedia saat dokumen ini dibuat:

- Arsip: `/home/botadmin/BOTCONNECTOR-NEW.zip`
- SHA-256: `070a61b40edd34a917999590f111b9dae967f5c638223e841455e6b44d529ae2`
- Isi: 7 PNG, masing-masing 1265 x 900 px
- Tanggal file pada arsip: 1 September 2026
- Tidak ada source Replit, prototype interaction, design tokens, font manifest, atau mobile export.

Dokumen ini membedakan `observed` dari `inferred`. Nilai transaksi, nama pelanggan,
tanggal, KPI, status, dan angka pada PNG adalah demo content dan tidak boleh disalin
ke production.

## Coverage

| Family | Bukti visual | Status |
|---|---:|---|
| Business | 5 PNG | Primary supplied reference |
| Parking Payment | 2 PNG | Primary supplied reference |
| Public Website / Operating Network | 0 PNG | Not present in supplied archive |
| Other product families | 0 PNG | Not present in supplied archive |

Approval status tidak tertanam di PNG. Karena itu istilah `primary supplied reference`
digunakan, bukan klaim bahwa setiap frame sudah approved secara formal.

## Structure

```text
BOTCONNECTOR DESIGN MASTER
├── Public Website
├── Business
│   ├── Dashboard
│   ├── POS + Orders
│   ├── Products + Inventory
│   ├── Restaurant + Kitchen/KDS
│   └── Reports / Integrations / Store Setup
├── Parking Payment
│   ├── Payment Dashboard / Transactions
│   └── QRIS / API / Reconciliation / Settings
└── Shared Design System
```

- `DESIGN-INVENTORY.md`: evidence inventory, coverage, dan missing evidence.
- `SCREEN-CATALOG.md`: catatan detail setiap frame/screen.
- `DESIGN-SYSTEM.md`: shell, navigation, tokens, components, states, responsive.
- `PRODUCT-FLOW.md`: hubungan screen dan state flow yang terlihat.
- `IMPLEMENTATION-HANDOFF.md`: batas implementasi, route mapping, dan acceptance criteria.
- `replit-assets/`: salinan PNG sumber yang diberikan.

## Source of truth rule

Untuk implementasi VPS:

1. Production code, route, API, auth, entitlement, dan database tetap technical source of truth.
2. PNG dalam `replit-assets/` adalah visual source of truth untuk screen yang terlihat.
3. Jika PNG bertentangan dengan production capability, pertahankan capability production dan
   ubah copy/interaction visualnya, bukan mengarang backend baru.
4. Jangan memasukkan demo data dari screenshot ke seed, fixture production, database, atau API.

## Review status

Reference ini siap dipakai sebagai dasar review visual untuk tujuh frame yang tersedia.
Ia belum cukup untuk menyatakan seluruh canvas Replit telah terpetakan karena export public
homepage, variants, mobile layouts, dan screen family lain tidak ada di arsip.
