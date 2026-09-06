# BOTCONNECTOR FINANCE CORE — ADENDUM MARKETPLACE

## Kebutuhan integrasi penjualan marketplace terhadap Finance Core
**Tanggal:** 13 Agustus 2026
**Ditujukan untuk:** sesi Finance Core, sebagai lanjutan handoff R9A-B
**Sumber:** sesi Multichannel, hasil discovery read-only terhadap `127.0.0.1:18200`
**Status Finance Core setelah discovery:** TIDAK BERUBAH

---

# 1. TUJUAN DOKUMEN

Sesi Multichannel telah membangun lapisan konektor marketplace yang siap
mengalirkan pesanan Shopee menjadi transaksi akuntansi. Dokumen ini mencatat
apa yang dibutuhkan dari Finance Core agar aliran itu dapat dibukukan dengan
benar.

Dokumen ini **bukan** permintaan mengubah foundation yang sudah dibekukan.
Seluruh kebutuhan di sini berupa penambahan akun dan penyesuaian urutan
pengembangan, bukan modifikasi kontrak yang sudah diterima.

---

# 2. BUKTI DISCOVERY — FINANCE CORE TIDAK TERSENTUH

Discovery dijalankan 13 Agustus 2026 pukul 22:02 WIB.

## Guard

```text
Business Core SHA256 sebelum : a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
Business Core SHA256 sesudah : a6fc9df8147db86c93ecb4733e2a1319e758326d09d35dddf948a674f9efd13a
```

Identik. Tidak ada mutasi.

## Neraca sebelum dan sesudah seluruh pekerjaan

```text
debit 9258000.00   kredit 9258000.00   selisih 0.00   seimbang true
```

Cocok dengan baseline handoff R9A-B pada seluruh angka:

```text
REVENUE=2250225.00   EXPENSES=1235000.00   NET_INCOME=1015225.00
ASSETS=4712000.00    LIABILITIES=2696775.00
POSTED_EQUITY=1000000.00   CURRENT_EARNINGS=1015225.00
OUTPUT_TAX=46775.00  INPUT_TAX=60500.00
```

## Cara interaksi

Seluruh permintaan memakai GET. Modul `rekonsiliasi.py` di sisi multichannel
sengaja hanya menyediakan pembaca yang memaksa `method="GET"`; tidak ada
fungsi tulis yang dapat terpanggil tidak sengaja.

```text
PUBLIC_EXPOSURE=NONE   penyebutan port 18200 di Nginx: 0
NGINX_MUTATION=NONE
MIGRATION_RUN=NONE
PERIOD_CLOSE=NONE
```

---

# 3. KOREKSI RANCANGAN JURNAL

Rancangan awal sesi Multichannel mengakui biaya marketplace pada saat pesanan.
**Itu salah** dan sudah dikoreksi agar sejalan dengan kontrak Finance Core
yang sudah diterima.

## Alasan koreksi

Marketplace memberi perkiraan biaya saat pesanan, tetapi angka sebenarnya baru
diketahui saat settlement. Sering berbeda karena program gratis ongkir,
potongan kampanye, atau penyesuaian yang muncul belakangan.

Mengakui biaya pada saat pesanan berarti membukukan angka yang belum pasti,
lalu harus dikoreksi. Mengakuinya saat settlement lebih akurat dan tidak
memerlukan perubahan apa pun pada kontrak invoice R4A.

## Rancangan yang benar

### Saat pesanan marketplace lunas — persis kontrak R4A

```text
DR Piutang Usaha        1201    (total termasuk PPN)
CR Penjualan            4101    (DPP)
CR PPN Keluaran         2102    (PPN)
```

Tidak ada yang baru. Pelanggan adalah marketplace, bukan pembeli akhir
(lihat bagian 5).

### Saat barang dikirim — persis kontrak R6

```text
DR Harga Pokok Penjualan  5101
CR Persediaan Barang      1301
```

Nilai dihitung Finance Core dengan rata-rata bergerak tertimbang. Multichannel
hanya mengirim jumlah unit; ia tidak pernah menghitung nilai.

### Saat settlement cair — pola R7 penerimaan bank + alokasi

