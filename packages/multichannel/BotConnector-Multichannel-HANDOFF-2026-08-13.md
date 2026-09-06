# BOTCONNECTOR MULTICHANNEL — HANDOFF

## Lapisan konektor marketplace, stok lintas kanal, dan jembatan akuntansi
**Tanggal handoff:** 13 Agustus 2026
**Status:** Seluruh lapisan offline terpasang dan lulus penerimaan
**Jaringan:** MATI — 4 dari 10 syarat aktivasi terpenuhi
**Langkah berikutnya:** menyuntikkan penanda tangan dari foundation beku Shopee

---

# 1. RINGKASAN SATU HALAMAN

Lapisan ini menghubungkan marketplace ke BotConnector, menjaga stok agar tidak
kelebihan jual antarkanal, dan menyiapkan jurnal untuk Finance Core.

Yang sudah berdiri dan terbukti lewat 82 gerbang penerimaan:

- kontrak provider yang membuat Shopee, TikTok Shop, dan Tokopedia dapat dipertukarkan
- Stock Core berbasis catatan gerakan, dengan reservasi dan penyangga per kanal
- buku pembantu marketplace dan jembatan posting ke Finance Core
- pemeriksa rekonsiliasi yang membaca Finance Core tanpa pernah menulis
- kontrak aktivasi produksi dengan gerbang yang dapat diperiksa mesin
- mesin keadaan alur "Hubungkan Toko" lengkap dengan pengaman otorisasi

Yang sengaja belum ada: panggilan jaringan sungguhan, credential, penandatanganan,
dan penyimpanan permanen.

---

# 2. YANG TIDAK BOLEH DISENTUH

## Foundation Shopee — BEKU

```text
/opt/botconnector-shopee-real-provider/
current-offline-shopee-provider-composition
-> releases/offline-shopee-provider-composition-v1-foundation-20260813T143519Z
```

SHA inti:

```text
531b670d047f4ca731daad6ef16b693177757b990a9654f336682d511f969056
```

Terbukti tidak berubah selama seluruh pekerjaan ini.

## Business Core — BEKU

```text
/opt/botconnector-business-core/releases/business-core-v1-foundation-20260813T102138Z/app.py
a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
```

Diverifikasi sebagai pre-guard dan post-guard saat discovery Finance Core.
Nilai sebelum dan sesudah identik.

## Finance Core — TIDAK TERSENTUH

```text
127.0.0.1:18200   internal, tidak terpapar Nginx
```

Seluruh interaksi memakai GET. Neraca sebelum dan sesudah tetap:

```text
debit 9258000.00   kredit 9258000.00   selisih 0.00   seimbang true
```

---

# 3. LETAK BERKAS

```text
/opt/botconnector-multichannel/          folder utama
/opt/botconnector_multichannel           symlink agar dapat diimpor sebagai paket

  VERSION.json
  core/
    models.py         bentuk data baku lintas marketplace
    safety.py         sakelar keselamatan lapisan konektor
    contract.py       kontrak yang wajib dipenuhi tiap provider
    registry.py       daftar provider dan matriks kemampuan
    stock.py          Stock Core
    finance.py        buku pembantu marketplace
    posting.py        jembatan ke sistem akuntansi
    rekonsiliasi.py   pembaca Finance Core, hanya GET
  providers/
    shopee.py         offline_foundation, kemampuan kosong
    tiktok_shop.py    belum_dibangun
    tokopedia.py      belum_dibangun
  activation/
    kontrak.py        gerbang aktivasi produksi
    kredensial.py     batas credential
    transport.py      transport berpagar, tanpa pustaka jaringan
    audit.py          jejak audit yang menyamarkan rahasia
    koneksi.py        mesin keadaan "Hubungkan Toko"
  tests/
    acceptance.py                15 gerbang
    acceptance_core.py           19 gerbang
    acceptance_posting.py        10 gerbang
    acceptance_rekonsiliasi.py   10 gerbang
    acceptance_aktivasi.py       14 gerbang
    acceptance_koneksi.py        14 gerbang
```

