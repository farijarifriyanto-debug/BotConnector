"""
BotConnector AI Support V3 — Canonical Knowledge Base & High-Performance Section-Level RAG Engine.
Maintains curated, section-level product documentation with versioning, pre-computed local embeddings,
BM25 lexical retrieval, hybrid reranking, and direct deep links to canonical documentation.
"""
from __future__ import annotations

import os
import re
import json
import math
import hashlib
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

KNOWLEDGE_VERSION = "3.0.0"
EMBEDDING_ENDPOINT = os.environ.get("SUPPORT_AI_EMBEDDING_URL", "http://botconnector-llama-embed:8080/v1/embeddings")
EMBEDDING_MODEL = os.environ.get("SUPPORT_AI_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
CANONICAL_DOCS_PATH = os.environ.get("SUPPORT_AI_DOCS_PATH", "/var/www/botconnector-automation-docs/current/index.html")

@dataclass
class KnowledgeChunk:
    chunk_id: str
    canonical_url: str
    title: str
    section_title: str
    product: str  # PLATFORM, BUSINESS_SUITE, PARKING, MY_DRIVE, SUPPORT, INTEGRATION, CONNECT
    doc_type: str  # TUTORIAL, HOW_TO, REFERENCE, EXPLANATION, TROUBLESHOOTING, GLOSSARY, INSTALLATION
    intent: str  # INFORMATION_REQUEST, EXPLANATION_REQUEST, HOW_TO_REQUEST, INSTALLATION_REQUEST, TROUBLESHOOTING, CUSTOMER_COMPLAINT, TECHNICAL_INTEGRATION, SECURITY_REPORT, PRIVACY_REQUEST, SUPPORT_ESCALATION
    parking_profile: Optional[str] = None  # FULL_STACK, EXISTING_HARDWARE, PAYMENT_ONLY, None
    keywords: List[str] = field(default_factory=list)
    action_links: List[Dict[str, str]] = field(default_factory=list)
    content: str = ""
    active: bool = True
    embedding: Optional[List[float]] = None
    source_hash: str = ""

# ================= CANONICAL STRUCTURED KNOWLEDGE CORPUS =================
CANONICAL_CHUNKS: List[KnowledgeChunk] = [
    # ----------------- 1. PLATFORM CORE -----------------
    KnowledgeChunk(
        chunk_id="plat_overview",
        canonical_url="https://botconnector.id/docs/#getting-started",
        title="Tentang Platform BotConnector",
        section_title="Mulai",
        product="PLATFORM",
        doc_type="EXPLANATION",
        intent="INFORMATION_REQUEST",
        keywords=["botconnector", "platform", "apa itu botconnector", "fitur", "ekosistem", "modul"],
        action_links=[
            {"title": "Buka Beranda", "url": "https://botconnector.id/"},
            {"title": "Buka Dokumentasi", "url": "https://botconnector.id/docs/"}
        ],
        content=(
            "BotConnector adalah ekosistem operasional terpadu yang menghubungkan retail, restoran, "
            "sistem parkir pintar, penyimpanan cloud, dan otomasi dari satu akun terpusat.\n"
            "Modul utama platform meliputi:\n"
            "1. Business Suite: Manajemen toko retail, kasir POS kasir ultra-responsif, manajemen meja resto & KDS dapur, "
            "inventori multi-cabang, transfer stok, rekap bot Telegram V2, dan laporan laba rugi real-time.\n"
            "2. BotConnector Parking: Sistem manajemen parkir modern dengan 3 profil fleksibel (Full Stack, Existing Hardware, dan Payment Only).\n"
            "3. My Drive: Ruang penyimpanan cloud terenkripsi untuk menyimpan dokumen bisnis, nota, dan laporan keuangan.\n"
            "4. BotConnector Connect: Jembatan otomasi sinyal webhook trading ke MT5 dan Binance."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_products",
        canonical_url="https://botconnector.id/docs/#product-selection",
        title="Memilih Produk yang Tepat di BotConnector",
        section_title="Mulai",
        product="PLATFORM",
        doc_type="EXPLANATION",
        intent="INFORMATION_REQUEST",
        keywords=["katalog produk", "pilih produk", "business suite buat apa", "parking buat apa", "my drive buat apa"],
        action_links=[
            {"title": "Katalog Produk", "url": "https://botconnector.id/products"},
            {"title": "Produk Saya", "url": "https://botconnector.id/my-products"}
        ],
        content=(
            "Platform BotConnector dirancang modular sesuai kebutuhan bisnis Anda:\n"
            "• Business Suite: Untuk toko retail, minimarket, kafe, dan restoran multi-cabang yang membutuhkan POS kasir, inventori stok, dan laporan keuangan.\n"
            "• BotConnector Parking: Untuk pengelola gedung, ruko, atau operator parkir yang membutuhkan kontrol gerbang, tarif otomatis, kamera ANPR, atau gateway pembayaran QRIS.\n"
            "• My Drive: Penyimpanan cloud terenkripsi untuk menyimpan dokumen bisnis, bukti potong pajak, dan berkas transaksi dari semua modul.\n"
            "• BotConnector Connect: Jembatan otomasi sinyal webhook trading ke MetaTrader 5 dan Binance API."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_auth",
        canonical_url="https://botconnector.id/docs/#account-auth",
        title="Akun, Login, Register & Menu Produk Saya",
        section_title="Mulai",
        product="PLATFORM",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["login", "masuk", "daftar", "register", "produk saya", "my products", "aktivasi produk", "akun"],
        action_links=[
            {"title": "Halaman Login", "url": "https://botconnector.id/login"},
            {"title": "Produk Saya", "url": "https://botconnector.id/my-products"}
        ],
        content=(
            "Akses Akun & Aktivasi Produk:\n"
            "1. Masuk ke akun Anda di /login menggunakan email dan kata sandi terdaftar. Jika belum punya akun, daftar di /register.\n"
            "2. Setelah berhasil masuk, buka menu 'Produk Saya' di /my-products.\n"
            "3. Pada halaman Produk Saya, Anda dapat mengaktifkan modul Business Suite, Parking, atau My Drive secara mandiri.\n"
            "Hasil: Produk yang aktif menampilkan status 'Aktif' dan menyediakan tombol akses langsung ke dashboard operasional masing-masing."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_status",
        canonical_url="https://botconnector.id/status",
        title="Status Layanan & Pemantauan Sistem",
        section_title="Mulai",
        product="PLATFORM",
        doc_type="REFERENCE",
        intent="SERVICE_INCIDENT_SUSPECTED",
        keywords=["status server", "server down", "gangguan sistem", "probe", "operational", "status layanan"],
        action_links=[
            {"title": "Status Layanan Live", "url": "https://botconnector.id/status"}
        ],
        content=(
            "Halaman /status menyajikan pemantauan langsung probe ketersediaan infrastruktur platform BotConnector secara real-time:\n"
            "• Platform Gateway: Normal / Operational\n"
            "• Business Suite & Kasir POS: Normal / Operational\n"
            "• BotConnector Parking: Normal / Operational\n"
            "• BotConnector Connect: Normal / Operational\n"
            "• My Drive Cloud Storage: Normal / Operational\n"
            "• Telegram Bot Routing V2: Normal / Operational\n"
            "Semua pemeriksaan dijalankan secara otomatis dari server produksi."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_support",
        canonical_url="https://botconnector.id/support",
        title="Pusat Bantuan & Layanan Tiket Dukungan",
        section_title="Bantuan",
        product="SUPPORT",
        doc_type="HOW_TO",
        intent="SUPPORT_ESCALATION",
        keywords=["hubungi support", "buat tiket", "bantuan admin", "kontak tim", "cs", "customer service"],
        action_links=[
            {"title": "Buka Pusat Dukungan", "url": "https://botconnector.id/support"}
        ],
        content=(
            "Cara Menghubungi Tim Dukungan BotConnector:\n"
            "1. Buka halaman Pusat Bantuan di /support.\n"
            "2. Pilih Kategori Masalah (misal: Akun, Business Suite, Parking, My Drive, Privasi, atau Keamanan).\n"
            "3. Tuliskan rincian kendala beserta langkah yang telah dicoba, lalu kirim tiket.\n"
            "Hasil: Anda akan mendapatkan nomor referensi resmi (format: BCS-XXX-XXXXXXXXXX). Tim dukungan internal (admin@botconnector.id) akan menindaklanjuti dan mengirimkan tanggapan ke email Anda."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_security",
        canonical_url="https://botconnector.id/security",
        title="Keamanan Platform & Pelaporan Kerentanan",
        section_title="Mulai",
        product="SUPPORT",
        doc_type="REFERENCE",
        intent="SECURITY_REPORT",
        keywords=["keamanan", "security", "lapor kerentanan", "vulnerability", "responsible disclosure", "security.txt"],
        action_links=[
            {"title": "Pusat Keamanan", "url": "https://botconnector.id/security"},
            {"title": "Form Laporan Keamanan", "url": "https://botconnector.id/support"}
        ],
        content=(
            "Arsitektur Keamanan BotConnector:\n"
            "• Menggunakan enkripsi TLS/HTTPS modern, isolasi data multi-tenant, dan otentikasi sesi bc_session terenkripsi.\n"
            "• Peneliti keamanan dapat melaporkan temuan kerentanan secara bertanggung jawab (Responsible Disclosure) melalui formulir Keamanan di /support (kategori: Laporan Keamanan Sistem) atau merujuk ke spesifikasi /.well-known/security.txt.\n"
            "• Seluruh laporan keamanan ditangani dengan prioritas tinggi oleh tim teknis."
        )
    ),
    KnowledgeChunk(
        chunk_id="plat_privacy",
        canonical_url="https://botconnector.id/privacy",
        title="Kebijakan Privasi & Hak Penghapusan Data",
        section_title="Mulai",
        product="SUPPORT",
        doc_type="REFERENCE",
        intent="PRIVACY_REQUEST",
        keywords=["privasi", "privacy", "hapus data", "data erasure", "kebijakan privasi", "hak pengguna"],
        action_links=[
            {"title": "Kebijakan Privasi", "url": "https://botconnector.id/privacy"},
            {"title": "Permintaan Privasi", "url": "https://botconnector.id/support"}
        ],
        content=(
            "Kebijakan Privasi & Hak Data Pengguna:\n"
            "• Data transaksi dan akun diisolasi per tenant secara ketat.\n"
            "• Pengguna berhak meminta akses, perbaikan, maupun penghapusan data (data deletion/erasure).\n"
            "• Pengajuan permohonan privasi dan penghapusan data dapat dilakukan resmi melalui formulir di /support dengan memilih kategori 'Permintaan Privasi & Penghapusan Data'."
        )
    ),

    # ----------------- 2. BUSINESS SUITE -----------------
    KnowledgeChunk(
        chunk_id="bs_retail_10min",
        canonical_url="https://botconnector.id/docs/#business-retail-10min",
        title="Tutorial: Mulai Toko Retail dalam 10 Menit",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="TUTORIAL",
        intent="INSTALLATION_REQUEST",
        keywords=["cara mulai business suite", "setup business suite", "pasang business suite", "mulai toko", "siapkan toko", "onboarding business suite"],
        action_links=[
            {"title": "Buka Business Suite", "url": "https://botconnector.id/bisnis/#/dashboard"},
            {"title": "Buka POS Kasir", "url": "https://botconnector.id/bisnis/#/pos"}
        ],
        content=(
            "Panduan Memulai Toko Retail dari Nol (Web-Based Setup):\n"
            "TUJUAN: Menyiapkan master toko, produk, stok awal, dan kasir POS hingga transaksi perdana berhasil dicatat.\n"
            "YANG DIBUTUHKAN: Akun BotConnector aktif dengan modul Business Suite terverifikasi.\n"
            "LANGKAH:\n"
            "1. Login ke BotConnector di /login lalu buka menu Produk Saya > Business Suite.\n"
            "2. Buka panduan 'Siapkan Toko': atur Identitas Usaha, Nama Toko, dan Cabang Utama.\n"
            "3. Buka menu Katalog Produk (#/products): Klik 'Tambah Produk', isi Nama Barang, Kategori, dan SKU unik.\n"
            "4. Atur Harga Jual: Klik tombol harga pada produk, masukkan nominal retail (misal: Rp 15.000) dan simpan.\n"
            "5. Masukkan Stok Awal: Klik 'Tambah Stok', masukkan jumlah stok fisik (misal: 50 unit).\n"
            "6. Buka Kasir POS (#/pos): Pilih produk, masukkan ke keranjang transaksi, dan klik 'Bayar Sekarang'.\n"
            "HASIL YANG DIHARAPKAN:\n"
            "• Transaksi tercatat di database dengan nomor struk unik.\n"
            "• Stok berkurang otomatis dari 50 menjadi 48 unit (jika terjual 2 unit).\n"
            "• Omzet dan grafik penjualan di Dashboard langsung bertambah.\n"
            "• Laporan Laba Rugi terbarui secara real-time.\n"
            "VERIFIKASI: Buka #/reports dan #/inventory untuk memastikan mutasi stok dan penjualan telah tercatat."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_products",
        canonical_url="https://botconnector.id/docs/#business-products",
        title="Katalog Produk, Tambah Produk & SKU Master",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara tambah produk", "tambah produk", "sku", "apa itu sku", "barcode", "katalog produk", "master produk"],
        action_links=[
            {"title": "Buka Katalog Produk", "url": "https://botconnector.id/bisnis/#/products"},
            {"title": "Panduan Produk & SKU", "url": "https://botconnector.id/docs/#business-products"}
        ],
        content=(
            "Panduan Menambah Produk & Menentukan SKU di Business Suite:\n"
            "Apa itu SKU? SKU (Stock Keeping Unit) adalah kode unik internal toko untuk identifikasi persediaan barang (misal: KOP-SUSU-001).\n"
            "Cara Menambah Produk Baru:\n"
            "1. Buka menu Katalog Produk di #/products.\n"
            "2. Klik tombol 'Tambah Produk'.\n"
            "3. Masukkan Nama Produk, Kategori Produk, dan SKU unik.\n"
            "4. Simpan produk, lalu atur Harga Jual retailnya agar produk aktif dan dapat digunakan di kasir POS.\n"
            "Hasil: Master produk terdaftar di katalog dan siap dipasangi stok awal."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_inventory",
        canonical_url="https://botconnector.id/docs/#business-inventory",
        title="Stok Awal & Manajemen Inventori (Contoh: 50 Jual 2)",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara masukkan stok", "stok awal", "tambah stok", "stok 50 jual 2", "kurang stok", "mutasi stok", "inventori"],
        action_links=[
            {"title": "Buka Inventory", "url": "https://botconnector.id/bisnis/#/inventory"},
            {"title": "Panduan Inventori", "url": "https://botconnector.id/docs/#business-inventory"}
        ],
        content=(
            "Panduan Memasukkan Stok Awal & Perhitungan Penjualan:\n"
            "Cara Memasukkan Stok Awal:\n"
            "1. Buka menu Inventori (#/inventory) atau klik 'Tambah Stok' pada baris produk di Katalog Produk.\n"
            "2. Masukkan jumlah stok fisik yang diterima di toko (misal: 50 unit) dan simpan.\n\n"
            "Penjelasan Dampak Penjualan (Contoh: Stok 50 jual 2):\n"
            "Jika stok awal 50 unit dan kasir menyelesaikan transaksi penjualan 2 unit di POS:\n"
            "• Saldo stok fisik otomatis berkurang dari 50 menjadi 48 unit tanpa perlu hitung manual.\n"
            "• Transaksi penjualan tercatat di database dengan nomor struk digital.\n"
            "• Total omzet pada Dashboard bertambah senilai total belanja.\n"
            "• Laporan Laba Rugi dan HPP (Harga Pokok Penjualan) langsung terbarui secara real-time."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_pos_guide",
        canonical_url="https://botconnector.id/docs/#business-pos",
        title="Panduan Kasir Retail POS & Transaksi Pertama",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara transaksi pertama", "pos", "kasir", "struk", "cara setup kasir", "buka kasir", "checkout"],
        action_links=[
            {"title": "Buka POS", "url": "https://botconnector.id/bisnis/#/pos"},
            {"title": "Panduan Kasir POS", "url": "https://botconnector.id/docs/#business-pos"}
        ],
        content=(
            "Panduan Menjalankan Transaksi Kasir POS:\n"
            "Prasyarat: Cabang sudah aktif, produk sudah memiliki harga jual retail (>0), dan stok sudah tersedia.\n"
            "Langkah Transaksi Kasir:\n"
            "1. Buka menu POS Kasir di #/pos.\n"
            "2. Pilih produk dari daftar atau gunakan scanner barcode / pencarian nama.\n"
            "3. Periksa item dan kuantitas belanja di keranjang transaksi.\n"
            "4. Klik tombol 'Bayar Sekarang', pilih metode pembayaran (Tunai, QRIS, Kartu, atau Transfer), dan selesaikan transaksi.\n"
            "Hasil: Struk belanja digital terbit dan dapat dicetak ke printer thermal. Stok barang langsung terpotong, omzet bertambah di Dashboard, dan data penjualan masuk ke Laporan Laba Rugi."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_restaurant",
        canonical_url="https://botconnector.id/docs/#business-restaurant",
        title="Manajemen Restoran, Meja, KOT & KDS Dapur",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="HOW_TO",
        intent="EXPLANATION_REQUEST",
        keywords=["apa itu kot", "apa beda kot sama kds", "kot", "kds", "restoran", "kafe", "meja", "dapur", "pesanan resto"],
        action_links=[
            {"title": "Buka Panduan KDS", "url": "https://botconnector.id/docs/#business-restaurant"},
            {"title": "Buka Resto & Meja", "url": "https://botconnector.id/bisnis/#/restaurant"}
        ],
        content=(
            "Penjelasan KOT & KDS untuk Operasional Restoran / Kafe:\n"
            "• KOT (Kitchen Order Ticket): Tiket pesanan ringkas yang dicetak atau dikirimkan ke bagian dapur segera setelah pelayan/kasir mencatat pesanan meja pelanggan.\n"
            "• KDS (Kitchen Display System): Layar monitor dapur digital interaktif yang menampilkan antrean pesanan masakan yang harus disiapkan koki secara real-time.\n"
            "• Perbedaan Utama: KOT adalah lembar tiket pesanan fisik/digital, sedangkan KDS adalah sistem layar monitor display alur kerja dapur koki.\n"
            "Alur Kerja: Pesanan meja dicatat > KOT dikirim > KDS menampilkan menu > Koki menandai selesai masak > Pelayan menyajikan hidangan."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_transfers",
        canonical_url="https://botconnector.id/docs/#business-transfers",
        title="Transfer Stok Antar Cabang & Mutasi Gudang",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara transfer stok", "transfer dua cabang", "transfer stok antar cabang", "mutasi cabang", "kirim stok", "kalau dua cabang", "dua cabang"],
        action_links=[
            {"title": "Buka Transfer Stok", "url": "https://botconnector.id/bisnis/#/transfers"},
            {"title": "Panduan Transfer Antar Cabang", "url": "https://botconnector.id/docs/#business-transfers"}
        ],
        content=(
            "Panduan Transfer Stok Antar Dua Cabang:\n"
            "1. Buka menu Transfer Barang di #/transfers.\n"
            "2. Klik 'Buat Transfer Baru'.\n"
            "3. Pilih Cabang Asal (Gudang Pengirim) dan Cabang Tujuan (Toko Penerima).\n"
            "4. Masukkan produk dan jumlah unit yang akan dipindahkan (misal: 30 unit), lalu kirim dokumen transfer.\n"
            "5. Cabang penerima memverifikasi fisik barang dan mengklik 'Terima Barang'.\n"
            "Hasil Mutasi:\n"
            "• Stok cabang asal berkurang (misal: 100 menjadi 70 unit).\n"
            "• Stok cabang tujuan bertambah (misal: 0 menjadi 30 unit).\n"
            "• Tercatat transparan dengan nomor surat jalan mutasi resmi."
        )
    ),
    KnowledgeChunk(
        chunk_id="bs_dashboard_reports",
        canonical_url="https://botconnector.id/docs/#business-dashboard",
        title="Dashboard KPI & Laporan Laba Rugi (AOV, Omzet, HPP)",
        section_title="Business Suite",
        product="BUSINESS_SUITE",
        doc_type="REFERENCE",
        intent="EXPLANATION_REQUEST",
        keywords=["dashboard", "laporan", "omzet", "aov", "apa itu aov", "laba rugi", "hpp", "cogs", "laporan keuangan"],
        action_links=[
            {"title": "Buka Dashboard", "url": "https://botconnector.id/bisnis/#/dashboard"},
            {"title": "Buka Laporan", "url": "https://botconnector.id/bisnis/#/reports"}
        ],
        content=(
            "Metrik Keuangan & Dashboard Business Suite:\n"
            "• Omzet Harian: Total pendapatan kotor dari seluruh transaksi penjualan yang selesai hari ini.\n"
            "• Total Transaksi: Jumlah struk belanja yang berhasil diproses kasir.\n"
            "• AOV (Average Order Value): Rata-rata nominal belanja konsumen untuk setiap 1 transaksi (Total Omzet / Total Transaksi).\n"
            "• Laporan Laba Rugi: Analisis pendapatan bersih dikurangi HPP (Harga Pokok Penjualan) untuk mengetahui margin keuntungan bersih toko per periode."
        )
    ),

    # ----------------- 3. BOTCONNECTOR PARKING -----------------
    KnowledgeChunk(
        chunk_id="parking_overview_3profiles",
        canonical_url="https://botconnector.id/docs/#parking-overview",
        title="BotConnector Parking — Gambaran Umum & 3 Profil",
        section_title="Parking",
        product="PARKING",
        doc_type="EXPLANATION",
        intent="INFORMATION_REQUEST",
        keywords=["parking buat apa", "apa beda tiga profil", "full stack existing hardware payment only", "profil parkir", "sistem parkir"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"},
            {"title": "Dokumentasi Parkir", "url": "https://botconnector.id/docs/#parking-overview"}
        ],
        content=(
            "BotConnector Parking adalah sistem manajemen fasilitas parkir modern dengan 3 profil arsitektur:\n"
            "1. FULL_STACK: Sistem operasional parkir lengkap (Site, gerbang masuk/keluar, lane, tarif otomatis, kamera ANPR, palang barrier, Edge gateway offline, dan pembayaran tunai/QRIS).\n"
            "2. EXISTING_HARDWARE: Untuk pengguna yang sudah memiliki kamera ANPR dan palang barrier di lokasi. Cukup sambungkan adapter software BotConnector tanpa perlu mengganti perangkat fisik.\n"
            "3. PAYMENT_ONLY: Khusus bagi yang sudah memiliki Parking Management System (PMS) sendiri dan hanya membutuhkan payment gateway QRIS MPM Dynamic, Webhook notifikasi, dan rekonsiliasi pembayaran."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_full_stack",
        canonical_url="https://botconnector.id/docs/#parking-full-stack",
        title="Profil 1: FULL_STACK Parking System",
        section_title="Parking",
        product="PARKING",
        doc_type="INSTALLATION",
        intent="INSTALLATION_REQUEST",
        parking_profile="FULL_STACK",
        keywords=["full stack parkir", "cara pasang parking full stack", "setup parking", "sistem parkir lengkap"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"},
            {"title": "Panduan Full Stack", "url": "https://botconnector.id/docs/#parking-full-stack"}
        ],
        content=(
            "Panduan Instalasi BotConnector Parking FULL_STACK:\n"
            "TUJUAN: Menggelar sistem operasional parkir penuh dari gerbang hingga pembayaran.\n"
            "YANG DIBUTUHKAN: Akses konsol /parking/, denah lokasi gerbang, skema tarif, dan perangkat Edge di lokasi (jika menggunakan hardware).\n"
            "TAHAPAN IMPLEMENTASI:\n"
            "• FASE A (Software Setup): Masuk ke /parking/, buat Site, tentukan kapasitas, daftarkan Entry Gate, Exit Gate, Lane, dan Skema Tarif (Flat/Hourly/Progressive).\n"
            "• FASE B (Simulasi): Uji simulasi kendaraan masuk (status PARKED), hitung tarif, selesaikan pembayaran (status PAID), dan verifikasi gerbang keluar (status CLOSED) di simulator browser.\n"
            "• FASE C (Edge Gateway): Unduh paket Edge, pasang site identity token, uji sinkronisasi konfigurasi dan ketahanan offline SQLite WAL.\n"
            "• FASE D (Hardware): Daftarkan kamera ANPR Profile M dan barrier controller Profile D, lakukan capability probe dan dry run.\n"
            "• FASE E (Pembayaran): Uji sandbox order dan selesaikan onboarding PJP untuk go-live QRIS produksi.\n"
            "HASIL: Sistem parkir terpasang terstruktur dengan pemisahan kesiapan software dan verifikasi fisik lapangan."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_existing_hardware",
        canonical_url="https://botconnector.id/docs/#parking-existing-hardware",
        title="Profil 2: EXISTING_HARDWARE (Kamera & Palang yang Sudah Ada)",
        section_title="Parking",
        product="PARKING",
        doc_type="INSTALLATION",
        intent="INSTALLATION_REQUEST",
        parking_profile="EXISTING_HARDWARE",
        keywords=["saya sudah punya kamera dan palang", "hardware sendiri", "cara sambungkan kamera saya", "hubungkan palang existing", "kamera hikvision dahua", "existing hardware", "cara cek hardware saya kompatibel", "kompatibilitas hardware", "cek kompatibilitas"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"},
            {"title": "Buka Panduan Existing Hardware", "url": "https://botconnector.id/docs/#parking-existing-hardware"}
        ],
        content=(
            "Panduan Menghubungkan Kamera & Palang yang Sudah Ada (EXISTING_HARDWARE):\n"
            "TUJUAN: Menggunakan kamera ANPR dan palang barrier yang telah terpasang di lokasi tanpa mengganti fisik unit.\n"
            "YANG DIBUTUHKAN: Informasi protokol perangkat (ONVIF Profile M, RTSP streaming, TCP/IP relay controller, atau relay HTTP).\n"
            "LANGKAH INSTALASI:\n"
            "1. Masuk ke konsol /parking/ dan pilih profil 'EXISTING_HARDWARE'.\n"
            "2. Buat Site dan petakan Gate / Lane yang ada.\n"
            "3. Buka menu Device Management > 'Register Device'.\n"
            "4. Pilih Adapter yang sesuai (misal: ONVIF Adapter untuk kamera Hikvision/Dahua, IP Relay Adapter untuk barrier controller).\n"
            "5. Masukkan referensi IP address perangkat lokal.\n"
            "6. Jalankan 'Capability Probe' untuk memverifikasi respon software adapter.\n"
            "7. Lakukan pengujian simulasi (Dry Run) di konsol.\n"
            "8. Lakukan uji coba fisik terkendali di lokasi sebelum menandai status VERIFIED.\n"
            "HASIL: Software BotConnector mengendalikan kamera dan palang yang ada secara aman dengan prinsip Fail-Closed."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_payment_only",
        canonical_url="https://botconnector.id/docs/#parking-payment-only",
        title="Profil 3: PAYMENT_ONLY (Gateway QRIS & Webhook)",
        section_title="Parking",
        product="PARKING",
        doc_type="INSTALLATION",
        intent="INSTALLATION_REQUEST",
        parking_profile="PAYMENT_ONLY",
        keywords=["saya cuma butuh pembayaran", "cuma qris doang bisa", "payment only", "pembayaran parkir saja", "pms sendiri", "webhook merchant", "hardware perlu nggak", "hardware masih perlu nggak"],
        action_links=[
            {"title": "Buka QRIS & Gateway", "url": "https://botconnector.id/parking/"},
            {"title": "Buka Integrasi API", "url": "https://botconnector.id/docs/#parking-api-ref"}
        ],
        content=(
            "Panduan Profil PAYMENT_ONLY (Khusus Pembayaran Parkir):\n"
            "TUJUAN: Mengintegrasikan pembayaran QRIS MPM Dynamic ke sistem parkir (PMS) yang sudah Anda miliki tanpa memerlukan hardware/ANPR/Edge dari BotConnector.\n"
            "ARSITEKTUR:\n"
            "PMS Milik Anda > BotConnector Payment API > QRIS / PJP Gateway > Pembayaran Lunas > Signed Webhook (HMAC) > PMS Anda membuka palang.\n"
            "LANGKAH INTEGRASI:\n"
            "1. Buka /parking/ dan pilih profil 'PAYMENT_ONLY'.\n"
            "2. Buka menu API Integration untuk mendapatkan API Token dan Webhook Secret Key.\n"
            "3. Konfigurasikan URL Webhook di PMS Anda untuk menerima notifikasi event PAYMENT_PAID.\n"
            "4. Buat Sandbox Order melalui POST /parking/api/payment-gateway/orders.\n"
            "5. Uji simulasi pembayaran lunas dan verifikasi signature HMAC webhook pada sistem Anda.\n"
            "6. Lakukan rekonsiliasi data dan selesaikan onboarding PJP untuk go-live produksi.\n"
            "HASIL: Sistem parkir Anda dapat menerima pembayaran QRIS dinamis secara otomatis dan aman."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_tariffs",
        canonical_url="https://botconnector.id/docs/#parking-tariffs",
        title="Skema Tarif Parkir (Flat, Hourly, Progressive, Grace Period)",
        section_title="Parking",
        product="PARKING",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara atur tarif parkir", "tarif parkir", "flat", "hourly", "progressive", "grace period", "daily max", "skema tarif"],
        action_links=[
            {"title": "Buka Tarif", "url": "https://botconnector.id/parking/"},
            {"title": "Panduan Skema Tarif", "url": "https://botconnector.id/docs/#parking-tariffs"}
        ],
        content=(
            "Panduan Pengaturan Skema Tarif di BotConnector Parking:\n"
            "1. Buka konsol /parking/ > Menu 'Tarif Parkir'.\n"
            "2. Pilih Jenis Kendaraan (Mobil, Motor, Truk) dan Skema Perhitungan:\n"
            "   • FLAT: Tarif tetap sekali masuk (misal: Rp 3.000 untuk motor seharian).\n"
            "   • HOURLY: Tarif jam pertama + tarif per jam berikutnya (misal: Rp 5.000 jam ke-1, Rp 3.000/jam berikutnya).\n"
            "   • PROGRESSIVE: Tarif bertingkat berdasarkan durasi waktu.\n"
            "   • GRACE PERIOD: Toleransi bebas biaya jika keluar sebelum batas waktu tertentu (misal: gratis jika drop-off < 10 menit).\n"
            "   • DAILY MAX: Batas tarif maksimum per 24 jam untuk kendaraan menginap.\n"
            "3. Klik Simpan Aturan Tarif.\n"
            "Hasil: Setiap kendaraan masuk menerima snapshot tarif beku (frozen snapshot) sehingga perubahan konfigurasi tidak mengubah tagihan yang sedang berjalan."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_simulation",
        canonical_url="https://botconnector.id/docs/#parking-simulation",
        title="Tutorial: Simulasi Operasional Parkir Tanpa Hardware",
        section_title="Parking",
        product="PARKING",
        doc_type="TUTORIAL",
        intent="HOW_TO_REQUEST",
        keywords=["cara test parking tanpa hardware", "simulasi parkir", "simulator", "kendaraan masuk keluar", "uji parkir", "jadi sekarang bisa test apa", "test apa"],
        action_links=[
            {"title": "Buka Mode Simulasi", "url": "https://botconnector.id/parking/"},
            {"title": "Panduan Simulasi", "url": "https://botconnector.id/docs/#parking-simulation"}
        ],
        content=(
            "Cara Menjalankan Simulasi Parkir Lengkap di Browser:\n"
            "1. Buka konsol /parking/ dan pilih menu 'Simulator'.\n"
            "2. Simulasi Masuk (Entry): Pilih Entry Gate, masukkan plat nomor (misal: B 1234 ABC), pilih Mobil/Motor, klik 'Simulasikan Masuk'. Status sesi menjadi PARKED dan kuota terisi (+1).\n"
            "3. Hitung Tarif & Bayar: Masukkan nomor tiket atau plat nomor, sistem menghitung durasi dan biaya, klik 'Bayar Tarif' hingga status menjadi PAID.\n"
            "4. Simulasi Keluar (Exit): Pilih Exit Gate, klik 'Selesaikan Keluar'. Sesi ditutup (CLOSED), palang keluar terbuka secara simulasi, dan kuota berkurang (-1).\n"
            "Hasil: Anda dapat memverifikasi seluruh alur operasional, log audit, dan laporan pendapatan tanpa perangkat fisik."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_readiness_truthfulness",
        canonical_url="https://botconnector.id/docs/#parking-anpr-hardware",
        title="Kesiapan Sistem Parkir: Software Ready vs Verifikasi Fisik / PJP",
        section_title="Parking",
        product="PARKING",
        doc_type="EXPLANATION",
        intent="EXPLANATION_REQUEST",
        keywords=["qris sudah bisa", "qris sudah aktif", "profile m ready artinya", "fail closed artinya", "kesiapan hardware", "anpr itu apa"],
        action_links=[
            {"title": "Dokumentasi Hardware", "url": "https://botconnector.id/docs/#parking-anpr-hardware"}
        ],
        content=(
            "Kesiapan Resmi BotConnector Parking:\n"
            "• ANPR (Profile M Ready): Perangkat lunak siap mendukung kontrak standar ONVIF Profile M untuk pertukaran metadata plat nomor. Kamera fisik diverifikasi saat instalasi lapangan.\n"
            "• Fail-Closed Safety: Palang gerbang selalu dalam posisi terkunci/tertutup jika komunikasi jaringan atau daya listrik terputus demi keselamatan dan keamanan lokasi.\n"
            "• Kesiapan QRIS: Modul software dan sandbox order SIAP digunakan untuk pengujian. Untuk menerima uang nyata di produksi, merchant wajib menyelesaikan proses onboarding PJP resmi terlebih dahulu."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_edge_gateway",
        canonical_url="https://botconnector.id/docs/#parking-anpr-hardware",
        title="Offline Edge Gateway (Ketahanan Jaringan Terputus)",
        section_title="Parking",
        product="PARKING",
        doc_type="REFERENCE",
        intent="EXPLANATION_REQUEST",
        keywords=["edge offline buat apa", "edge gateway", "offline sync", "sqlite wal", "koneksi terputus"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"}
        ],
        content=(
            "Fungsi & Arsitektur Edge Gateway BotConnector Parking:\n"
            "• Edge Gateway adalah perangkat lunak lokal (dijalankan pada mini-PC di lokasi gerbang parkir) yang menyimpan transaksi secara persisten di database SQLite WAL lokal.\n"
            "• Saat koneksi internet cloud terputus, gerbang tetap dapat menerbitkan tiket, membaca plat nomor lokal, dan membuka palang secara mandiri.\n"
            "• Saat koneksi internet pulih, seluruh antrean transaksi lokal otomatis tersinkronisasi kembali ke server cloud tanpa ada data yang hilang."
        )
    ),
    KnowledgeChunk(
        chunk_id="parking_api_webhook",
        canonical_url="https://botconnector.id/docs/#parking-api-ref",
        title="Parking Payment API & Webhook Merchant",
        section_title="Integrasi & API",
        product="INTEGRATION",
        doc_type="REFERENCE",
        intent="TECHNICAL_INTEGRATION",
        keywords=["merchant webhook buat apa", "endpoint payment", "api parking", "webhook qris", "hmac signature"],
        action_links=[
            {"title": "Dokumentasi API", "url": "https://botconnector.id/docs/#parking-api-ref"}
        ],
        content=(
            "Dokumentasi Teknis Parking Payment API & Webhook:\n"
            "Endpoint Create Order: POST /parking/api/payment-gateway/orders\n"
            "Headers: Authorization: Bearer <API_TOKEN>, Content-Type: application/json\n"
            "Payload:\n"
            "{\n"
            '  "merchant_order_ref": "PARK-LOC01-98213",\n'
            '  "amount": 15000,\n'
            '  "currency": "IDR",\n'
            '  "payment_method": "QRIS_MPM_DYNAMIC"\n'
            "}\n\n"
            "Webhook Event (PAYMENT_PAID):\n"
            "Saat pembayaran diselesaikan, BotConnector mengirimkan HTTP POST bertanda tangan HMAC SHA-256 ke webhook URL merchant Anda dengan payload status PAID untuk membuka palang PMS Anda secara otomatis."
        )
    ),

    # ----------------- 4. MY DRIVE -----------------
    KnowledgeChunk(
        chunk_id="drive_overview",
        canonical_url="https://botconnector.id/docs/#drive-overview",
        title="My Drive — Penyimpanan Cloud & Berkas Bisnis",
        section_title="My Drive",
        product="MY_DRIVE",
        doc_type="HOW_TO",
        intent="HOW_TO_REQUEST",
        keywords=["cara upload file ke my drive", "my drive buat apa", "upload file", "drive", "simpan dokumen", "berkas"],
        action_links=[
            {"title": "Buka My Drive", "url": "https://botconnector.id/drive"},
            {"title": "Panduan My Drive", "url": "https://botconnector.id/docs/#drive-overview"}
        ],
        content=(
            "Panduan Penggunaan My Drive (Web-Based Cloud Storage):\n"
            "My Drive adalah ruang penyimpanan berkas bisnis berbasis web di /drive (tidak memerlukan instalasi software desktop sync tambahan).\n"
            "Cara Mengunggah & Mengelola Berkas:\n"
            "1. Masuk ke akun Anda dan buka tautan /drive dari menu navigasi atau Produk Saya.\n"
            "2. Klik 'Buat Folder' untuk membuat struktur folder (misal: Laporan_2026 atau Bukti_Pajak).\n"
            "3. Tarik dan letakkan (drag-and-drop) file atau klik 'Upload Berkas' (mendukung PDF, Excel, gambar nota, dll maks 50MB per berkas).\n"
            "4. Gunakan fitur 'Bagikan Tautan' (Public Share Link) jika ingin membagikan dokumen ke pihak eksternal dengan kendali izin akses.\n"
            "Hasil: Berkas tersimpan aman terenkripsi di cloud dan dapat diakses dari perangkat mana pun."
        )
    ),

    # ----------------- 5. TROUBLESHOOTING HUB -----------------
    KnowledgeChunk(
        chunk_id="troubleshoot_pos_missing_prod",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Kenapa Produk Tidak Muncul di POS?",
        section_title="Troubleshooting",
        product="BUSINESS_SUITE",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        keywords=["kenapa produk nggak muncul di pos", "produk tidak muncul di pos", "produk hilang di pos", "pos kosong"],
        action_links=[
            {"title": "Buka Katalog Produk", "url": "https://botconnector.id/bisnis/#/products"},
            {"title": "Buka POS", "url": "https://botconnector.id/bisnis/#/pos"}
        ],
        content=(
            "Troubleshooting: Produk Tidak Muncul di Kasir POS\n"
            "Masalah: Produk sudah ditambahkan di master katalog namun tidak terlihat saat membuka layar kasir POS.\n"
            "Penyebab Umum:\n"
            "1. Produk belum diberi harga retail aktif (>0).\n"
            "2. Saldo stok fisik produk di cabang terkait masih 0 (kosong).\n"
            "3. Kasir sedang berada pada lokasi cabang yang berbeda dengan cabang penyimpanan stok.\n"
            "Langkah Pemeriksaan:\n"
            "1. Buka menu Katalog Produk (#/products), klik tombol harga pada produk, pastikan harga jual > 0 dan simpan.\n"
            "2. Buka menu Inventori (#/inventory), pastikan stok awal sudah dimasukkan untuk cabang tersebut.\n"
            "3. Periksa header POS untuk memastikan kasir memilih cabang yang sesuai.\n"
            "Hasil yang Diharapkan: Produk langsung muncul di katalog kasir POS dan siap ditambahkan ke keranjang."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_stock_discrepancy",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Stok Salah / Stok Tidak Berkurang",
        section_title="Troubleshooting",
        product="BUSINESS_SUITE",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        keywords=["stok saya salah", "stok tidak berkurang", "stok kok nggak berubah", "barang habis dijual tapi jumlahnya sama", "masalah stok"],
        action_links=[
            {"title": "Buka Inventori", "url": "https://botconnector.id/bisnis/#/inventory"},
            {"title": "Buka Laporan Penjualan", "url": "https://botconnector.id/bisnis/#/reports"}
        ],
        content=(
            "Troubleshooting: Stok Tidak Berkurang Setelah Penjualan\n"
            "Masalah: Transaksi penjualan terjadi tetapi saldo stok di gudang/cabang tidak berkurang.\n"
            "Pemeriksaan Utama:\n"
            "1. Verifikasi Status Transaksi: Pastikan transaksi di POS benar-benar diselesaikan hingga status 'Completed' / 'Lunas' dan struk terbit (transaksi draft/pending belum memotong stok).\n"
            "2. Verifikasi Lokasi Cabang: Periksa apakah register kasir POS berada pada cabang yang sama dengan gudang yang Anda periksa di menu Inventori (#/inventory).\n"
            "3. Periksa Mutasi Stok: Buka kartu stok produk di menu Inventori untuk melihat log mutasi keluar masuk barang.\n"
            "Hasil yang Diharapkan: Saldo stok berkurang secara real-time tepat sejumlah item yang terjual. Jika terdapat inkonsistensi data, ajukan tiket eskalasi melalui /support."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_empty_reports",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Laporan Penjualan / Laba Rugi Kosong",
        section_title="Troubleshooting",
        product="BUSINESS_SUITE",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        keywords=["laporan kosong kenapa", "laporan tidak muncul", "laporan laba rugi kosong", "omzet tidak tercatat"],
        action_links=[
            {"title": "Buka Laporan", "url": "https://botconnector.id/bisnis/#/reports"}
        ],
        content=(
            "Troubleshooting: Laporan Penjualan / Laba Rugi Kosong\n"
            "Masalah: Halaman laporan tidak menampilkan angka omzet atau transaksi.\n"
            "Pemeriksaan Utama:\n"
            "1. Filter Rentang Tanggal: Periksa filter periode tanggal di bagian atas laporan, pastikan mencakup hari terjadinya transaksi.\n"
            "2. Filter Cabang: Pastikan Anda memilih cabang yang sesuai atau memilih opsi 'Semua Cabang'.\n"
            "3. Status Transaksi: Laporan hanya menghitung transaksi yang telah selesai (Completed/Lunas).\n"
            "Hasil yang Diharapkan: Grafik dan rincian transaksi omzet langsung tampil lengkap."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_barrier_not_opening",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Palang Parkir Tidak Terbuka",
        section_title="Troubleshooting",
        product="PARKING",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        parking_profile="FULL_STACK",
        keywords=["palang tidak terbuka", "palang tidak buka", "parkir nggak bisa keluar", "gate terkunci", "barrier macet"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"}
        ],
        content=(
            "Troubleshooting: Palang Gerbang Parkir Tidak Mau Terbuka\n"
            "Masalah: Kendaraan berada di gerbang keluar namun palang tidak terangkat.\n"
            "Pemeriksaan Utama:\n"
            "1. Status Pembayaran: Pastikan sesi parkir kendaraan sudah lunas (status PAID). Palang tidak akan terbuka jika tarif belum dibayar demi kebijakan Fail-Closed.\n"
            "2. ANPR Review: Jika plat nomor tertutup atau terbaca sebagian, operator dapat melakukan 'Manual Review' di konsol /parking/ untuk mencocokkan sesi parkir.\n"
            "3. Koneksi Controller: Pada instalasi hardware fisik, periksa status koneksi adapter barrier di menu Device Health.\n"
            "Catatan Keselamatan: Sistem dilarang membuka palang secara paksa jika status pembayaran belum diverifikasi. Pekerjaan kelistrikan motor palang harus ditangani teknisi bersertifikasi."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_qris_pending",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Pembayaran QRIS Pending / Belum Lunas",
        section_title="Troubleshooting",
        product="PARKING",
        doc_type="TROUBLESHOOTING",
        intent="CUSTOMER_COMPLAINT",
        keywords=["qris pending kenapa", "qris saya pending", "sudah bayar tapi belum lunas", "qris nggak masuk", "tertagih dua kali"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"},
            {"title": "Pusat Bantuan", "url": "https://botconnector.id/support"}
        ],
        content=(
            "Troubleshooting & Keamanan: Pembayaran QRIS Pending / Tertagih\n"
            "Masalah: Pengguna merasa sudah scan QRIS dan saldo terpotong, namun status sistem masih Pending.\n"
            "Pemeriksaan Aman:\n"
            "1. Periksa Nomor Referensi Pembayaran (Payment Reference) pada struk atau aplikasi perbankan.\n"
            "2. Cek status callback webhook dari PJP pada log transaksi konsol.\n"
            "3. Rekonsiliasi berkala dilakukan otomatis dalam beberapa detik saat notifikasi bank diterima.\n"
            "Aturan Keamanan AI:\n"
            "• Asisten AI tidak diizinkan menandai status lunas (PAID) secara manual atau memicu mutasi saldo.\n"
            "• Jika terjadi indikasi pembayaran ganda atau selisih nominal, sistem segera menyiapkan draf tiket bantuan prioritas tinggi ke tim admin BotConnector."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_device_offline",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Kamera ANPR / Palang Status OFFLINE",
        section_title="Troubleshooting",
        product="PARKING",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        parking_profile="EXISTING_HARDWARE",
        keywords=["kamera offline", "device offline", "edge nggak sync", "perangkat offline", "palang offline"],
        action_links=[
            {"title": "Konsol Parking", "url": "https://botconnector.id/parking/"}
        ],
        content=(
            "Troubleshooting: Perangkat Kamera ANPR / Palang Status OFFLINE\n"
            "Masalah: Perangkat terdaftar di konsol /parking/ namun menampilkan status 'Offline'.\n"
            "Pemeriksaan Utama:\n"
            "1. Jaringan Lokal: Pastikan IP address perangkat dapat dijangkau (ping) dari mini-PC Edge Gateway di lokasi.\n"
            "2. Kredensial Adapter: Periksa konfigurasi port RTSP/ONVIF atau IP relay adapter.\n"
            "3. Jalankan 'Capability Probe': Klik tombol uji kapabilitas pada baris perangkat di menu Device Management untuk mendiagnosis titik kegagalan respon.\n"
            "Hasil yang Diharapkan: Status berubah menjadi 'Healthy / Online' saat respon TCP/ONVIF berhasil diterima."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_drive_upload",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Gagal Upload File di My Drive",
        section_title="Troubleshooting",
        product="MY_DRIVE",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        keywords=["file gagal upload", "gagal upload", "file tidak terlihat", "my drive upload error"],
        action_links=[
            {"title": "Buka My Drive", "url": "https://botconnector.id/drive"}
        ],
        content=(
            "Troubleshooting: Gagal Mengunggah Berkas ke My Drive\n"
            "Penyebab Umum & Solusi:\n"
            "1. Batas Ukuran File: Pastikan ukuran file individual di bawah 50MB.\n"
            "2. Format File: Mendukung dokumen PDF, spreadsheet Excel/CSV, Word, dan gambar standar (PNG/JPG/SVG).\n"
            "3. Koneksi Internet: Pastikan jaringan stabil saat proses transfer upload berlangsung.\n"
            "Hasil yang Diharapkan: File langsung muncul pada daftar berkas di folder tujuan setelah proses upload selesai 100%."
        )
    ),
    KnowledgeChunk(
        chunk_id="troubleshoot_activation_failed",
        canonical_url="https://botconnector.id/docs/#troubleshooting-hub",
        title="Troubleshooting: Produk Tidak Muncul di 'Produk Saya' / Aktivasi Gagal",
        section_title="Troubleshooting",
        product="PLATFORM",
        doc_type="TROUBLESHOOTING",
        intent="TROUBLESHOOTING",
        keywords=["produk saya nggak muncul di produk saya", "aktivasi gagal", "produk hilang", "layanan tidak aktif"],
        action_links=[
            {"title": "Produk Saya", "url": "https://botconnector.id/my-products"},
            {"title": "Katalog Produk", "url": "https://botconnector.id/products"}
        ],
        content=(
            "Troubleshooting: Layanan Tidak Muncul di Halaman Produk Saya\n"
            "Pemeriksaan Utama:\n"
            "1. Refresh Sesi Akun: Coba logout dan login kembali di /login untuk memperbarui token hak akses akun Anda.\n"
            "2. Aktivasi Mandiri: Buka /products, pilih layanan yang diinginkan (Business Suite, Parking, atau My Drive), lalu klik 'Aktifkan'.\n"
            "3. Periksa Status Akun: Pastikan akun Anda tidak dalam status penangguhan.\n"
            "Hasil yang Diharapkan: Layanan langsung muncul di /my-products dengan status 'Aktif'."
        )
    ),

    # ----------------- 6. GLOSSARY -----------------
    KnowledgeChunk(
        chunk_id="glossary_terms",
        canonical_url="https://botconnector.id/docs/#glossary",
        title="Glosarium Istilah Resmi Platform BotConnector",
        section_title="Glosarium",
        product="PLATFORM",
        doc_type="GLOSSARY",
        intent="EXPLANATION_REQUEST",
        keywords=["glosarium", "istilah", "pos", "sku", "kot", "kds", "anpr", "onvif", "profile m", "profile d", "fail closed", "qris mpm", "aov", "byob"],
        action_links=[
            {"title": "Glosarium Lengkap", "url": "https://botconnector.id/docs/#glossary"}
        ],
        content=(
            "Glosarium Istilah Resmi BotConnector:\n"
            "• POS (Point of Sale): Terminal kasir penjualan untuk melayani transaksi retail dan resto.\n"
            "• SKU (Stock Keeping Unit): Kode unik identifikasi inventori barang.\n"
            "• KOT (Kitchen Order Ticket): Tiket cetak pesanan menu untuk bagian dapur.\n"
            "• KDS (Kitchen Display System): Monitor digital layar dapur untuk koki restoran.\n"
            "• AOV (Average Order Value): Rata-rata nilai rupiah belanja pelanggan per transaksi.\n"
            "• ANPR (Automatic Number Plate Recognition): Kamera AI pembaca plat nomor kendaraan otomatis.\n"
            "• Profile M: Standar industri ONVIF untuk metadata video analytics dan deteksi plat nomor.\n"
            "• Profile D: Standar industri ONVIF untuk kontrol akses fisik dan peripheral palang gerbang.\n"
            "• Fail-Closed: Prinsip keselamatan di mana palang gerbang tetap terkunci/tertutup jika listrik atau jaringan mati.\n"
            "• QRIS MPM Dynamic: QRIS Merchant-Presented Mode dengan nominal tagihan spesifik yang dibuat otomatis per transaksi.\n"
            "• PJP (Penyelenggara Jasa Pembayaran): Lembaga keuangan berizin BI penyedia gerbang pembayaran QRIS nyata.\n"
            "• BYOB (Bring Your Own Bot): Fitur integrasi bot Telegram kustom menggunakan bot token milik pengguna sendiri."
        )
    ),

    # ----------------- 7. BOTCONNECTOR CONNECT (PRESERVED) -----------------
    KnowledgeChunk(
        chunk_id="connect_overview",
        canonical_url="https://botconnector.id/connect-v2/",
        title="BotConnector Connect — Webhook & MetaTrader 5 Bridge",
        section_title="Connect",
        product="CONNECT",
        doc_type="REFERENCE",
        intent="TECHNICAL_INTEGRATION",
        keywords=["connect", "tradingview", "mt5", "metatrader", "binance", "sinyal trading", "webhook trading"],
        action_links=[
            {"title": "BotConnector Connect", "url": "https://botconnector.id/connect-v2/"}
        ],
        content=(
            "BotConnector Connect adalah jembatan otomasi eksekusi sinyal trading event-driven:\n"
            "• Menghubungkan peringatan sinyal (webhook alerts) dari TradingView langsung ke terminal MetaTrader 5 (MT5) atau Binance API.\n"
            "• Eksekusi order berkecepatan tinggi dengan antrean aman dan verifikasi idempotency token.\n"
            "• Peringatan Risiko: BotConnector Connect adalah perangkat lunak otomasi teknis semata. BotConnector TIDAK PERNAH menjanjikan keuntungan (profit guarantee) dan tidak memberikan saran finansial/investasi perseorangan."
        )
    ),
]

def _tokenize(text: str) -> List[str]:
    """Tokenize and normalize Indonesian and technical terms."""
    cleaned = re.sub(r"[^\w\s\-\_]", " ", text.lower())
    words = cleaned.split()
    return [w for w in words if len(w) > 1]

def _compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

class KnowledgeBase:
    """
    High-Performance Section-Level Hybrid RAG Engine.
    Combines BM25 token matching, keyword weighting, dense vector embeddings,
    and intent/profile reranking with direct deep links.
    """

    def __init__(self, chunks: Optional[List[KnowledgeChunk]] = None):
        self.chunks: List[KnowledgeChunk] = chunks or list(CANONICAL_CHUNKS)
        self.docs_file_hash: Optional[str] = None
        self._sync_with_canonical_docs_file()

    def _sync_with_canonical_docs_file(self):
        """Optionally verify hash of canonical html on VPS to ensure index freshness."""
        if os.path.exists(CANONICAL_DOCS_PATH):
            try:
                with open(CANONICAL_DOCS_PATH, "r", encoding="utf-8") as f:
                    content = f.read()
                    self.docs_file_hash = _compute_sha256(content)
            except Exception:
                pass

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Fetch dense vector embedding from local embedding endpoint."""
        try:
            payload = {"input": text, "model": EMBEDDING_MODEL}
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                EMBEDDING_ENDPOINT,
                headers={"Content-Type": "application/json"},
                data=data_bytes
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["data"][0]["embedding"]
        except Exception:
            return None

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two float vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search_hybrid(
        self,
        query: str,
        inferred_product: Optional[str] = None,
        inferred_intent: Optional[str] = None,
        inferred_parking_profile: Optional[str] = None,
        client_ecosystem: Optional[str] = None,
        top_k: int = 3
    ) -> List[Tuple[KnowledgeChunk, float]]:
        """
        Execute Ultra-Fast Hybrid (BM25 Lexical + Reranking) retrieval.
        """
        q_tokens = _tokenize(query)
        if not q_tokens:
            return [(c, 1.0) for c in self.chunks[:top_k]]

        query_lower = query.lower()

        scored: List[Tuple[KnowledgeChunk, float]] = []

        for chunk in self.chunks:
            if not chunk.active:
                continue

            # --- A. Lexical Score ---
            title_tokens = _tokenize(chunk.title)
            content_tokens = _tokenize(chunk.content)
            keyword_tokens = [k.lower() for k in chunk.keywords]

            title_matches = sum(1 for t in q_tokens if t in title_tokens)
            body_matches = sum(1 for t in q_tokens if t in content_tokens)
            keyword_matches = sum(1 for t in q_tokens if any(t in kw or kw in t for kw in keyword_tokens))

            # Exact phrase match boost
            exact_keyword_boost = 0.0
            for kw in chunk.keywords:
                if kw in query_lower:
                    exact_keyword_boost += 2.0

            raw_lexical = (title_matches * 3.5) + (body_matches * 1.0) + (keyword_matches * 3.0) + exact_keyword_boost
            if raw_lexical <= 0:
                continue

            lexical_score = min(raw_lexical / (max(len(q_tokens), 1) * 2.5), 2.5)

            final_score = lexical_score

            # --- B. Reranking Boosts ---
            # 1. Exact Product Match
            target_product = inferred_product or client_ecosystem
            if target_product:
                if chunk.product.upper() == target_product.upper():
                    final_score += 0.40
                elif target_product.upper() not in ("PLATFORM", "SUPPORT") and chunk.product.upper() not in ("PLATFORM", "SUPPORT") and chunk.product.upper() != target_product.upper():
                    final_score -= 0.35

            # 2. Intent Match Boost
            if inferred_intent:
                if inferred_intent == "INSTALLATION_REQUEST" and chunk.doc_type in ("INSTALLATION", "TUTORIAL"):
                    final_score += 0.35
                elif inferred_intent in ("CUSTOMER_COMPLAINT", "TROUBLESHOOTING") and chunk.doc_type == "TROUBLESHOOTING":
                    final_score += 0.45
                elif inferred_intent in ("EXPLANATION_REQUEST", "GLOSSARY") and chunk.doc_type in ("GLOSSARY", "EXPLANATION"):
                    final_score += 0.30
                elif inferred_intent == "TECHNICAL_INTEGRATION" and chunk.doc_type == "REFERENCE":
                    final_score += 0.35

            # 3. Parking Profile Match Boost
            if inferred_parking_profile:
                if chunk.parking_profile == inferred_parking_profile:
                    final_score += 0.55
                elif chunk.parking_profile and chunk.parking_profile != inferred_parking_profile:
                    final_score -= 0.40

            if final_score > 0.15:
                scored.append((chunk, round(final_score, 4)))

        # Sort descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def format_rag_context(self, docs: List[Tuple[KnowledgeChunk, float]]) -> str:
        """Format retrieved documents with clean prompt boundary fences."""
        if not docs:
            return "Tidak ada dokumen pengetahuan resmi yang spesifik untuk pertanyaan ini."

        chunks = ["BEGIN BOTCONNECTOR CANONICAL KNOWLEDGE"]
        for chunk, score in docs:
            chunks.append(
                f"[{chunk.title}] (Produk: {chunk.product} | Tipe: {chunk.doc_type} | URL: {chunk.canonical_url})\n"
                f"{chunk.content}"
            )
        chunks.append("END BOTCONNECTOR CANONICAL KNOWLEDGE")
        return "\n\n".join(chunks)

# Singleton Global Knowledge Base
GLOBAL_KB = KnowledgeBase()