```text
DR Bank                   1102    (neto yang benar-benar diterima)
DR Beban Marketplace      6202    (biaya sebenarnya)
DR/CR Selisih Settlement  6203    (bila tidak cocok dengan perkiraan)
CR Piutang Usaha          1201    (nilai piutang yang dilunasi)
```

### Saat retur pembeli

```text
DR Retur Penjualan        4102    (DPP)
DR PPN Keluaran           2102    (pembalikan PPN)
CR Piutang Usaha          1201
```

ditambah pembalikan persediaan sesuai kontrak R6C:

```text
DR Persediaan Barang      1301
CR Harga Pokok Penjualan  5101
```

---

# 4. TIGA AKUN YANG DIBUTUHKAN

Tidak ada endpoint pembuatan akun; `/api/v1/accounts` menjawab 404. Ketiganya
harus lewat migrasi.

## 4102 Retur Penjualan — PALING MENDESAK

```text
tipe            REVENUE
saldo normal    DEBIT (kontra-pendapatan)
```

Saat ini **tidak ada kontra-pendapatan sama sekali**. Di R6C retur hanya
menyentuh persediaan tanpa membalik pendapatan. Untuk penjualan marketplace di
Indonesia yang tingkat returnya tinggi, omzet akan selalu tampak lebih besar
dari kenyataan, dan selisihnya membesar tiap bulan.

## 6202 Beban Marketplace

```text
tipe            EXPENSE
saldo normal    DEBIT
```

`6201 Biaya Payment Gateway` sudah ada dan bersaldo nol, tetapi bukan hal yang
sama. Menggabungkannya menghilangkan kemampuan menjawab pertanyaan sederhana:
berapa sebenarnya Shopee memotong bulan ini.

## 6203 Selisih Settlement

```text
tipe            EXPENSE
saldo normal    DEBIT
```

`6190 Selisih Persediaan` untuk barang, bukan uang. Tanpa akun ini, potongan
yang tidak sesuai perkiraan akan merusak angka lain diam-diam, dan orang akan
menghabiskan berjam-jam mencari selisih beberapa ribu rupiah saat tutup buku.

## Catatan urutan migrasi

Handoff R9A-B menyatakan `MIGRATION_010_REAPPLY=NO` dan migrasi 011 sudah
persisten. Ketiga akun ini sebaiknya masuk sebagai **migrasi terpisah**, bukan
digabung dengan pekerjaan pajak yang sedang berjalan. Prinsip bagian 45
handoff berlaku: jangan menggabungkan beberapa domain baru dalam satu migrasi.

---

# 5. KEPUTUSAN: SIAPA PELANGGANNYA

## Rekomendasi: satu pelanggan per marketplace

```text
Customer: "Shopee"        -> seluruh penjualan Shopee
Customer: "TikTok Shop"   -> seluruh penjualan TikTok Shop
```

## Alasan

Piutang Anda memang kepada marketplace, bukan kepada pembeli akhir. Uangnya
datang dari Shopee lewat settlement. Anda tidak pernah menagih pembeli akhir,
dan tidak punya hak menagih mereka.

Mencatat pembeli akhir sebagai pelanggan akan membuat AR aging membengkak
ribuan baris yang tidak satu pun dapat ditindaklanjuti, sekaligus memindahkan
data pribadi pembeli ke dalam sistem akuntansi tanpa keperluan yang jelas.

Identitas pembeli tetap tersimpan di sisi multichannel sebagai detail pesanan,
untuk keperluan pengiriman dan layanan pelanggan.

## Konsekuensi yang perlu disepakati

AR aging per marketplace menjadi indikator yang bermakna: berapa lama Shopee
menahan uang Anda. Itu justru informasi yang berguna dan sekarang tidak
terlihat di mana pun.

---

# 6. KEBUTUHAN ITEM PERSEDIAAN

Multichannel memakai SKU internal sebagai jangkar, dan memetakan SKU tiap
marketplace ke sana. Finance Core memakai pengenal itemnya sendiri.

Yang dibutuhkan:

```text
GET  /api/v1/inventory/items        sudah ada, bentuk pengenal belum diperiksa
POST /api/v1/inventory/items/sync   sudah ada, kontrak belum diperiksa
GET  /api/v1/inventory/balances     sudah ada, dipakai untuk rekonsiliasi
```

Pertanyaan terbuka: apakah item punya bidang SKU yang dapat dijadikan
kunci pemetaan, atau hanya `item_id` internal? Jawaban ini menentukan bentuk
tabel pemetaan di sisi multichannel.

---

# 7. REKONSILIASI YANG SUDAH SIAP

Modul `rekonsiliasi.py` sudah terpasang dan hanya membaca. Yang dibandingkan:

## Stok

```text
multichannel.fisik(sku)  vs  /api/v1/inventory/balances
```

Keduanya menyimpan jumlah barang. Penyimpangan bukan kemungkinan, melainkan
kepastian. Pemeriksaan rutin inilah yang menentukan apakah penyimpangan itu
jadi masalah atau tidak.

## Piutang

```text
buku pembantu marketplace  vs  saldo 1201 di trial balance
```

## Periode

```text
periode_terbuka_pada("2026-08")  ->  true
```

Settlement marketplace sering datang terlambat. Bila settlement untuk penjualan
Juli baru cair 5 Agustus sementara Juli sudah ditutup, jurnalnya harus tertahan
di antrean dengan pesan yang jelas, bukan ditolak database di ujung.

## Catatan bentuk jawaban

`/api/v1/periods` memakai `period_year` dan `period_month`, bukan `code` atau
`name`. Tebakan awal meleset dan menyebabkan satu gerbang gagal sebelum
diperbaiki.

---

# 8. PENGAMATAN YANG PERLU DITINDAKLANJUTI

## Akun Bank bersaldo negatif

```text
1102 Bank    debit 575000.00    kredit 985500.00    saldo -410500.00
```

Untuk data uji ini mungkin wajar. Tetapi rekening bank bersaldo negatif di
neraca biasanya menandakan ada pembayaran yang dibukukan tanpa penerimaan
pasangannya.

Sebelum data marketplake sungguhan masuk, sebaiknya ditelusuri — karena
settlement marketplace akan menambah transaksi ke akun yang sama, dan
menelusurinya nanti akan jauh lebih sulit.

## Selisih Persediaan bersaldo kredit

```text
6190 Selisih Persediaan    saldo -100000.00
```

Akun beban dengan saldo kredit berarti keuntungan persediaan bersih. Tampil
sebagai beban negatif di laporan laba rugi. Bukan kesalahan, tetapi perlu
diketahui saat membaca laporan.

---

# 9. KETERGANTUNGAN URUTAN YANG PENTING

Retur marketplace **membutuhkan credit note**, bukan sekadar akun 4102.

Handoff R9A-B bagian 47 sudah menyatakan bahwa `payment.refunded` adalah
pembalikan pembayaran dan AR, bukan alur credit note pajak. Retur marketplace
harus membalik PPN Keluaran juga, dan itu adalah `R9C Credit Note / Tax
Adjustment` di peta jalan Anda.

Artinya:

```text
Penjualan marketplace          -> cukup R4A + akun 6202, 6203
Retur marketplace              -> BUTUH R9C, tidak bisa dipaksakan lebih awal
```

Rekomendasi: aktifkan penjualan marketplace lebih dulu tanpa retur, dan tahan
retur di antrean sampai R9C selesai. Lebih baik retur tertunda beberapa minggu
daripada membukukan pembalikan pajak dengan cara yang salah.

---

# 10. URUTAN YANG DISARANKAN UNTUK SESI FINANCE CORE

```text
1. R9A_C_TAX_INVOICE_WIRING_CANARY          sesuai rencana yang sudah ada
2. Migrasi akun marketplace: 4102, 6202, 6203
3. Master pelanggan marketplace: Shopee
4. Periksa kontrak /api/v1/inventory/items untuk pemetaan SKU
5. R9A_D permanent invoice tax wiring
6. R9B tax internal REST API
7. R9C credit note                          <- pembuka retur marketplace
```