## Berkas pengaturan di luar folder rilis

```text
/etc/botconnector-multichannel.json         sakelar keselamatan konektor
/etc/botconnector-akun.json                 pemetaan akun ke Finance Core
/etc/botconnector-shopee-activation.json    kontrak aktivasi produksi
/etc/botconnector-shopee-credential.json    BELUM ADA, wajib izin 0600
/var/log/botconnector-shopee-activation.jsonl   jejak audit
```

Semuanya di luar folder rilis, sehingga tidak hilang saat rilis diperbarui.

---

# 4. MENJALANKAN SELURUH GERBANG

```bash
cd /opt
for t in acceptance acceptance_core acceptance_posting \
         acceptance_rekonsiliasi acceptance_aktivasi acceptance_koneksi; do
  echo -n "$t: "
  sudo python3 /opt/botconnector_multichannel/tests/$t.py | grep "Lulus:"
done
```

Hasil yang diterima pada 13 Agustus 2026:

```text
acceptance:                Lulus: 15   Gagal: 0
acceptance_core:           Lulus: 19   Gagal: 0
acceptance_posting:        Lulus: 10   Gagal: 0
acceptance_rekonsiliasi:   Lulus: 10   Gagal: 0   Lewat: 0
acceptance_aktivasi:       Lulus: 14   Gagal: 0
acceptance_koneksi:        Lulus: 14   Gagal: 0
                           TOTAL 82 gerbang
```

Angka ini adalah baseline. Bila menurun tanpa perubahan yang disengaja,
ada yang rusak.

---

# 5. PEMBAGIAN KEBENARAN

Ini keputusan arsitektur terpenting di seluruh lapisan.

```text
Finance Core   -> nilai persediaan, HPP, piutang, kas, pajak, buku besar
Multichannel   -> ketersediaan: reservasi, penyangga, target sinkron per kanal
```

Alasannya: Finance Core sudah punya persediaan rata-rata bergerak tertimbang
dan buku besar dengan bagan akun lengkap. Membuat buku besar kedua akan
membuat angka menyimpang dalam hitungan minggu tanpa ada yang bisa memastikan
mana yang benar.

Finance Core tidak punya konsep reservasi maupun kanal penjualan, dan memang
tidak seharusnya punya. Itulah tugas lapisan ini.

## Tiga titik temu

```text
barang keluar     -> multichannel catat KELUAR, Finance Core hitung HPP
pesanan lunas     -> Sales Invoice: DR AR / CR Penjualan / CR PPN Keluaran
settlement cair   -> penerimaan bank + alokasi pembayaran ke AR
```

## Catatan penamaan yang belum diperbaiki

Kelas `BukuBesar` di `core/finance.py` salah nama. Setelah discovery jelas ia
adalah **buku pembantu marketplace**, bukan buku besar. Fungsinya benar,
namanya menyesatkan. Ganti nama sebelum ada yang salah mengira ada dua buku besar.

---

# 6. STOCK CORE

## Kaidah

Stok adalah catatan gerakan yang hanya bisa ditambah, bukan angka yang ditimpa.
Setiap angka dapat dijelaskan asal-usulnya lewat `jelaskan(sku)`.

Jenis gerakan: `MASUK`, `KELUAR`, `RESERVASI`, `LEPAS`, `RETUR`, `PENYESUAIAN`.
Hanya `PENYESUAIAN` yang boleh bernilai negatif.

## Tiga angka yang berbeda

```text
fisik      = MASUK + RETUR + PENYESUAIAN - KELUAR
reservasi  = RESERVASI - LEPAS - KELUAR
tersedia   = fisik - reservasi - penyangga_umum - penyangga_kanal
```

Hanya `tersedia` yang boleh dikirim ke marketplace.

## Yang dijaga gerbang

- pesanan mengurangi tersedia, bukan fisik
- pengiriman menutup reservasi
- kelebihan jual antarkanal ditolak dengan `StokTidakCukup`
- penarikan pesanan berulang tidak menghitung dua kali
- pembatalan mengembalikan ketersediaan
- penyangga menahan unit terakhir

## Bug yang sudah diperbaiki

`tersedia()` sempat mengurangi penyangga dua kali ketika provider kosong,
karena kunci penyangga umum dan penyangga kanal menunjuk baris yang sama.
Akibatnya stok tersedia lebih kecil dari kenyataan. Sudah diperbaiki dan
dijaga gerbang "penyangga menahan unit terakhir".

---

# 7. BUKU PEMBANTU MARKETPLACE

## Aturan jurnal

```text
Pesanan lunas
  DR Piutang Marketplace   (total - fee)
  DR Beban Fee Marketplace (fee)
  CR Penjualan             (total)

Settlement cair
  DR Kas                   (neto)
  DR/CR Selisih Settlement (bila potongan tak sesuai perkiraan)
  CR Piutang Marketplace   (piutang yang diharapkan)

Retur
  DR Retur Penjualan       (total)
  CR Piutang Marketplace   (total - fee)
  CR Beban Fee Marketplace (fee)
```

Kaidah utama: **pesanan bukan kas**. Yang lahir dari pesanan adalah piutang ke
marketplace. Kas baru muncul saat settlement.

## Yang dijaga gerbang

- pesanan tidak menambah saldo kas
- neraca percobaan selalu seimbang
- jurnal tidak seimbang ditolak saat pembuatan
- nilai `float` ditolak, wajib `Decimal`
- pesanan ganda tidak dibukukan dua kali
- potongan tak terduga masuk akun selisih, bukan merusak angka lain

## Bug yang sudah diperbaiki

`SELISIH_SETTLEMENT` tidak terdaftar sebagai akun bersaldo normal debit,
sehingga potongan berlebih tercatat bertanda terbalik. Sudah diperbaiki.

---

# 8. JEMBATAN POSTING

Sistem akuntansi menerima **ringkasan harian per marketplace per toko**,
bukan jurnal per pesanan. Toko dengan 300 pesanan sehari tidak boleh
membanjiri akuntansi dengan 300 jurnal.

Kunci ringkasan dapat diulang dan tetap sama:

```text
posting:shopee:t1:20260813
```

## Yang dijaga gerbang

- lima pesanan menjadi satu ringkasan, nilai tidak berubah
- hari berbeda dan marketplace berbeda tidak digabung
- ringkasan yang sudah terkirim tidak bisa dikirim ulang
- posting gagal tetap masuk antrean, tidak hilang
- **akun yang belum dipetakan MENOLAK diekspor**, bukan ditebak

Yang terakhir disengaja keras. Kesalahan pemetaan akun baru ketahuan saat
tutup buku, dan saat itu sudah terlambat.

---

# 9. HASIL DISCOVERY FINANCE CORE

Dijalankan 13 Agustus 2026, seluruhnya GET, dengan pre-guard dan post-guard.

## Permukaan API

48 endpoint. Yang relevan untuk marketplace:

```text
POST /api/v1/sales/invoices              POST /api/v1/sales/invoices/{id}/issue
POST /api/v1/inventory/sales-invoices    POST /api/v1/inventory/sales-invoices/{id}/issue
GET  /api/v1/inventory/balances          GET  /api/v1/inventory/items
GET  /api/v1/inventory/movements         POST /api/v1/inventory/items/sync
GET,POST /api/v1/customers               GET,POST /api/v1/bank/transactions
POST /api/v1/payments/{id}/allocate      GET  /api/v1/payments/unallocated
GET  /api/v1/periods                     GET  /api/v1/reports/trial-balance
POST /api/v1/events/business-core
```

## Bagan akun yang sudah ada