Butir 2 sampai 4 tidak bergantung pada pekerjaan pajak dan dapat dikerjakan
paralel. Butir 1 tetap didahulukan karena pesanan marketplace pertama akan
langsung menjadi Sales Invoice dengan PPN keluaran, dan lebih baik jalur itu
sudah terbukti sebelum ada data sungguhan yang lewat.

---

# 11. YANG SUDAH SIAP DI SISI MULTICHANNEL

```text
/opt/botconnector-multichannel/
```

82 gerbang penerimaan lulus, nol gagal. Rinciannya:

```text
kontrak provider         15 gerbang
stock core               19 gerbang
jembatan posting         10 gerbang
rekonsiliasi             10 gerbang
kontrak aktivasi         14 gerbang
alur hubungkan toko      14 gerbang
```

Pemetaan akun di `/etc/botconnector-akun.json`:

```text
kas                   -> 1102    sudah
piutang_marketplace   -> 1201    sudah
penjualan             -> 4101    sudah
beban_fee_marketplace -> kosong  menunggu 6202
retur_penjualan       -> kosong  menunggu 4102
selisih_settlement    -> kosong  menunggu 6203
```

Ekspor jurnal **menolak berjalan** selama ada akun yang kosong. Ini disengaja:
akun yang belum dipetakan harus menolak, bukan ditebak atau dialihkan ke akun
lain-lain. Kesalahan pemetaan akun baru ketahuan saat tutup buku, dan saat itu
sudah terlambat.

Begitu ketiga akun dibuat, cukup isi kodenya di berkas itu dan ekspor langsung
berfungsi. Tidak ada perubahan kode yang diperlukan.

---

# 12. BENTUK JURNAL YANG AKAN DITERIMA FINANCE CORE

Ringkasan harian per marketplace per toko, bukan per pesanan. Toko dengan 300
pesanan sehari tidak boleh membanjiri akuntansi dengan 300 jurnal.

```json
{
  "kunci": "posting:shopee:t1:20260813",
  "tanggal": "2026-08-13",
  "provider": "shopee",
  "id_toko": "t1",
  "keterangan": "Ringkasan shopee t1 13/08/2026 (37 transaksi)",
  "baris": [
    {"akun_internal": "piutang_marketplace", "kode_akun": "1201",
     "debit": "3250000", "kredit": "0"},
    {"akun_internal": "penjualan", "kode_akun": "4101",
     "debit": "0", "kredit": "3250000"}
  ],
  "total_debit": "3250000",
  "total_kredit": "3250000"
}
```

Kunci ringkasan dapat diulang dan selalu sama untuk hari itu. Bila proses
terputus di tengah dan diulang, hasilnya tetap satu posting.

Detail per pesanan tetap tersimpan di sisi multichannel dan dapat ditelusuri
kapan saja.

---

# 13. PERTANYAAN TERBUKA UNTUK SESI FINANCE CORE

1. Apakah akun 4102, 6202, 6203 disetujui, dan dengan kode itu?
2. Apakah satu pelanggan per marketplace disetujui?
3. Apakah item persediaan punya bidang SKU yang dapat dipetakan?
4. Bagaimana ringkasan harian sebaiknya masuk — lewat
   `POST /api/v1/events/business-core`, lewat sales invoice biasa, atau lewat
   endpoint baru khusus?
5. Apakah saldo negatif pada akun 1102 Bank memang disengaja?

Pertanyaan nomor 4 yang paling menentukan bentuk jembatan. Sampai dijawab,
sisi multichannel hanya menghasilkan berkas JSON netral dan tidak mengirim
apa pun.

---

# 14. INVARIAN YANG DIPERTAHANKAN SESI MULTICHANNEL

```text
FINANCE_CORE_WRITE=NONE
BUSINESS_CORE_MUTATION=NONE
NGINX_MUTATION=NONE
MIGRATION_RUN=NONE
PERIOD_CLOSE=NONE
PUBLIC_EXPOSURE=NONE
```

Seluruh pekerjaan sesi ini berada di `/opt/botconnector-multichannel/` dan
`/etc/botconnector-*.json`. Menghapusnya tidak memengaruhi Finance Core sama
sekali:

```bash
sudo rm -rf /opt/botconnector-multichannel /opt/botconnector_multichannel
```

---

# END OF ADENDUM