```text
1101 Kas                        1102 Bank
1103 Payment Clearing           1201 Piutang Usaha
1301 Persediaan Barang          2101 Utang Usaha
2102 PPN Keluaran               2109 Penerimaan Belum Dialokasikan
2201 PPN Masukan                3101 Modal
3201 Laba Ditahan               4101 Penjualan
4201 Pendapatan Lain-lain       5101 Harga Pokok Penjualan
6101 Beban Operasional          6190 Selisih Persediaan
6201 Biaya Payment Gateway
```

## Periode fiskal

```text
2026-08   OPEN   2026-08-01 sampai 2026-08-31   closed_at null
```

Jawaban `/api/v1/periods` memakai `period_year` dan `period_month`,
bukan `code` atau `name`.

## Pengamatan yang perlu ditindaklanjuti

Akun `1102 Bank` bersaldo **negatif 410.500**. Kredit 985.500 melebihi debit
575.000. Untuk data uji mungkin wajar, tetapi rekening bank bersaldo negatif
biasanya menandakan ada pembayaran yang dibukukan tanpa penerimaan pasangannya.

---

# 10. PEMETAAN AKUN

Berkas: `/etc/botconnector-akun.json`

## Sudah dipetakan

```text
kas                   -> 1102 Bank
piutang_marketplace   -> 1201 Piutang Usaha
penjualan             -> 4101 Penjualan
```

## MENUNGGU KEPUTUSAN — ekspor menolak jalan sampai diisi

```text
beban_fee_marketplace -> usul 6202 Beban Marketplace
retur_penjualan       -> usul 4102 Retur Penjualan
selisih_settlement    -> usul 6203 Selisih Settlement
```

Alasan tiap usulan:

**6202** — `6201 Biaya Payment Gateway` bukan hal yang sama. Menggabungkannya
menghilangkan kemampuan melihat berapa sebenarnya marketplace memotong.

**4102** — belum ada kontra-pendapatan sama sekali. Di R6C retur hanya
menyentuh persediaan tanpa membalik pendapatan. Untuk marketplace dengan
tingkat retur tinggi, omzet akan selalu tampak lebih besar dari kenyataan.
**Ini yang paling mendesak dari ketiganya.**

**6203** — `6190 Selisih Persediaan` untuk barang, bukan uang. Potongan
marketplace hampir tidak pernah persis sama dengan perkiraan.

Tidak ada endpoint pembuatan akun; `/api/v1/accounts` menjawab 404.
Ketiganya harus lewat migrasi di sesi Finance Core.

---

# 11. KEPUTUSAN YANG BELUM DIAMBIL

## Pelanggan marketplace

Satu pelanggan bernama "Shopee", atau pembeli akhir satu per satu?

Rekomendasi: **satu pelanggan per marketplace**. Piutang Anda memang ke
marketplace, dan uangnya datang dari marketplace. AR aging dengan ribuan
pembeli akhir yang tidak pernah ditagih hanya mengaburkan laporan. Identitas
pembeli disimpan di sisi multichannel sebagai detail pesanan.

Keputusan ini memengaruhi struktur pelanggan di Finance Core, jadi harus
disepakati sebelum pesanan pertama masuk.

## Item persediaan

Bagaimana SKU internal multichannel dipetakan ke item Finance Core?
`/api/v1/inventory/items` tersedia dan `POST /api/v1/inventory/items/sync` ada,
tetapi bentuk pengenalnya belum diperiksa.

---

# 12. KONTRAK AKTIVASI PRODUKSI

Berkas: `/etc/botconnector-shopee-activation.json`

## Keadaan sekarang: 4 dari 10 syarat lolos

```text
lolos  kill switch tidak aktif
BELUM  aktivasi produksi disetujui
BELUM  gerbang jaringan dinyalakan
BELUM  credential dinyalakan
BELUM  berkas credential ada
BELUM  izin credential 0600 atau lebih ketat
lolos  daftar host tidak kosong
lolos  daftar endpoint baca tidak kosong
BELUM  toko kanari ditentukan
lolos  berkas audit dapat ditulis
```

Menyalakan satu gerbang tidak cukup. `boleh_jaringan()` menyebutkan syarat mana
yang belum lolos, bukan sekadar menolak.

## Daftar izin

Host: `partner.shopeemobile.com`

Endpoint baca, enam, seluruhnya `get_`:

```text
/api/v2/shop/get_shop_info        /api/v2/shop/get_profile
/api/v2/order/get_order_list      /api/v2/order/get_order_detail
/api/v2/product/get_item_list     /api/v2/product/get_item_base_info
```

Endpoint tulis: **kosong**, dan tetap ditolak selama
`READ_ONLY_ACCEPTANCE_PASSED` belum benar.

## Yang dibuktikan gerbang

- pengirim jaringan tidak pernah terpanggil selama gerbang tertutup
- `transport.py` tidak mengimpor `requests`, `httpx`, `urllib.request`,
  `http.client`, maupun `socket` — kemampuan jaringan memang tidak ada,
  bukan sekadar dimatikan
- host di luar daftar ditolak
- endpoint di luar daftar ditolak
- operasi tulis ditolak sebelum read-only lulus
- hanya toko kanari yang boleh
- kill switch menutup segalanya
- setiap penolakan tercatat di audit

---

# 13. BATAS CREDENTIAL

Berkas credential belum ada. Saat dibuat nanti, wajib:

```text
/etc/botconnector-shopee-credential.json
izin 0600 atau lebih ketat, milik root
tidak berada di dalam repositori git
berisi partner_id dan partner_key
```

`muat_kredensial()` menolak bila salah satu syarat tidak terpenuhi.

## Rahasia tidak bisa bocor lewat cetakan

`Rahasia.__repr__` menghasilkan `<Rahasia a1b2c3 panjang=48>`. Berlaku juga
untuk `str`, f-string, dan `format`. Ini menutup jalur kebocoran paling umum:
seseorang menulis `print(kredensial)` saat menelusuri masalah, dan kuncinya
masuk ke log selamanya.

Audit menyamarkan bidang yang cocok dengan pola `partner_key`, `access_token`,
`refresh_token`, `sign`, `signature`, `secret`, `password`, `authorization`.

---

# 14. ALUR "HUBUNGKAN TOKO"

```text
BELUM_TERHUBUNG
      |  pengguna menekan "Hubungkan Shopee"
      v
MENUNGGU_OTORISASI     state acak 32 byte, sekali pakai, kedaluwarsa 10 menit
      |  marketplace mengarahkan kembali dengan code + shop_id
      v
callback diperiksa     state cocok, belum dipakai, belum kedaluwarsa,
      |                toko belum dimiliki tenant lain
      v
tukar code jadi token  lewat transport berpagar
      v
TERHUBUNG              token tersimpan, toko terikat ke tenant
      |
      +--> KEDALUWARSA bila token lewat masa berlaku
      +--> TERPUTUS bila pengguna memutus sambungan
```

## Yang dijaga gerbang

- state acak, berbeda tiap permintaan, panjang minimal 32
- state asing dan kedaluwarsa ditolak
- state hanya bisa dipakai sekali
- callback berulang mengembalikan sambungan yang sama, tidak menggandakan
- satu toko tidak bisa dimiliki dua tenant
- token tidak muncul saat sambungan dicetak
- memutus sambungan menghapus token
- callback tertahan selama gerbang tertutup dan tidak meninggalkan
  sambungan setengah jadi

## Yang sengaja tidak ditulis ulang

**Penandatanganan.** `url_otorisasi()` menolak jalan tanpa `penanda_tangan`
yang disuntikkan dari foundation beku. Menulis ulang HMAC di sini berarti ada
dua implementasi, dan suatu saat keduanya akan berbeda.

**Penukar token.** Juga disuntikkan. Yang ada sekarang hanya mesin keadaannya.

## Halaman Integrasi

`halaman_integrasi()` menghasilkan kartu sesuai dokumen ide utama:

```text
shopee        Terhubung           Pengaturan
tiktok_shop   Belum terhubung     Hubungkan Tiktok_Shop
tokopedia     Belum terhubung     Hubungkan Tokopedia
```

---

# 15. KEKURANGAN TERBESAR: BELUM ADA PENYIMPANAN

Seluruh keadaan masih di memori:

```text
GudangSambungan   sambungan dan permintaan otorisasi
BukuStok          catatan gerakan stok
BukuBesar         jurnal buku pembantu
BukuPosting       catatan ringkasan yang sudah terkirim
```

Semuanya hilang saat proses berhenti.

**Ini harus diselesaikan sebelum kanari otorisasi.** Kalau tidak, sambungan
yang berhasil dibuat akan lenyap saat layanan dimuat ulang, dan pengguna harus
menghubungkan tokonya berulang kali.

Basis data sudah tersedia: `botconnector-core-postgres`. Pola yang sudah
terbukti aman untuk menjangkaunya dari runtime Python di host ada di
handoff Finance Core bagian 4 — jangan mengandalkan nama kontainer,
resolusikan IP-nya secara dinamis.

---

# 16. URUTAN PENGEMBANGAN BERIKUTNYA

```text
1. Penyimpanan permanen untuk sambungan dan stok        <- WAJIB sebelum kanari
2. Suntikkan penanda tangan dari foundation beku        <- masih offline
3. Kontrak OAuth lengkap dan endpoint callback
4. Kandidat transport nyata, jaringan tetap default OFF
5. Kanari otorisasi satu toko
6. Pertukaran token kanari
7. Panggilan read-only pertama: identitas toko
8. Penerimaan read-only shop binding
9. API pesanan read-only
10. Pemetaan ke Business Core
11. Pemetaan ke Finance Core
12. Baru pertimbangkan operasi tulis, terpisah
```

Paralel di jalur lain, tidak bersinggungan:

```text
Finance Core   R9A_C_TAX_INVOICE_WIRING_CANARY
               lalu tiga akun baru: 6202, 4102, 6203
```

Bila harus memilih satu lebih dulu, dahulukan R9A-C. Saat pesanan Shopee
pertama masuk nanti, ia langsung menjadi Sales Invoice dengan PPN keluaran,
dan lebih baik jalur itu sudah terbukti sebelum ada data sungguhan yang lewat.

---

# 17. POLA KEGAGALAN YANG SUDAH DIPELAJARI

Enam kesalahan nyata yang terjadi selama sesi ini. Semuanya berulang bila
tidak dicatat.

## Glob shell tidak mengikuti izin sudo

```bash
sudo grep -c "pola" "$DIR"/*.py      # gagal diam-diam bila $DIR tidak
                                      # dapat dibaca pengguna biasa
```

Perluasan glob terjadi sebagai pengguna biasa, sebelum `sudo` berlaku.
Hasilnya nol tanpa pesan galat. Ini menyesatkan dua kali dalam satu hari.

Pakai:

```bash
sudo find "$DIR" -maxdepth 1 -name '*.py'
```

## String Python yang terpecah antarbaris

```python
PATH = Path(
    "/opt/document-assistant/handwriting-renderer/"
    "venv/bin/python"
)
```

Mencari teks `handwriting-renderer/venv/bin/python` tidak akan menemukannya.
Satukan dulu dengan `re.sub(r'"\s*\n\s*"', '', teks)` sebelum memeriksa.

## `try:` tanpa `except`

Menyebabkan `SyntaxError` yang pesannya menunjuk baris jauh di bawah lokasi
sebenarnya. Selalu jalankan `compile()` terhadap blok Python sebelum mengirim
skrip ke server.

## Kunci ganda pada penyangga

`penyangga(sku)` dan `penyangga(sku, provider)` menunjuk baris yang sama
ketika provider kosong, sehingga terpotong dua kali. Uji dengan nilai yang
diketahui, jangan hanya memeriksa tidak ada galat.

## Tanda saldo akun

Akun yang tidak terdaftar di `NORMAL_DEBIT` menghasilkan saldo bertanda
terbalik. Selalu uji dengan angka yang sudah diketahui hasilnya.

## Menebak bentuk jawaban API

`/api/v1/periods` memakai `period_year` dan `period_month`. Tebakan `code`,
`period`, dan `name` semuanya meleset, dan uji gagal dengan `['None']`.
Lakukan discovery lebih dulu, jangan menebak nama bidang.

---

# 18. ROLLBACK

## Hapus seluruh lapisan

```bash
sudo rm -rf /opt/botconnector-multichannel /opt/botconnector_multichannel
```

Tidak ada layanan yang bergantung padanya, tidak ada systemd unit, tidak ada
rute Nginx. Menghapusnya tidak memengaruhi apa pun yang sedang berjalan.

## Kembalikan pengaturan

Berkas pengaturan di `/etc/` dapat dihapus terpisah. Cadangan bertanggal ada
untuk `/etc/botconnector-akun.json`.

## Cadangan berkas kode

```text
/root/rekonsiliasi.py.bak-2026-08-13-221535
```

---

# 19. INVARIAN YANG WAJIB DIPERTAHANKAN

```text
FOUNDATION_SHOPEE_MUTATION=NONE
BUSINESS_CORE_MUTATION=NONE
FINANCE_CORE_WRITE=NONE
NGINX_MUTATION=NONE
NETWORK_ENABLED=NO
REAL_CREDENTIAL_ENABLED=NO
WRITE_OPERATIONS_APPROVED=NO
PRODUCTION_AUGUST=OPEN
```

Seluruh interaksi dengan Finance Core memakai GET. Modul `rekonsiliasi.py`
sengaja hanya menyediakan `_ambil()` yang memaksa `method="GET"`; tidak ada
fungsi tulis yang bisa dipanggil tidak sengaja.

---

# 20. KEADAAN AKHIR

```text
BOTCONNECTOR MULTICHANNEL

KONTRAK PROVIDER:        TERPASANG, 3 provider terdaftar
STOCK CORE:              TERPASANG, 19 gerbang
BUKU PEMBANTU:           TERPASANG
JEMBATAN POSTING:        TERPASANG, 3 dari 6 akun dipetakan
REKONSILIASI:            TERPASANG, hanya baca
KONTRAK AKTIVASI:        TERPASANG, 4 dari 10 syarat
ALUR HUBUNGKAN TOKO:     TERPASANG, 14 gerbang

TOTAL GERBANG:           82 LULUS, 0 GAGAL

PENYIMPANAN PERMANEN:    BELUM ADA
PENANDA TANGAN:          BELUM DISUNTIKKAN
CREDENTIAL:              BELUM ADA
JARINGAN:                MATI
PANGGILAN API NYATA:     NIHIL
TOKO TERSAMBUNG:         NIHIL

FOUNDATION BEKU:         UTUH
BUSINESS CORE:           UTUH
FINANCE CORE:            9258000.00 SEIMBANG, TIDAK TERSENTUH
```

---

# 21. YANG PERLU DIPUTUSKAN MANUSIA

Tiga hal, dan tidak satu pun dapat diputuskan oleh kode.

1. **Tiga akun baru** — 6202, 4102, 6203. Yang paling mendesak 4102 Retur
   Penjualan, karena tanpanya omzet akan selalu tampak lebih besar dari
   kenyataan.

2. **Model pelanggan marketplace** — satu pelanggan per marketplace, atau
   pembeli akhir satu per satu.

3. **Toko kanari** — satu toko Shopee sungguhan yang akan dipakai untuk
   percobaan pertama. Sampai ini ditentukan, gerbang aktivasi tidak akan
   pernah lengkap.

---

# END OF HANDOFF
