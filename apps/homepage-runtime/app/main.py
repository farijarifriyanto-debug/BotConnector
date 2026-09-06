import csv
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .ai_bridge import (
    BusinessAIError,
    PersonalAIError,
    assist_business_lead,
    generate_creator_plan,
    generate_freelancer_plan,
    simulate_whatsapp_admin,
)
from .core_bridge import (
    CoreAPIError,
    activate_product as core_activate_product,
    active_candidate_products as core_active_products,
    api_request as core_api_request,
    clear_browser_session,
    core_slug,
    create_project as core_create_project,
    current_user as core_current_user,
    get_onboarding as core_get_onboarding,
    get_project as core_get_project,
    list_projects as core_list_projects,
    response_session_token,
    set_browser_session,
    update_onboarding as core_update_onboarding,
    update_project as core_update_project,
)
from .staging_control import is_platform_admin, register_staging_control

BASE_DIR = Path(__file__).resolve().parent
settings = get_settings()

app = FastAPI(
    title="BotConnector Platform",
    description="Satu akun dengan ruang produk dan bantuan pembuatan yang terpisah.",
    version="0.15.4",
    docs_url="/api/docs",
    redoc_url=None,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.core_cookie_secure,
    max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

from .support_ai_routes import router as support_ai_router
app.include_router(support_ai_router)



def menu(slug: str, label: str, title: str, text: str) -> dict[str, str]:
    return {"slug": slug, "label": label, "title": title, "text": text}


PRODUCTS: list[dict[str, Any]] = [
    {
        "slug": "webhook",
        "eyebrow": "KONEKSI",
        "name": "Webhook Connector",
        "short_summary": "Menghubungkan TradingView.",
        "summary": "Ceritakan koneksi yang dibutuhkan. BotConnector membantu menyiapkan konfigurasi, pengujian, dan langkah aktivasinya.",
        "features": ["Susun koneksi", "Uji pesan", "Pantau status"],
        "status": "Tersedia",
        "status_class": "live",
        "url": settings.webhook_url,
        "cta": "Buka Webhook",
        "home_cta": "Pilih",
        "icon": "pulse",
        "accent": "blue",
        "onboarding_title": "Apa yang ingin Anda hubungkan?",
        "onboarding_text": "Ceritakan tujuan koneksi. BotConnector akan membantu menyiapkannya dari awal.",
        "starter_choices": ["TradingView ke MetaTrader", "TradingView ke Binance", "Webhook ke aplikasi lain", "Belum yakin"],
        "menu": [
            menu("overview", "Dashboard", "Ringkasan Webhook", "Mulai atau lanjutkan koneksi yang sedang disiapkan."),
            menu("tradingview", "TradingView", "TradingView", "Siapkan alert TradingView sesuai strategi Anda."),
            menu("metatrader", "MetaTrader", "MetaTrader", "Siapkan koneksi dan pemetaan order ke MetaTrader."),
            menu("connections", "Koneksi", "Koneksi", "Susun sumber, tujuan, dan aturan pengiriman."),
            menu("activity", "Aktivitas", "Aktivitas", "Periksa pesan, status proses, dan masalah pengiriman."),
            menu("settings", "Pengaturan", "Pengaturan", "Sesuaikan aturan koneksi dan notifikasi."),
        ],
        "cards": [
            {"label": "Koneksi", "value": "Belum dihubungkan"},
            {"label": "Pesan hari ini", "value": "Belum ada data"},
            {"label": "Status", "value": "Siap dibantu"},
        ],
    },
    {
        "slug": "ai",
        "eyebrow": "AI",
        "name": "BotConnector AI",
        "short_summary": "Asisten AI dengan riwayat dan konteks percakapan.",
        "summary": "Gunakan BotConnector AI untuk berdiskusi, menulis, menganalisis, dan menyelesaikan pekerjaan dalam satu workspace.",
        "features": ["Percakapan kontekstual", "Riwayat tersimpan", "Mode cepat hingga mendalam"],
        "status": "Tersedia",
        "status_class": "live",
        "url": "/panel/ai/",
        "direct_url": "/panel/ai/",
        "cta": "Buka BotConnector AI",
        "home_cta": "Buka",
        "icon": "spark",
        "accent": "violet",
        "onboarding_title": "Apa yang ingin Anda kerjakan?",
        "onboarding_text": "Mulai percakapan dan BotConnector AI akan mempertahankan konteksnya.",
        "starter_choices": ["Tulis dan ringkas", "Riset topik", "Bantu coding", "Diskusi ide"],
        "menu": [],
        "cards": [],
    },
    {
        "slug": "document",
        "eyebrow": "DOKUMEN",
        "name": "Document Assistant",
        "short_summary": "Mengubah PDF digital atau scan ke Excel dan Word.",
        "summary": "Unggah PDF dan unduh hasil Excel atau Word yang dapat diperiksa kembali.",
        "features": ["PDF digital", "OCR dokumen scan", "Excel dan Word"],
        "status": "Tersedia gratis",
        "status_class": "live",
        "url": "/document-assistant/",
        "direct_url": "/document-assistant/",
        "cta": "Buka Document Assistant",
        "home_cta": "Buka",
        "icon": "document",
        "accent": "blue",
        "onboarding_title": "Dokumen apa yang ingin dikonversi?",
        "onboarding_text": "Pilih PDF digital atau scan dan tentukan format hasil.",
        "starter_choices": ["PDF ke Excel", "PDF ke Word"],
        "menu": [],
        "cards": [],
    },
    {
        "slug": "langkah",
        "eyebrow": "PELUANG",
        "name": "LANGKAH",
        "short_summary": "Mencari lowongan dan menyiapkan CV.",
        "summary": "Ceritakan tujuan kerja Anda. LANGKAH membantu mencari lowongan, membuat CV, menyiapkan lamaran, dan berlatih wawancara.",
        "features": ["Cari lowongan", "Buat CV", "Siapkan seleksi"],
        "status": "Sedang diuji",
        "status_class": "beta",
        "url": settings.langkah_url,
        "cta": "Buka LANGKAH",
        "home_cta": "Pilih",
        "icon": "path",
        "accent": "violet",
        "onboarding_title": "Apa tujuan kerja Anda?",
        "onboarding_text": "Mulai dari tujuan sederhana. LANGKAH akan membantu menyiapkan setiap bagian sampai siap digunakan.",
        "starter_choices": ["Mencari pekerjaan pertama", "Pindah pekerjaan", "Membuat atau memperbaiki CV", "Persiapan wawancara"],
        "menu": [
            menu("overview", "Dashboard", "Ringkasan LANGKAH", "Lihat kebutuhan kerja yang sedang dibantu dan langkah berikutnya."),
            menu("jobs", "Temukan Lowongan", "Temukan Lowongan", "Cari dan saring lowongan sesuai tujuan, kemampuan, dan lokasi Anda."),
            menu("match", "Kecocokan", "Kecocokan", "Bandingkan profil Anda dengan persyaratan lowongan."),
            menu("cv", "Buat CV", "Buat CV", "Buat CV dari awal atau sesuaikan CV untuk lowongan tertentu."),
            menu("pack", "Berkas Lamaran", "Berkas Lamaran", "Siapkan surat lamaran, email, dan dokumen pendukung."),
            menu("applications", "Progres", "Progres Lamaran", "Catat proses lamaran dan tindak lanjut yang perlu dilakukan."),
            menu("interview", "Latihan Wawancara", "Latihan Wawancara", "Latih jawaban dan perbaiki cara menyampaikannya."),
        ],
        "cards": [
            {"label": "Lowongan tersimpan", "value": "Belum ada"},
            {"label": "CV aktif", "value": "Belum dibuat"},
            {"label": "Lamaran", "value": "Belum ada"},
        ],
    },
    {
        "slug": "business",
        "eyebrow": "BISNIS",
        "name": "Business Automation",
        "short_summary": "WhatsApp AI dan workflow bisnis.",
        "summary": "Ceritakan cara kerja bisnis Anda. BotConnector membantu menyiapkan WhatsApp AI Admin, pengelolaan prospek, booking, tindak lanjut, dan workflow operasional.",
        "features": ["WhatsApp AI Admin", "Kelola prospek", "Uji sebelum aktif"],
        "status": "Pilot",
        "status_class": "beta",
        "url": settings.business_url,
        "cta": "Buka Business Automation",
        "home_cta": "Pilih",
        "icon": "flow",
        "accent": "orange",
        "onboarding_title": "Apa yang ingin Anda otomatisasi?",
        "onboarding_text": "Ceritakan pekerjaan yang masih dilakukan manual. BotConnector akan membantu membuat alurnya.",
        "starter_choices": ["WhatsApp AI Admin", "Penerimaan prospek", "Booking", "Tindak lanjut", "Proses bisnis lainnya"],
        "menu": [
            menu("overview", "Dashboard", "Ringkasan Bisnis", "Lihat sistem bisnis yang sedang dibuat dan tahap penyelesaiannya."),
            menu("operations", "Operasional", "Business Operations", "Kelola profil bisnis, layanan, pelanggan, pipeline prospek, approval, booking, follow-up, dan audit log."),
            menu("chat", "WhatsApp AI Admin", "WhatsApp AI Admin", "Buat jawaban otomatis, pengumpulan lead, dan aturan pengalihan ke admin manusia."),
            menu("leads", "Prospek", "Prospek", "Buat formulir, penyaringan, dan tindak lanjut calon pelanggan."),
            menu("bookings", "Booking", "Booking", "Buat layanan, jadwal, konfirmasi, dan pengingat booking."),
            menu("followup", "Tindak lanjut", "Tindak lanjut", "Buat pesan dan jadwal tindak lanjut otomatis."),
            menu("workflows", "Alur kerja", "Alur kerja", "Ubah proses bisnis menjadi langkah yang dapat dijalankan otomatis."),
            menu("settings", "Pengaturan", "Pengaturan", "Sesuaikan kanal, admin, jam kerja, dan aturan automasi."),
        ],
        "cards": [
            {"label": "Percakapan AI", "value": "Belum diaktifkan"},
            {"label": "Prospek baru", "value": "Belum ada data"},
            {"label": "Tugas admin", "value": "Tidak ada"},
        ],
    },
    {
        "slug": "business_suite",
        "eyebrow": "BISNIS",
        "name": "Business Suite",
        "short_summary": "POS, inventory, restoran, finance, dan laporan yang tenant-safe.",
        "summary": "Kelola operasional bisnis Anda dalam ruang kerja yang terpisah dari bisnis lain.",
        "features": ["POS & inventory", "Restoran & KDS", "Finance & reports"],
        "status": "Tersedia",
        "status_class": "live",
        "url": "/bisnis/",
        "direct_url": "/bisnis/",
        "cta": "Buka Business Suite",
        "home_cta": "Pilih",
        "icon": "flow",
        "accent": "green",
        "onboarding_title": "Siapkan Business Suite",
        "onboarding_text": "Buat ruang bisnis pertama Anda.",
        "starter_choices": ["Retail", "Restoran", "Hybrid"],
        "menu": [],
        "cards": [],
    },
    {
        "slug": "personal",
        "eyebrow": "INDIVIDU",
        "name": "Personal Automation",
        "short_summary": "Membantu creator dan freelancer.",
        "summary": "Gunakan ruang kerja terpisah untuk menyiapkan konten, mengelola klien, proyek, invoice, revisi, dan pembayaran.",
        "features": ["Creator Assistant", "Freelancer Assistant", "Satu ruang kerja"],
        "status": "Pilot",
        "status_class": "beta",
        "url": "/personal",
        "cta": "Buka Personal Automation",
        "home_cta": "Pilih",
        "icon": "spark",
        "accent": "rose",
        "onboarding_title": "Bantuan personal apa yang Anda butuhkan?",
        "onboarding_text": "Pilih tujuan utama. BotConnector akan membuka ruang kerja yang sesuai tanpa mencampur menu bisnis, trading, atau lowongan kerja.",
        "starter_choices": ["Creator Assistant", "Freelancer Assistant", "Keduanya", "Belum yakin"],
        "menu": [
            menu("overview", "Dashboard", "Ringkasan Personal", "Lihat rancangan personal yang sedang dibuat dan langkah berikutnya."),
            menu("creator", "Creator Assistant", "Creator Assistant", "Buat ide, hook, script, caption, hashtag, dan kalender konten."),
            menu("freelancer", "Freelancer Assistant", "Freelancer Assistant", "Kelola calon klien, proposal, proyek, revisi, invoice, dan pembayaran."),
            menu("content-calendar", "Kalender Konten", "Kalender Konten", "Atur draft, review, jadwal, dan status publikasi konten."),
            menu("clients", "Klien & Proyek", "Klien & Proyek", "Susun pipeline calon klien, pekerjaan aktif, deadline, dan revisi."),
            menu("invoices", "Invoice", "Invoice & Pembayaran", "Siapkan invoice, jatuh tempo, pengingat, kuitansi, dan laporan pendapatan."),
            menu("settings", "Pengaturan", "Pengaturan", "Sesuaikan gaya konten, data jasa, notifikasi, dan batas penggunaan."),
        ],
        "cards": [
            {"label": "Draft konten", "value": "Belum ada"},
            {"label": "Proyek aktif", "value": "Belum ada"},
            {"label": "Invoice tertunda", "value": "Tidak ada"},
        ],
    },
    {
        "slug": "monitor",
        "eyebrow": "PEMANTAUAN",
        "name": "Monitor & Resolve",
        "short_summary": "Memantau sistem dan layanan.",
        "summary": "Ceritakan sistem yang penting. BotConnector membantu membuat pemantauan, notifikasi, dan langkah penanganan masalah.",
        "features": ["Tambah layanan", "Atur peringatan", "Siapkan penanganan"],
        "status": "Preview",
        "status_class": "soon",
        "url": settings.monitor_url,
        "cta": "Buka Monitor",
        "home_cta": "Pilih",
        "icon": "radar",
        "accent": "green",
        "onboarding_title": "Apa yang ingin Anda pantau?",
        "onboarding_text": "Tambahkan sistem pertama. BotConnector akan membantu menentukan pemeriksaan dan notifikasinya.",
        "starter_choices": ["Website", "Webhook", "VPS", "Agent", "Beberapa layanan sekaligus"],
        "menu": [
            menu("overview", "Status", "Status Layanan", "Lihat layanan yang sedang disiapkan dan kondisi pemantauannya."),
            menu("websites", "Website", "Website", "Buat pemeriksaan uptime, respons, dan sertifikat website."),
            menu("webhooks", "Webhook", "Webhook", "Buat pemeriksaan endpoint dan proses webhook."),
            menu("vps", "VPS", "VPS", "Buat pemantauan CPU, RAM, disk, layanan, dan log penting."),
            menu("agents", "Agent", "Agent", "Buat pemeriksaan agent dan koneksi yang diperlukan."),
            menu("incidents", "Insiden", "Insiden", "Susun notifikasi dan langkah penanganan saat terjadi masalah."),
        ],
        "cards": [
            {"label": "Layanan dipantau", "value": "Belum ada"},
            {"label": "Peringatan aktif", "value": "Belum ada"},
            {"label": "Insiden", "value": "Tidak ada"},
        ],
    },
]

PRODUCT_MAP = {product["slug"]: product for product in PRODUCTS}

# Canonical operational products
LIVE_PRODUCT_SLUGS = {"business_suite", "connect", "webhook", "drive"}
STAGING_PRODUCT_SLUGS = set(PRODUCT_MAP) - LIVE_PRODUCT_SLUGS

for staging_slug in STAGING_PRODUCT_SLUGS:
    staging_product = PRODUCT_MAP[staging_slug]
    staging_product.update(
        {
            "status": "STAGING",
            "status_class": "soon",
            "home_cta": "Lihat status",
            "cta": "Lihat status staging",
            "direct_url": "/staging-closed",
            "staging": True,
        }
    )



# ============================================================
# BOTCONNECTOR_PUBLIC_PRODUCT_REGISTRY_V1
#
# Public marketing/application catalog only.
# Legacy PRODUCTS / PRODUCT_MAP remain untouched for
# entitlement, account, onboarding, and compatibility.
# ============================================================

from app.public_products import (
    PUBLIC_GROUPS,
    PUBLIC_PRODUCT_MAP,
    PUBLIC_PRODUCTS,
)

HOME_PRODUCTS = PUBLIC_PRODUCTS
HOME_PRODUCT_MAP = PUBLIC_PRODUCT_MAP
HOME_GROUPS = PUBLIC_GROUPS


@app.middleware("http")
async def block_retired_product_routes(request: Request, call_next):
    """Keep retired implementations unreachable during the clean rebuild."""
    parts = [part for part in request.url.path.split("/") if part]
    retired = False
    if parts and parts[0] in {"business", "personal", "monitor", "smartbiz"}:
        retired = True
    elif (
        len(parts) >= 2
        and parts[0] in {"choose", "onboarding", "app"}
        and parts[1] in STAGING_PRODUCT_SLUGS
    ):
        retired = True

    if retired:
        if request.method in {"GET", "HEAD"}:
            return RedirectResponse("/staging-closed", status_code=303)
        return Response(status_code=404)
    return await call_next(request)


def guide(title: str, text: str, question: str, placeholder: str, choices: list[str], deliverables: list[str]) -> dict[str, Any]:
    return {
        "title": title,
        "text": text,
        "question": question,
        "placeholder": placeholder,
        "choices": choices,
        "deliverables": deliverables,
    }


GUIDES: dict[str, dict[str, dict[str, Any]]] = {
    "webhook": {
        "overview": guide("Bantu siapkan koneksi saya", "Mulai dari tujuan koneksi. Kami bantu menyusun konfigurasi sampai siap diuji.", "Apa yang ingin Anda hubungkan?", "Contoh: alert TradingView XAUUSD dikirim ke MT5 Exness dengan aturan lot tertentu.", ["TradingView ke MetaTrader", "TradingView ke Binance", "Webhook ke aplikasi lain", "Belum yakin"], ["Rancangan koneksi", "Daftar konfigurasi", "Skenario pengujian", "Langkah aktivasi"]),
        "tradingview": guide("Bantu buat alert TradingView", "Jelaskan strategi dan format pesan yang dibutuhkan.", "Alert seperti apa yang ingin dibuat?", "Contoh: sinyal BUY dan SELL dengan simbol, entry, SL, TP, dan ID strategi.", ["Alert entry", "Alert exit", "Alert lengkap", "Perbaiki alert lama"], ["Format alert", "Payload webhook", "Contoh pesan", "Checklist pengujian"]),
        "metatrader": guide("Bantu hubungkan MetaTrader", "Kami bantu memetakan simbol, akun, dan aturan order.", "Bagaimana order seharusnya dijalankan?", "Contoh: XAUUSD, lot 0.01, satu posisi per sinyal, komentar BotConnector.", ["MT5 Windows", "MT5 VPS", "Multi-akun", "Belum yakin"], ["Pemetaan simbol", "Aturan order", "Konfigurasi executor", "Uji order aman"]),
        "connections": guide("Bantu susun koneksi", "Tentukan sumber, tujuan, dan aturan pengiriman.", "Jelaskan alur koneksi yang diinginkan.", "Contoh: TradingView → BotConnector → MT5 dan Telegram.", ["Satu sumber satu tujuan", "Satu sumber banyak tujuan", "Banyak sumber", "Koneksi khusus"], ["Diagram alur", "Konfigurasi endpoint", "Aturan routing", "Rencana fallback"]),
        "activity": guide("Bantu periksa aktivitas", "Kami bantu mencari sumber pesan gagal atau terlambat.", "Masalah apa yang sedang terjadi?", "Tempel ringkasan error atau jelaskan kapan pesan gagal.", ["Pesan tidak masuk", "Order gagal", "Pesan terlambat", "Audit umum"], ["Ringkasan temuan", "Urutan pemeriksaan", "Saran perbaikan", "Rencana verifikasi"]),
        "settings": guide("Bantu atur koneksi", "Sesuaikan keamanan, notifikasi, dan perilaku koneksi.", "Pengaturan apa yang ingin diubah?", "Contoh: kirim notifikasi Telegram hanya saat order gagal.", ["Keamanan", "Notifikasi", "Retry", "Aturan order"], ["Rancangan pengaturan", "Nilai yang disarankan", "Dampak perubahan", "Checklist penerapan"]),
    },
    "langkah": {
        "overview": guide("Bantu siapkan pencarian kerja saya", "Ceritakan tujuan kerja Anda. LANGKAH membantu menentukan urutan yang paling tepat.", "Apa yang ingin Anda capai?", "Contoh: mencari pekerjaan administrasi di Bandung dalam 2 bulan.", ["Cari pekerjaan pertama", "Pindah pekerjaan", "Kembali bekerja", "Belum yakin"], ["Rencana pencarian kerja", "Prioritas dokumen", "Target mingguan", "Langkah berikutnya"]),
        "jobs": guide("Bantu carikan lowongan", "Kami bantu menentukan kata kunci, lokasi, dan sumber lowongan yang relevan.", "Pekerjaan seperti apa yang Anda cari?", "Contoh: staf administrasi, pengalaman 2 tahun, Bandung atau remote.", ["Full-time", "Part-time", "Magang", "Remote"], ["Kriteria pencarian", "Daftar sumber", "Aturan penyaringan", "Daftar lowongan pilihan"]),
        "match": guide("Bantu periksa kecocokan", "Bandingkan pengalaman Anda dengan lowongan yang dipilih.", "Tempel ringkasan lowongan atau persyaratannya.", "Contoh: membutuhkan Excel, administrasi dokumen, dan komunikasi pelanggan.", ["Cocokkan dengan profil", "Cocokkan dengan CV", "Cari kekurangan", "Siapkan perbaikan"], ["Nilai kecocokan", "Kekuatan utama", "Kekurangan", "Saran perbaikan"]),
        "cv": guide("Bantu buat CV saya", "Kami bantu membuat CV dari awal atau menyesuaikannya untuk lowongan tertentu.", "Ceritakan pengalaman, pendidikan, dan pekerjaan yang dituju.", "Contoh: lulusan SMK, pernah bekerja sebagai admin toko 2 tahun, mahir Excel dan WhatsApp Business.", ["Buat dari awal", "Perbaiki CV lama", "Sesuaikan untuk lowongan", "Buat versi ATS"], ["Ringkasan profesional", "Susunan pengalaman", "Daftar keahlian", "CV siap PDF dan DOCX"]),
        "pack": guide("Bantu siapkan berkas lamaran", "Kami bantu membuat surat, email, dan daftar dokumen yang dibutuhkan.", "Untuk perusahaan dan posisi apa berkas ini dibuat?", "Contoh: Admin Operasional di PT Contoh, melamar melalui email.", ["Surat lamaran", "Cover letter", "Email lamaran", "Paket lengkap"], ["Surat lamaran", "Email pengantar", "Jawaban formulir", "Checklist dokumen"]),
        "applications": guide("Bantu kelola progres lamaran", "Kami bantu menyusun status, pengingat, dan tindak lanjut.", "Lamaran apa yang sedang diproses?", "Contoh: sudah melamar ke 5 perusahaan dan menunggu panggilan.", ["Mulai pencatatan", "Buat pengingat", "Tindak lanjut", "Rapikan progres"], ["Daftar lamaran", "Status setiap lamaran", "Jadwal tindak lanjut", "Prioritas berikutnya"]),
        "interview": guide("Bantu latihan wawancara", "Kami bantu membuat pertanyaan, menilai jawaban, dan memperbaikinya.", "Posisi apa yang akan diwawancarai?", "Contoh: Customer Service, wawancara HR dan user minggu depan.", ["Wawancara HR", "Wawancara user", "Pertanyaan teknis", "Simulasi lengkap"], ["Daftar pertanyaan", "Contoh jawaban", "Simulasi", "Catatan perbaikan"]),
    },
    "business": {
        "operations": guide(
            "Bangun pusat operasional bisnis",
            "Simpan profil bisnis dan kelola prospek, layanan, approval, booking, serta follow-up dalam satu ruang kerja.",
            "Ceritakan profil bisnis dan aturan operasional utama.",
            "Contoh: katering di Bandung, buka 08.00–20.00, harga dan ketersediaan harus disetujui admin, gaya balasan ramah dan ringkas.",
            [
                "Katalog layanan dan jam operasional",
                "Database pelanggan dan prospek",
                "Pipeline dan approval admin",
                "Booking dan follow-up simulasi",
            ],
            [
                "Profil bisnis terstruktur",
                "Database pelanggan dan prospek",
                "Pipeline operasional",
                "Approval queue",
                "Booking simulator",
                "Follow-up terjadwal",
                "Dashboard dan audit log",
            ],
        ),
        "overview": guide("Bantu buat sistem bisnis saya", "Ceritakan pekerjaan manual yang ingin dipermudah.", "Proses apa yang ingin Anda otomatisasi?", "Contoh: pertanyaan pelanggan masuk dari WhatsApp lalu dicatat dan ditindaklanjuti admin.", ["WhatsApp AI Admin", "Prospek", "Booking", "Tindak lanjut", "Proses lainnya"], ["Peta proses", "Rancangan automasi", "Pembagian tugas admin", "Rencana penerapan"]),
        "chat": guide("Bantu siapkan WhatsApp AI Admin", "Kami bantu membuat sapaan, FAQ, basis pengetahuan, pengumpulan lead, dan alih ke admin manusia.", "Pelanggan biasanya menanyakan apa dan kapan harus dialihkan ke admin?", "Contoh: harga, katalog, jadwal, lokasi, status pesanan, keluhan, dan permintaan bantuan teknis.", ["FAQ dan katalog", "Lead capture", "Alih ke admin", "Laporan percakapan"], ["Basis pengetahuan", "Alih ke admin", "Data yang dikumpulkan", "Alur percakapan", "Laporan harian"]),
        "leads": guide("Bantu buat alur prospek", "Kami bantu mengumpulkan, menyaring, dan membagikan calon pelanggan.", "Prospek seperti apa yang ingin dikumpulkan?", "Contoh: calon pembeli rumah dengan budget dan lokasi tertentu.", ["Formulir website", "WhatsApp", "Iklan", "Sumber lainnya"], ["Formulir prospek", "Pertanyaan penyaringan", "Kategori dan skor", "Aturan tindak lanjut"]),
        "bookings": guide("Bantu buat sistem booking", "Kami bantu membuat layanan, jadwal, konfirmasi, dan pengingat.", "Booking untuk layanan apa?", "Contoh: konsultasi 30 menit, Senin–Sabtu, maksimal 8 booking per hari.", ["Konsultasi", "Jasa lapangan", "Klinik atau salon", "Layanan lainnya"], ["Daftar layanan", "Aturan jadwal", "Formulir booking", "Pesan konfirmasi dan pengingat"]),
        "followup": guide("Bantu buat tindak lanjut", "Kami bantu menyusun pesan dan waktu pengiriman otomatis.", "Siapa yang perlu ditindaklanjuti dan kapan?", "Contoh: prospek yang belum membalas setelah 1 hari dan 3 hari.", ["Prospek", "Pembayaran", "Setelah layanan", "Permintaan ulasan"], ["Urutan pesan", "Jadwal pengiriman", "Kondisi berhenti", "Aturan alih ke admin"]),
        "workflows": guide("Bantu buat alur kerja", "Jelaskan proses dengan bahasa sederhana. Kami bantu mengubahnya menjadi workflow.", "Bagaimana proses berjalan dari awal sampai selesai?", "Contoh: formulir masuk → simpan data → beri tahu admin → kirim pesan pelanggan.", ["Satu alur sederhana", "Beberapa cabang", "Persetujuan admin", "Integrasi aplikasi"], ["Diagram workflow", "Trigger dan aksi", "Kondisi dan cabang", "Skenario pengujian"]),
        "settings": guide("Bantu atur automasi", "Sesuaikan kanal, jam kerja, admin, dan batas automasi.", "Pengaturan apa yang dibutuhkan?", "Contoh: bot aktif 24 jam, tetapi alih ke admin pukul 08.00–20.00.", ["Kanal", "Jam operasional", "Admin", "Notifikasi"], ["Rancangan pengaturan", "Hak akses", "Aturan notifikasi", "Checklist penerapan"]),
    },
    "personal": {
        "overview": guide("Bantu siapkan ruang personal saya", "Pilih bantuan creator, freelancer, atau keduanya.", "Apa tujuan utama Anda?", "Contoh: membuat konten affiliate setiap minggu sekaligus mengelola klien desain.", ["Creator Assistant", "Freelancer Assistant", "Keduanya", "Belum yakin"], ["Peta kebutuhan", "Ruang kerja", "Prioritas penerapan", "Rencana pengujian"]),
        "creator": guide("Bantu buat workflow konten", "Kami bantu mengubah produk, ide, foto, atau video menjadi rancangan konten.", "Konten apa yang ingin dibuat?", "Contoh: 20 ide TikTok untuk produk skincare dengan gaya edukatif dan call to action yang aman.", ["Ide dan hook", "Script video", "Caption dan hashtag", "Repurposing"], ["Daftar ide", "Hook dan script", "Caption dan CTA", "Kalender konten"]),
        "freelancer": guide("Bantu kelola pekerjaan freelance", "Kami bantu menyusun alur calon klien sampai proyek selesai dan dibayar.", "Bagaimana proses kerja freelance Anda sekarang?", "Contoh: calon klien masuk dari WhatsApp, dikirim quotation, proyek dibuat, lalu invoice diingatkan.", ["Calon klien", "Proposal dan quotation", "Proyek dan revisi", "Invoice dan pembayaran"], ["Pipeline klien", "Template penawaran", "Struktur proyek", "Alur invoice"]),
        "content-calendar": guide("Bantu susun kalender konten", "Kami bantu mengatur draft, review, jadwal, platform, dan status publikasi.", "Seberapa sering dan di mana Anda ingin posting?", "Contoh: TikTok 5 kali per minggu dan Instagram 3 kali per minggu.", ["TikTok", "Instagram", "YouTube", "Beberapa platform"], ["Kalender mingguan", "Status konten", "Pengingat", "Daftar materi"]),
        "clients": guide("Bantu susun klien dan proyek", "Kami bantu mencatat prospek, kebutuhan, deadline, milestone, file, dan revisi.", "Jenis jasa dan proyek apa yang Anda kerjakan?", "Contoh: desain website dengan dua milestone dan maksimal tiga revisi.", ["Prospek", "Proyek aktif", "Deadline", "Revisi"], ["Pipeline klien", "Daftar tugas", "Milestone", "Aturan revisi"]),
        "invoices": guide("Bantu siapkan invoice dan pembayaran", "Kami bantu menyusun nomor invoice, item, jatuh tempo, pengingat, dan kuitansi.", "Bagaimana pembayaran biasanya dilakukan?", "Contoh: DP 50%, pelunasan setelah selesai, reminder H-2 dan H+1.", ["Invoice satu kali", "DP dan pelunasan", "Pembayaran bertahap", "Pengingat"], ["Template invoice", "Jadwal pembayaran", "Pesan pengingat", "Laporan status"]),
        "settings": guide("Bantu atur Personal Automation", "Sesuaikan brand voice, data jasa, notifikasi, dan preferensi penggunaan.", "Pengaturan apa yang perlu disimpan?", "Contoh: gaya bahasa santai, mata uang rupiah, reminder Telegram, dan jam kerja Senin–Jumat.", ["Gaya konten", "Data jasa", "Notifikasi", "Batas penggunaan"], ["Profil pengaturan", "Aturan notifikasi", "Data default", "Checklist penerapan"]),
    },
    "monitor": {
        "overview": guide("Bantu siapkan pemantauan", "Ceritakan layanan penting dan jenis gangguan yang harus diketahui.", "Apa yang ingin dipantau?", "Contoh: website, webhook TradingView, dan VPS Ubuntu.", ["Website", "Webhook", "VPS", "Agent", "Semua layanan"], ["Daftar layanan", "Aturan pemeriksaan", "Tujuan notifikasi", "Langkah penanganan"]),
        "websites": guide("Bantu pantau website", "Kami bantu menentukan pemeriksaan uptime, respons, dan sertifikat.", "Website mana dan gangguan apa yang penting?", "Contoh: botconnector.id harus merespons 200 dalam 5 detik.", ["Uptime", "Kecepatan", "SSL", "Konten halaman"], ["Endpoint pemeriksaan", "Interval", "Batas peringatan", "Pesan notifikasi"]),
        "webhooks": guide("Bantu pantau webhook", "Kami bantu memeriksa endpoint, respons, dan kegagalan proses.", "Webhook apa yang ingin dipantau?", "Contoh: endpoint TradingView harus menerima dan memproses pesan dalam 10 detik.", ["Ketersediaan endpoint", "Validasi respons", "Keterlambatan", "Kegagalan order"], ["Health check", "Aturan log", "Batas peringatan", "Langkah eskalasi"]),
        "vps": guide("Bantu pantau VPS", "Kami bantu memilih metrik, layanan, dan batas peringatan.", "Masalah VPS apa yang ingin dicegah?", "Contoh: disk di atas 80%, RAM tinggi, container mati, atau service gagal.", ["CPU dan RAM", "Disk", "Docker", "Systemd", "Semua"], ["Daftar metrik", "Batas peringatan", "Pemeriksaan layanan", "Rencana pemulihan"]),
        "agents": guide("Bantu pantau Agent", "Kami bantu memeriksa koneksi, heartbeat, dan versi Agent.", "Agent apa yang harus selalu terhubung?", "Contoh: Agent Windows untuk executor MT5 pada komputer kantor.", ["Agent Windows", "Agent Linux", "Beberapa Agent", "Belum yakin"], ["Heartbeat", "Aturan offline", "Notifikasi", "Langkah pemulihan"]),
        "incidents": guide("Bantu siapkan penanganan insiden", "Kami bantu menentukan siapa diberi tahu dan apa yang dilakukan lebih dulu.", "Masalah seperti apa yang perlu ditangani?", "Contoh: webhook gagal 3 kali berturut-turut atau container mati.", ["Notifikasi saja", "Panduan perbaikan", "Perbaikan otomatis terbatas", "Eskalasi admin"], ["Klasifikasi insiden", "Urutan tindakan", "Pesan notifikasi", "Catatan penyelesaian"]),
    },
}



BUSINESS_PUBLIC: dict[str, Any] = {
    "name": "Business Automation",
    "eyebrow": "UNTUK BISNIS",
    "headline": "Balas pelanggan lebih cepat tanpa kehilangan kendali.",
    "lead": (
        "WhatsApp AI Admin membantu membaca pesan pelanggan, "
        "mengelompokkan kebutuhan, membuat draft balasan, menilai "
        "prospek, dan meneruskan percakapan penting ke admin manusia."
    ),
    "features": [
        "Klasifikasi pertanyaan, prospek, booking, keluhan, dan pembayaran",
        "Draft balasan berdasarkan profil serta aturan bisnis",
        "Lead score dan informasi yang masih perlu ditanyakan",
        "Deteksi pesan prioritas dan aturan eskalasi ke admin",
        "Riwayat simulasi tersimpan pada akun dan PostgreSQL",
        "Uji seluruh alur sebelum menghubungkan WhatsApp nyata",
    ],
    "workflow": [
        {
            "title": "Isi profil bisnis",
            "text": (
                "Masukkan nama usaha, layanan, jam operasional, "
                "gaya bahasa, dan aturan pengalihan ke admin."
            ),
        },
        {
            "title": "Masukkan pesan simulasi",
            "text": (
                "Gunakan contoh pesan pelanggan tanpa menghubungkan "
                "nomor WhatsApp."
            ),
        },
        {
            "title": "Periksa hasil AI",
            "text": (
                "Lihat kategori, prioritas, lead score, data yang "
                "terdeteksi, draft balasan, dan alasan eskalasi."
            ),
        },
        {
            "title": "Perbaiki aturan",
            "text": (
                "Ulangi pengujian sampai balasan dan eskalasi sesuai "
                "cara kerja bisnis."
            ),
        },
    ],
    "example_input": (
        "Pelanggan: Halo, saya butuh katering untuk 80 orang Sabtu "
        "depan. Bisa kirim daftar paket dan apakah masih tersedia?"
    ),
    "example_output": [
        "Kategori: lead dan booking",
        "Prioritas: tinggi",
        "Lead score serta data jumlah tamu dan tanggal",
        "Pertanyaan yang masih perlu dikonfirmasi",
        "Draft balasan yang siap diperiksa admin",
    ],
    "safety": (
        "Candidate ini tidak mengirim pesan WhatsApp, tidak membuat "
        "booking, tidak menerima pembayaran, dan tidak menjanjikan "
        "harga atau stok. Semua hasil hanya simulasi dan harus diperiksa."
    ),
}


PERSONAL_ASSISTANTS: dict[str, dict[str, Any]] = {
    "creator": {
        "slug": "creator",
        "name": "Creator Assistant",
        "eyebrow": "UNTUK KONTEN",
        "headline": "Dari satu ide menjadi konten yang siap diperiksa.",
        "lead": (
            "Creator Assistant membantu mengubah produk, foto, video, "
            "atau materi menjadi ide, hook, script, caption, dan "
            "kalender konten."
        ),
        "accent": "creator",
        "icon": "✦",
        "features": [
            "Ide dan sudut konten berdasarkan niche atau produk",
            "Hook dan script untuk video pendek",
            "Caption, call to action, judul, dan hashtag",
            "Repurposing untuk beberapa platform",
            "Kalender, status draft, review, dan jadwal",
            "Pengelolaan produk dan link affiliate",
        ],
        "workflow": [
            {
                "title": "Masukkan bahan",
                "text": (
                    "Tambahkan produk, ide, foto, video, platform, "
                    "target audiens, dan gaya bahasa."
                ),
            },
            {
                "title": "Buat rancangan",
                "text": (
                    "Sistem menyiapkan variasi ide, hook, script, "
                    "caption, CTA, dan hashtag."
                ),
            },
            {
                "title": "Periksa dan revisi",
                "text": (
                    "Pilih hasil yang sesuai, perbaiki draft, dan "
                    "simpan versi yang disetujui."
                ),
            },
            {
                "title": "Masukkan ke kalender",
                "text": (
                    "Atur platform, tanggal, status, dan pengingat "
                    "tanpa memublikasikan otomatis."
                ),
            },
        ],
        "example_title": "Contoh: produk skincare untuk TikTok",
        "example_input": (
            "Serum wajah, target perempuan 20–35 tahun, gaya edukatif, "
            "lima konten per minggu."
        ),
        "example_output": [
            "12 ide konten dengan sudut berbeda",
            "Hook tiga detik untuk setiap ide",
            "Script video pendek dan urutan visual",
            "Caption, CTA, serta hashtag",
            "Kalender konten satu minggu",
        ],
        "safety": (
            "Creator Assistant tidak menjanjikan konten viral, tidak "
            "membuat testimoni palsu, dan tidak memublikasikan konten "
            "tanpa pemeriksaan pengguna."
        ),
        "section": "creator",
        "goal": "Creator Assistant",
    },
    "freelancer": {
        "slug": "freelancer",
        "name": "Freelancer Assistant",
        "eyebrow": "UNTUK JASA",
        "headline": "Kelola klien, proyek, revisi, dan pembayaran.",
        "lead": (
            "Freelancer Assistant membantu mengatur proses dari calon "
            "klien hingga proyek selesai, invoice dikirim, dan "
            "pembayaran dipantau."
        ),
        "accent": "freelancer",
        "icon": "▣",
        "features": [
            "Pipeline calon klien dan jadwal follow-up",
            "Proposal, quotation, dan ruang lingkup kerja",
            "Milestone, tugas, deadline, file, dan revisi",
            "Invoice PDF dan status pembayaran",
            "Pengingat jatuh tempo dan kuitansi",
            "Laporan pendapatan dan bahan portfolio",
        ],
        "workflow": [
            {
                "title": "Catat calon klien",
                "text": (
                    "Simpan kebutuhan, anggaran, deadline, sumber lead, "
                    "dan status prospek."
                ),
            },
            {
                "title": "Siapkan penawaran",
                "text": (
                    "Buat quotation, ruang lingkup, milestone, ketentuan "
                    "revisi, dan pembayaran."
                ),
            },
            {
                "title": "Kelola pekerjaan",
                "text": (
                    "Pantau tugas, file, progres, waktu kerja, perubahan, "
                    "dan komunikasi penting."
                ),
            },
            {
                "title": "Pantau pembayaran",
                "text": (
                    "Buat invoice, catat jatuh tempo, simpan status, "
                    "dan siapkan pesan pengingat."
                ),
            },
        ],
        "example_title": "Contoh: proyek desain website",
        "example_input": (
            "Klien membutuhkan website perusahaan, dua milestone, "
            "maksimal tiga revisi, DP 50%."
        ),
        "example_output": [
            "Ringkasan kebutuhan dan status prospek",
            "Quotation dan ruang lingkup pekerjaan",
            "Daftar milestone, tugas, serta deadline",
            "Catatan revisi dan file proyek",
            "Invoice DP dan pelunasan beserta pengingat",
        ],
        "safety": (
            "Template dokumen harus diperiksa pengguna. Freelancer "
            "Assistant tidak memberikan nasihat hukum final, tidak "
            "mengirim invoice palsu, dan tidak menjamin klien membayar."
        ),
        "section": "freelancer",
        "goal": "Freelancer Assistant",
    },
}


def get_personal_assistant(assistant_slug: str) -> dict[str, Any]:
    assistant = PERSONAL_ASSISTANTS.get(assistant_slug)
    if not assistant:
        raise HTTPException(
            status_code=404,
            detail="Asisten personal tidak ditemukan",
        )
    return assistant


def remember_personal_assistant(
    request: Request,
    assistant_slug: str | None,
) -> None:
    if assistant_slug in PERSONAL_ASSISTANTS:
        request.session["selected_assistant"] = assistant_slug
        request.session["selected_product"] = "personal"


def selected_personal_goal(request: Request) -> str | None:
    assistant_slug = request.session.get("selected_assistant")
    assistant = PERSONAL_ASSISTANTS.get(str(assistant_slug))
    return assistant["goal"] if assistant else None


def personal_destination(request: Request, assistant_slug: str) -> str:
    assistant = get_personal_assistant(assistant_slug)
    remember_personal_assistant(request, assistant_slug)
    if not current_user(request):
        return (
            "/login?product=personal"
            f"&assistant={assistant_slug}"
        )
    if "personal" not in active_products(request):
        return f"/onboarding/personal?assistant={assistant_slug}"
    return f"/app/personal/{assistant['section']}"



def get_product(slug: str) -> dict[str, Any]:
    product = PRODUCT_MAP.get(slug)
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return product


def get_section(product: dict[str, Any], section_slug: str) -> dict[str, str]:
    section = next((item for item in product["menu"] if item["slug"] == section_slug), None)
    if not section:
        raise HTTPException(status_code=404, detail="Menu produk tidak ditemukan")
    return section


def get_guide(slug: str, section_slug: str) -> dict[str, Any]:
    try:
        return GUIDES[slug][section_slug]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Panduan belum tersedia") from exc


def current_user(request: Request) -> dict[str, Any] | None:
    if settings.core_integration_enabled:
        return core_current_user(request, settings)
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def active_products(request: Request) -> list[str]:
    if settings.core_integration_enabled:
        return core_active_products(request, settings)
    values = request.session.get("product_access", [])
    if not isinstance(values, list):
        return []
    return [slug for slug in values if slug in PRODUCT_MAP]


def projects(request: Request) -> dict[str, dict[str, Any]]:
    values = request.session.get("projects", {})
    return values if isinstance(values, dict) else {}


def project_key(slug: str, section_slug: str) -> str:
    return f"{slug}:{section_slug}"


def core_project_type(slug: str, section_slug: str) -> str:
    return f"{slug}.{section_slug}"


def personal_ai_enabled(section_slug: str) -> bool:
    if section_slug == "creator":
        return settings.creator_ai_enabled
    if section_slug == "freelancer":
        return settings.freelancer_ai_enabled
    return False


def personal_ai_output_key(section_slug: str) -> str:
    if section_slug == "creator":
        return "creator_plan"
    if section_slug == "freelancer":
        return "freelancer_plan"
    raise ValueError("Asisten AI personal tidak dikenal.")


def generate_personal_plan(
    section_slug: str,
    *,
    need: str,
    choice: str,
    revision: str = "",
    current_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if section_slug == "creator":
        return generate_creator_plan(
            settings,
            need=need,
            choice=choice,
            revision=revision,
            current_plan=current_plan,
        )
    if section_slug == "freelancer":
        return generate_freelancer_plan(
            settings,
            need=need,
            choice=choice,
            revision=revision,
            current_plan=current_plan,
        )
    raise PersonalAIError("Asisten AI personal tidak dikenal.")


def personal_ai_success_message(
    section_slug: str,
    *,
    revision: bool,
) -> str:
    if section_slug == "creator":
        return (
            "Creator Assistant sudah memperbarui rancangan konten."
            if revision
            else "Creator Assistant sudah membuat rancangan konten."
        )
    return (
        "Freelancer Assistant sudah memperbarui paket kerja."
        if revision
        else (
            "Freelancer Assistant sudah membuat proposal, scope, "
            "milestone, dan template komunikasi."
        )
    )


BUSINESS_PIPELINE_STATUSES = {
    "new",
    "contacted",
    "follow_up",
    "booked",
    "completed",
    "lost",
}
BUSINESS_APPROVAL_PENDING_STATUSES = {
    "pending",
    "pending_admin",
    "pending_manager",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_sla_rules() -> list[dict[str, Any]]:
    return [
        {
            "priority": "urgent",
            "target_minutes": 30,
            "approval_level": 2,
            "label": "30 menit",
        },
        {
            "priority": "high",
            "target_minutes": 120,
            "approval_level": 2,
            "label": "2 jam",
        },
        {
            "priority": "medium",
            "target_minutes": 480,
            "approval_level": 1,
            "label": "8 jam",
        },
        {
            "priority": "low",
            "target_minutes": 1440,
            "approval_level": 1,
            "label": "24 jam",
        },
    ]


def default_business_operations_state() -> dict[str, Any]:
    return {
        "mode": "simulation",
        "live_whatsapp_connected": False,
        "live_message_sending": False,
        "automatic_booking": False,
        "automatic_followup": False,
        "profile": {},
        "services": [],
        "customers": [],
        "leads": [],
        "bookings": [],
        "approvals": [],
        "followups": [],
        "reply_templates": [],
        "sla_rules": default_sla_rules(),
        "audit_log": [],
        "integrations": {
            "whatsapp_simulator_sync": True,
            "live_whatsapp_connected": False,
            "scheduler_connected": False,
        },
    }


def parse_utc_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def customer_identity_key(name: Any, contact: Any) -> str:
    contact_key = normalize_identity(contact)
    if contact_key:
        return f"contact:{contact_key}"
    name_key = normalize_identity(name)
    return f"name:{name_key or 'unknown'}"


def sla_rule_for(
    state: dict[str, Any],
    priority: str,
) -> dict[str, Any]:
    rules = state.get("sla_rules")
    if not isinstance(rules, list):
        rules = default_sla_rules()
    for item in rules:
        if (
            isinstance(item, dict)
            and item.get("priority") == priority
        ):
            return item
    return next(
        item for item in default_sla_rules()
        if item["priority"] == "medium"
    )


def compute_sla_due_at(
    state: dict[str, Any],
    priority: str,
    *,
    created_at: str | None = None,
) -> str:
    rule = sla_rule_for(state, priority)
    try:
        target_minutes = max(
            1,
            int(rule.get("target_minutes", 480)),
        )
    except (TypeError, ValueError):
        target_minutes = 480
    start = parse_utc_iso(created_at) or datetime.now(timezone.utc)
    return (start + timedelta(minutes=target_minutes)).isoformat()


def normalize_approval(item: dict[str, Any]) -> dict[str, Any]:
    approval = dict(item)
    status = str(approval.get("status") or "pending_admin")
    if status == "pending":
        status = "pending_admin"
    approval["status"] = status
    try:
        required_level = int(approval.get("required_level", 1))
    except (TypeError, ValueError):
        required_level = 1
    approval["required_level"] = 2 if required_level >= 2 else 1
    approval["current_level"] = int(
        approval.get("current_level", 0) or 0
    )
    approval.setdefault(
        "required_role",
        "manager"
        if approval["required_level"] == 2
        else "admin",
    )
    approval.setdefault("delivery_status", "not_sent")
    approval.setdefault("review_history", [])
    return approval


def build_admin_tasks(
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    for item in state.get("approvals", []):
        if not isinstance(item, dict):
            continue
        approval = normalize_approval(item)
        if approval["status"] not in BUSINESS_APPROVAL_PENDING_STATUSES:
            continue
        tasks.append({
            "id": f"task-approval-{approval.get('id', '')}",
            "type": "approval",
            "priority": (
                "high"
                if approval.get("required_level") == 2
                else "medium"
            ),
            "title": (
                f"Review draft untuk "
                f"{approval.get('lead_name', 'prospek')}"
            ),
            "detail": approval.get("status", "pending_admin"),
            "due_at": approval.get("sla_due_at", ""),
            "status": "open",
        })

    for lead in state.get("leads", []):
        if not isinstance(lead, dict):
            continue
        if lead.get("status") not in {"new", "follow_up"}:
            continue
        tasks.append({
            "id": f"task-lead-{lead.get('id', '')}",
            "type": "lead_action",
            "priority": lead.get("priority", "medium"),
            "title": f"Tindak lanjuti {lead.get('name', 'prospek')}",
            "detail": lead.get("next_action") or (
                "Periksa kebutuhan dan tentukan tindakan berikutnya."
            ),
            "due_at": lead.get("sla_due_at", ""),
            "status": "open",
        })

    for booking in state.get("bookings", []):
        if not isinstance(booking, dict):
            continue
        if booking.get("status") != "tentative":
            continue
        tasks.append({
            "id": f"task-booking-{booking.get('id', '')}",
            "type": "booking_review",
            "priority": "medium",
            "title": (
                f"Periksa booking "
                f"{booking.get('customer_name', '')}"
            ),
            "detail": (
                f"{booking.get('service_name', '')} · "
                f"{booking.get('schedule_text', '')}"
            ),
            "due_at": "",
            "status": "open",
        })

    for followup in state.get("followups", []):
        if not isinstance(followup, dict):
            continue
        if followup.get("status") != "planned_not_sent":
            continue
        tasks.append({
            "id": f"task-followup-{followup.get('id', '')}",
            "type": "followup_plan",
            "priority": "medium",
            "title": (
                f"Review follow-up "
                f"{followup.get('target_name', '')}"
            ),
            "detail": followup.get("due_text", ""),
            "due_at": "",
            "status": "open",
        })

    priority_order = {
        "urgent": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    tasks.sort(
        key=lambda item: (
            priority_order.get(
                str(item.get("priority", "medium")),
                2,
            ),
            str(item.get("due_at", "")),
            str(item.get("title", "")),
        )
    )
    return tasks


def normalize_business_operations_state(
    raw: dict[str, Any] | None,
) -> dict[str, Any]:
    state = default_business_operations_state()
    if isinstance(raw, dict):
        for key in state:
            if key in raw:
                state[key] = raw[key]

    if not isinstance(state["profile"], dict):
        state["profile"] = {}
    if not isinstance(state["integrations"], dict):
        state["integrations"] = {}
    state["integrations"].update({
        "whatsapp_simulator_sync": True,
        "live_whatsapp_connected": False,
        "scheduler_connected": False,
    })

    list_keys = (
        "services",
        "customers",
        "leads",
        "bookings",
        "approvals",
        "followups",
        "reply_templates",
        "sla_rules",
        "audit_log",
    )
    for key in list_keys:
        if not isinstance(state[key], list):
            state[key] = []

    if not state["sla_rules"]:
        state["sla_rules"] = default_sla_rules()

    state["customers"] = [
        item for item in state["customers"]
        if isinstance(item, dict)
    ]
    state["leads"] = [
        item for item in state["leads"]
        if isinstance(item, dict)
    ]
    state["approvals"] = [
        normalize_approval(item)
        for item in state["approvals"]
        if isinstance(item, dict)
    ]
    state["bookings"] = [
        item for item in state["bookings"]
        if isinstance(item, dict)
    ]
    state["followups"] = [
        item for item in state["followups"]
        if isinstance(item, dict)
    ]
    state["reply_templates"] = [
        item for item in state["reply_templates"]
        if isinstance(item, dict)
    ]
    state["sla_rules"] = [
        item for item in state["sla_rules"]
        if isinstance(item, dict)
    ]

    now = datetime.now(timezone.utc)
    sla_breached = 0
    for lead in state["leads"]:
        due = parse_utc_iso(lead.get("sla_due_at"))
        if (
            due
            and due < now
            and lead.get("status")
            not in {"booked", "completed", "lost"}
        ):
            lead["sla_status"] = "breached"
            sla_breached += 1
        elif due:
            lead["sla_status"] = "within_sla"
        else:
            lead["sla_status"] = "not_set"

    admin_tasks = build_admin_tasks(state)
    state["admin_tasks"] = admin_tasks
    state["stats"] = {
        "customers": len(state["customers"]),
        "leads": len(state["leads"]),
        "new": sum(
            1 for item in state["leads"]
            if item.get("status") == "new"
        ),
        "follow_up": sum(
            1 for item in state["leads"]
            if item.get("status") == "follow_up"
        ),
        "booked": sum(
            1 for item in state["leads"]
            if item.get("status") == "booked"
        ),
        "pending_approvals": sum(
            1 for item in state["approvals"]
            if item.get("status")
            in BUSINESS_APPROVAL_PENDING_STATUSES
        ),
        "bookings": len(state["bookings"]),
        "planned_followups": sum(
            1 for item in state["followups"]
            if item.get("status") == "planned_not_sent"
        ),
        "tasks": len(admin_tasks),
        "sla_breached": sla_breached,
        "templates": len(state["reply_templates"]),
    }
    return state


def append_business_audit(
    state: dict[str, Any],
    event: str,
    detail: str,
    *,
    limit: int,
) -> None:
    audit = state.get("audit_log")
    if not isinstance(audit, list):
        audit = []
    audit.append({
        "event": event,
        "detail": detail,
        "created_at": utc_now_iso(),
        "execution": "record_only",
    })
    state["audit_log"] = audit[-limit:]


def limited_text(
    value: Any,
    *,
    max_length: int,
) -> str:
    return str(value or "").strip()[:max_length]


def required_approval_level(
    analysis: dict[str, Any],
    state: dict[str, Any],
) -> int:
    priority = str(analysis.get("priority") or "medium")
    category = str(analysis.get("category") or "other")
    if (
        bool(analysis.get("should_escalate"))
        or priority in {"urgent", "high"}
        or category in {"complaint", "payment"}
    ):
        return 2
    rule = sla_rule_for(state, priority)
    try:
        level = int(rule.get("approval_level", 1))
    except (TypeError, ValueError):
        level = 1
    return 2 if level >= 2 else 1


def sync_whatsapp_record_to_operations(
    state: dict[str, Any] | None,
    record: dict[str, Any],
    *,
    current_version: int,
    record_limit: int,
    audit_limit: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    operations = normalize_business_operations_state(state)
    analysis = record.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("Analisis WhatsApp simulator tidak tersedia.")

    customer_name = limited_text(
        record.get("customer_name"),
        max_length=180,
    ) or "Pelanggan simulasi"
    customer_contact = limited_text(
        record.get("customer_contact"),
        max_length=240,
    )
    customer_key = customer_identity_key(
        customer_name,
        customer_contact,
    )
    now = utc_now_iso()

    customer = next(
        (
            item for item in operations["customers"]
            if item.get("customer_key") == customer_key
        ),
        None,
    )
    customer_created = False
    if customer is None:
        customer = {
            "id": (
                f"customer-sync-{current_version}-"
                f"{len(operations['customers']) + 1}"
            ),
            "customer_key": customer_key,
            "name": customer_name,
            "contact": customer_contact,
            "source": "whatsapp_simulation",
            "source_message_ids": [record.get("id", "")],
            "created_at": now,
            "updated_at": now,
        }
        operations["customers"].append(customer)
        customer_created = True
    else:
        message_ids = customer.get("source_message_ids")
        if not isinstance(message_ids, list):
            message_ids = []
        if record.get("id") not in message_ids:
            message_ids.append(record.get("id"))
        customer.update({
            "name": customer_name or customer.get("name"),
            "contact": (
                customer_contact or customer.get("contact", "")
            ),
            "source_message_ids": message_ids[-50:],
            "updated_at": now,
        })

    open_statuses = {"new", "contacted", "follow_up", "booked"}
    lead = next(
        (
            item for item in operations["leads"]
            if item.get("customer_key") == customer_key
            and item.get("status") in open_statuses
        ),
        None,
    )
    lead_created = False
    if lead is None:
        lead = {
            "id": (
                f"lead-sync-{current_version}-"
                f"{len(operations['leads']) + 1}"
            ),
            "customer_id": customer["id"],
            "customer_key": customer_key,
            "name": customer_name,
            "contact": customer_contact,
            "source": "whatsapp_simulation",
            "interest": limited_text(
                analysis.get("intent"),
                max_length=500,
            ),
            "notes": limited_text(
                record.get("customer_message"),
                max_length=1800,
            ),
            "latest_message": limited_text(
                record.get("customer_message"),
                max_length=1800,
            ),
            "source_message_ids": [record.get("id", "")],
            "status": "new",
            "priority": analysis.get("priority", "medium"),
            "lead_score": int(analysis.get("lead_score", 0) or 0),
            "ai_summary": limited_text(
                analysis.get("admin_note")
                or analysis.get("intent"),
                max_length=1200,
            ),
            "next_action": (
                (analysis.get("recommended_actions") or [""])[0]
                if isinstance(
                    analysis.get("recommended_actions"),
                    list,
                )
                else ""
            ),
            "missing_information": (
                analysis.get("missing_information")
                if isinstance(
                    analysis.get("missing_information"),
                    list,
                )
                else []
            ),
            "should_escalate": bool(
                analysis.get("should_escalate")
            ),
            "escalation_reason": limited_text(
                analysis.get("escalation_reason"),
                max_length=700,
            ),
            "created_at": now,
            "updated_at": now,
        }
        lead["sla_due_at"] = compute_sla_due_at(
            operations,
            str(lead["priority"]),
            created_at=now,
        )
        operations["leads"].append(lead)
        lead_created = True
    else:
        message_ids = lead.get("source_message_ids")
        if not isinstance(message_ids, list):
            message_ids = []
        if record.get("id") not in message_ids:
            message_ids.append(record.get("id"))
        lead.update({
            "name": customer_name,
            "contact": customer_contact or lead.get("contact", ""),
            "latest_message": limited_text(
                record.get("customer_message"),
                max_length=1800,
            ),
            "source_message_ids": message_ids[-50:],
            "priority": analysis.get(
                "priority",
                lead.get("priority", "medium"),
            ),
            "lead_score": max(
                int(lead.get("lead_score", 0) or 0),
                int(analysis.get("lead_score", 0) or 0),
            ),
            "updated_at": now,
        })
        if not lead.get("sla_due_at"):
            lead["sla_due_at"] = compute_sla_due_at(
                operations,
                str(lead.get("priority", "medium")),
                created_at=lead.get("created_at"),
            )

    required_level = required_approval_level(
        analysis,
        operations,
    )
    approval = next(
        (
            item for item in operations["approvals"]
            if (
                item.get("source_message_id") == record.get("id")
                and item.get("lead_id") == lead["id"]
                and item.get("customer_id") == customer["id"]
            )
        ),
        None,
    )
    if approval is None:
        approval = normalize_approval({
            "id": (
                f"approval-sync-{current_version}-"
                f"{len(operations['approvals']) + 1}"
            ),
            "lead_id": lead["id"],
            "lead_name": customer_name,
            "customer_id": customer["id"],
            "source_message_id": record.get("id", ""),
            "type": "whatsapp_reply_draft",
            "content": limited_text(
                analysis.get("draft_reply"),
                max_length=3000,
            ),
            "suggested_due": lead.get("sla_due_at", ""),
            "sla_due_at": lead.get("sla_due_at", ""),
            "required_level": required_level,
            "required_role": (
                "manager" if required_level == 2 else "admin"
            ),
            "current_level": 0,
            "status": "pending_admin",
            "delivery_status": "not_sent",
            "created_at": now,
            "review_history": [],
        })
        operations["approvals"].append(approval)

    operations["customers"] = operations["customers"][
        -record_limit:
    ]
    operations["leads"] = operations["leads"][-record_limit:]
    operations["approvals"] = operations["approvals"][
        -record_limit:
    ]

    append_business_audit(
        operations,
        "whatsapp_simulation_synced",
        (
            f"Pesan simulasi {record.get('id', '')} disinkronkan "
            f"ke pelanggan {customer_name} dan prospek {lead['id']}."
        ),
        limit=audit_limit,
    )
    operations = normalize_business_operations_state(operations)

    return operations, {
        "synced": True,
        "customer_id": customer["id"],
        "customer_created": customer_created,
        "lead_id": lead["id"],
        "lead_created": lead_created,
        "approval_id": approval["id"],
        "approval_status": approval["status"],
        "required_approval_level": approval["required_level"],
        "live_sent": False,
    }


def apply_approval_decision(
    approval: dict[str, Any],
    *,
    decision: str,
    reviewer_role: str,
) -> dict[str, Any]:
    result = normalize_approval(approval)
    role = reviewer_role if reviewer_role in {
        "admin",
        "manager",
        "owner",
    } else "admin"
    history = result.get("review_history")
    if not isinstance(history, list):
        history = []

    if decision == "reject":
        result["status"] = "rejected"
        result["delivery_status"] = "not_sent"
    elif decision == "approve":
        if result["status"] == "pending_manager":
            if role not in {"manager", "owner"}:
                raise ValueError(
                    "Draft ini memerlukan persetujuan manager atau owner."
                )
            result["status"] = "approved_not_sent"
            result["current_level"] = 2
        elif result["status"] in {"pending_admin", "pending"}:
            if (
                result["required_level"] >= 2
                and role == "admin"
            ):
                result["status"] = "pending_manager"
                result["current_level"] = 1
            else:
                result["status"] = "approved_not_sent"
                result["current_level"] = result["required_level"]
        else:
            raise ValueError(
                "Draft ini sudah tidak menunggu persetujuan."
            )
        result["delivery_status"] = "not_sent"
    else:
        raise ValueError("Keputusan approval tidak valid.")

    history.append({
        "decision": decision,
        "reviewer_role": role,
        "status_after": result["status"],
        "reviewed_at": utc_now_iso(),
        "delivery_status": "not_sent",
    })
    result["review_history"] = history[-20:]
    result["reviewed_at"] = utc_now_iso()
    return result


def business_operations_csv_rows(
    state: dict[str, Any] | None,
    *,
    limit: int,
) -> list[dict[str, str]]:
    operations = normalize_business_operations_state(state)
    rows: list[dict[str, str]] = []

    for item in operations["customers"]:
        rows.append({
            "record_type": "customer",
            "record_id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "contact": str(item.get("contact", "")),
            "status": "active",
            "priority": "",
            "lead_score": "",
            "detail": str(item.get("source", "")),
            "delivery_status": "",
            "created_at": str(item.get("created_at", "")),
        })

    for item in operations["leads"]:
        rows.append({
            "record_type": "lead",
            "record_id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "contact": str(item.get("contact", "")),
            "status": str(item.get("status", "")),
            "priority": str(item.get("priority", "")),
            "lead_score": str(item.get("lead_score", "")),
            "detail": str(
                item.get("interest")
                or item.get("latest_message")
                or ""
            ),
            "delivery_status": "",
            "created_at": str(item.get("created_at", "")),
        })

    for item in operations["approvals"]:
        rows.append({
            "record_type": "approval",
            "record_id": str(item.get("id", "")),
            "name": str(item.get("lead_name", "")),
            "contact": "",
            "status": str(item.get("status", "")),
            "priority": (
                "high"
                if item.get("required_level") == 2
                else "medium"
            ),
            "lead_score": "",
            "detail": str(item.get("content", "")),
            "delivery_status": str(
                item.get("delivery_status", "not_sent")
            ),
            "created_at": str(item.get("created_at", "")),
        })

    for item in operations["bookings"]:
        rows.append({
            "record_type": "booking",
            "record_id": str(item.get("id", "")),
            "name": str(item.get("customer_name", "")),
            "contact": "",
            "status": str(item.get("status", "")),
            "priority": "",
            "lead_score": "",
            "detail": (
                f"{item.get('service_name', '')} · "
                f"{item.get('schedule_text', '')}"
            ),
            "delivery_status": str(
                item.get("confirmation_status", "not_sent")
            ),
            "created_at": str(item.get("created_at", "")),
        })

    for item in operations["followups"]:
        rows.append({
            "record_type": "followup",
            "record_id": str(item.get("id", "")),
            "name": str(item.get("target_name", "")),
            "contact": "",
            "status": str(item.get("status", "")),
            "priority": "",
            "lead_score": "",
            "detail": str(item.get("draft_message", "")),
            "delivery_status": str(
                item.get("delivery_status", "not_sent")
            ),
            "created_at": str(item.get("created_at", "")),
        })

    return rows[-max(1, limit):]


def find_core_project_detail(
    request: Request,
    *,
    slug: str,
    section_slug: str,
) -> dict[str, Any] | None:
    rows = core_list_projects(request, settings, slug)
    wanted = core_project_type(slug, section_slug)
    row = next(
        (
            item for item in rows
            if item.get("project_type") == wanted
        ),
        None,
    )
    if not row:
        return None
    return core_get_project(request, settings, str(row["id"]))


def get_or_create_operations_project(
    request: Request,
    *,
    business_context: str,
) -> dict[str, Any]:
    detail = find_core_project_detail(
        request,
        slug="business",
        section_slug="operations",
    )
    if detail:
        return detail

    guide_data = get_guide("business", "operations")
    created = core_create_project(
        request,
        settings,
        "business",
        {
            "title": guide_data["title"],
            "project_type": core_project_type(
                "business",
                "operations",
            ),
            "status": "testing",
            "input_data": {
                "need": business_context,
                "choice": "WhatsApp AI Admin integration",
                "deliverables": guide_data["deliverables"],
                "steps": product_steps("business"),
                "stage": "testing",
                "stage_label": "Workflow dibuat otomatis",
                "status_message": (
                    "Business Operations dibuat untuk menerima data "
                    "dari WhatsApp simulator."
                ),
                "ai_error": "",
            },
            "output_data": {
                "business_operations": (
                    default_business_operations_state()
                ),
            },
        },
    )
    return core_get_project(request, settings, str(created["id"]))



def normalize_core_project(
    project: dict[str, Any],
    slug: str,
    section_slug: str,
    guide_data: dict[str, Any],
) -> dict[str, Any]:
    input_data = project.get("input_data") or {}
    if not isinstance(input_data, dict):
        input_data = {}
    output_data = project.get("output_data") or {}
    if not isinstance(output_data, dict):
        output_data = {}
    if slug == "personal" and section_slug in {
        "creator",
        "freelancer",
    }:
        output_key = personal_ai_output_key(section_slug)
    elif slug == "business" and section_slug == "chat":
        output_key = "whatsapp_admin"
    elif slug == "business" and section_slug == "operations":
        output_key = "business_operations"
    else:
        output_key = ""
    ai_output = output_data.get(output_key) if output_key else None
    if slug == "business" and section_slug == "operations":
        ai_output = normalize_business_operations_state(
            ai_output if isinstance(ai_output, dict) else None
        )
    elif not isinstance(ai_output, dict):
        ai_output = None
    ai_meta = output_data.get("ai_meta")
    if not isinstance(ai_meta, dict):
        ai_meta = {}
    stage = str(input_data.get("stage") or project.get("status") or "draft")
    return {
        "id": str(project.get("id", "")),
        "slug": slug,
        "section_slug": section_slug,
        "title": str(project.get("title") or guide_data["title"]),
        "need": str(input_data.get("need", "")),
        "choice": str(input_data.get("choice", "Belum dipilih")),
        "deliverables": input_data.get("deliverables") or guide_data["deliverables"],
        "steps": input_data.get("steps") or product_steps(slug),
        "stage": stage,
        "stage_label": str(input_data.get("stage_label", "Rancangan tersimpan")),
        "revision": str(input_data.get("revision", "")),
        "status_message": str(input_data.get("status_message", "Rancangan tersimpan pada akun Anda.")),
        "current_version": int(project.get("current_version") or 1),
        "ai_output": ai_output,
        "ai_meta": ai_meta,
        "ai_error": str(input_data.get("ai_error", "")),
        "_input_data": input_data,
        "_output_data": output_data,
    }


def current_project(
    request: Request,
    slug: str,
    section_slug: str,
    guide_data: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.core_integration_enabled:
        return projects(request).get(project_key(slug, section_slug))
    try:
        rows = core_list_projects(request, settings, slug)
        wanted = core_project_type(slug, section_slug)
        row = next(
            (item for item in rows if item.get("project_type") == wanted),
            None,
        )
        if not row:
            return None
        detail = core_get_project(request, settings, str(row["id"]))
        return normalize_core_project(detail, slug, section_slug, guide_data)
    except CoreAPIError as exc:
        request.state.core_error = exc.detail
        return None


def base_context(request: Request) -> dict[str, Any]:
    user = current_user(request)
    raw_active = active_products(request) if user else []

    # Map core entitlement slugs to canonical UI slugs
    active_slugs = set()
    for slug in raw_active:
        if slug in ("business_suite", "business-suite"):
            active_slugs.add("business_suite")
        elif slug in ("webhook", "webhook-connector", "connect"):
            active_slugs.add("connect")
        elif slug in ("parking",):
            active_slugs.add("parking")

    # Universal capabilities for all authenticated accounts
    if user:
        active_slugs.add("drive")

    has_business_suite = "business_suite" in active_slugs
    has_connect = "connect" in active_slugs
    has_parking = "parking" in active_slugs

    entitled_products = []
    if has_business_suite and "business_suite" in PUBLIC_PRODUCT_MAP:
        p = dict(PUBLIC_PRODUCT_MAP["business_suite"])
        p["status"] = "Aktif"
        p["status_class"] = "live"
        entitled_products.append(p)

    if has_parking and "parking" in PUBLIC_PRODUCT_MAP:
        p = dict(PUBLIC_PRODUCT_MAP["parking"])
        p["status"] = "Aktif"
        p["status_class"] = "live"
        entitled_products.append(p)

    if has_connect and "connect" in PUBLIC_PRODUCT_MAP:
        p = dict(PUBLIC_PRODUCT_MAP["connect"])
        p["status"] = "Aktif"
        p["status_class"] = "live"
        entitled_products.append(p)

    if user and "drive" in PUBLIC_PRODUCT_MAP:
        p = dict(PUBLIC_PRODUCT_MAP["drive"])
        p["status"] = "Universal"
        p["status_class"] = "live"
        entitled_products.append(p)

    account_groups = []
    for group in PUBLIC_GROUPS:
        visible = []
        for product in group["products"]:
            if product.get("legacy"):
                continue
            if product.get("requires_auth") and product["slug"] not in active_slugs:
                continue
            item = dict(product)
            if item["slug"] == "business_suite":
                item["public_url"] = "/bisnis/"
                item["home_cta"] = "Buka Business Suite"
                item["status"] = "Aktif"
                item["status_class"] = "live"
            elif item["slug"] == "parking":
                item["public_url"] = "/parking/"
                item["home_cta"] = "Buka Parking"
                item["status"] = "Aktif" if has_parking else "Tersedia"
                item["status_class"] = "live" if has_parking else ""
            elif item["slug"] == "connect":
                item["status"] = "Aktif" if has_connect else "Tersedia"
            visible.append(item)
        if visible:
            account_groups.append({**group, "products": visible})

    return {
        "request": request,
        "settings": settings,
        "products": PRODUCTS,
        "home_products": HOME_PRODUCTS,
        "home_groups": HOME_GROUPS,
        "public_products": [p for p in PUBLIC_PRODUCTS if not p.get("legacy")],
        "public_groups": PUBLIC_GROUPS,
        "account_groups": account_groups,
        "entitled_products": entitled_products,
        "has_business_suite": has_business_suite,
        "has_connect": has_connect,
        "has_parking": has_parking,
        "user": user,
        "is_platform_admin": is_platform_admin(
            request,
            settings,
            current_user,
        ),
        "active_product_slugs": list(active_slugs),
        "active_products": [PUBLIC_PRODUCT_MAP[s] for s in active_slugs if s in PUBLIC_PRODUCT_MAP],
        "core_integration_enabled": settings.core_integration_enabled,
        "creator_ai_enabled": settings.creator_ai_enabled,
        "freelancer_ai_enabled": settings.freelancer_ai_enabled,
        "business_ai_enabled": settings.business_ai_enabled,
        "business_operations_enabled": (
            settings.business_operations_enabled
        ),
        "business_workflow_enabled": (
            settings.business_workflow_enabled
        ),
        "core_error": getattr(request.state, "core_error", None),
    }


def product_destination(request: Request, slug: str) -> str:
    product = PRODUCT_MAP.get(slug)
    if slug in STAGING_PRODUCT_SLUGS:
        return "/staging-closed"
    if product and product.get("direct_url"):
        return str(product["direct_url"])
    if not current_user(request):
        return f"/login?product={slug}"
    if slug not in active_products(request):
        return f"/onboarding/{slug}"
    return f"/app/{slug}"


def require_product_access(request: Request, slug: str) -> RedirectResponse | None:
    if slug in STAGING_PRODUCT_SLUGS:
        return RedirectResponse("/staging-closed", status_code=303)
    if not current_user(request):
        request.session["selected_product"] = slug
        return RedirectResponse(f"/login?product={slug}", status_code=303)
    if slug not in active_products(request):
        return RedirectResponse(f"/onboarding/{slug}", status_code=303)
    return None


def auth_switch_url(request: Request, target: str) -> str:
    slug = request.session.get("selected_product")
    assistant = request.session.get("selected_assistant")
    params: list[str] = []
    if slug in PRODUCT_MAP:
        params.append(f"product={slug}")
    if slug == "personal" and assistant in PERSONAL_ASSISTANTS:
        params.append(f"assistant={assistant}")
    suffix = "?" + "&".join(params) if params else ""
    return f"/{target}{suffix}"


def render_auth_error(
    request: Request,
    mode: str,
    message: str,
    *,
    status_code: int = 400,
    form_values: dict[str, str] | None = None,
):
    context = base_context(request)
    context.update({
        "mode": mode,
        "error": message,
        "selected_product": PRODUCT_MAP.get(request.session.get("selected_product")),
        "switch_url": auth_switch_url(
            request,
            "login" if mode == "register" else "register",
        ),
        "form_values": form_values or {},
        "csrf_token": _preauth_csrf_token(request),
    })
    return templates.TemplateResponse(
        request,
        "auth.html",
        context,
        status_code=status_code,
    )



# ============================================================
# BOTCONNECTOR_ACCOUNT_RECOVERY_V1
# ============================================================

def _preauth_csrf_token(
    request: Request,
) -> str:
    import secrets

    token = request.session.get(
        "preauth_csrf_token"
    )

    if (
        not isinstance(token, str)
        or len(token) < 32
    ):
        token = secrets.token_urlsafe(32)

        request.session[
            "preauth_csrf_token"
        ] = token

    return token


def _valid_preauth_csrf(
    request: Request,
    supplied: str,
) -> bool:
    import hmac

    expected = request.session.get(
        "preauth_csrf_token"
    )

    return (
        isinstance(expected, str)
        and bool(expected)
        and bool(supplied)
        and hmac.compare_digest(
            expected,
            supplied,
        )
    )


def _recovery_response(
    request: Request,
    *,
    mode: str,
    message: str = "",
    error: str = "",
    email: str = "",
    token: str = "",
    status_code: int = 200,
):
    context = base_context(request)

    context.update({
        "recovery_mode": mode,
        "message": message,
        "error": error,
        "email": email,
        "token": token,
        "csrf_token": _preauth_csrf_token(
            request
        ),
    })

    return templates.TemplateResponse(
        request,
        "account_recovery.html",
        context,
        status_code=status_code,
    )



def product_steps(slug: str) -> list[str]:
    return {
        "webhook": ["Pahami kebutuhan", "Susun konfigurasi", "Uji koneksi", "Aktifkan"],
        "langkah": ["Kumpulkan data", "Buat hasil", "Periksa bersama", "Siap digunakan"],
        "business": ["Pahami proses", "Susun automasi", "Uji skenario", "Aktifkan"],
        "personal": ["Pahami tujuan", "Susun ruang kerja", "Uji alur", "Gunakan"],
        "monitor": ["Daftar layanan", "Atur pemeriksaan", "Uji peringatan", "Aktifkan"],
    }[slug]


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    from urllib.parse import urlencode

    reset_token = str(
        request.query_params.get(
            "reset_token",
            "",
        )
    ).strip()

    verify_token = str(
        request.query_params.get(
            "verify_token",
            "",
        )
    ).strip()

    if reset_token:
        return RedirectResponse(
            "/reset-password?"
            + urlencode({
                "token": reset_token,
            }),
            status_code=303,
        )

    if verify_token:
        return RedirectResponse(
            "/verify-email?"
            + urlencode({
                "token": verify_token,
            }),
            status_code=303,
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        base_context(request),
    )


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request):
    return templates.TemplateResponse(request, "products.html", base_context(request))


@app.get("/choose/{slug}")
def choose_product(request: Request, slug: str):
    product = get_product(slug)
    if product.get("direct_url"):
        return RedirectResponse(str(product["direct_url"]), status_code=303)
    request.session["selected_product"] = slug
    return RedirectResponse(product_destination(request, slug), status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    product: str | None = None,
    assistant: str | None = None,
):
    if product == "personal":
        remember_personal_assistant(request, assistant)
    if product in PRODUCT_MAP:
        request.session["selected_product"] = product
        if current_user(request):
            return RedirectResponse(
                product_destination(request, product),
                status_code=303,
            )
    else:
        if current_user(request):
            return RedirectResponse("/my-products", status_code=303)
        # A generic login must not inherit a previous product continuation.
        request.session.pop("selected_product", None)
    context = base_context(request)
    context.update({
        "mode": "login",
        "selected_product": PRODUCT_MAP.get(request.session.get("selected_product")),
        "switch_url": auth_switch_url(request, "register"),
        "form_values": {},
        "csrf_token": _preauth_csrf_token(request),
    })
    return templates.TemplateResponse(request, "auth.html", context)


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()

    supplied_csrf = str(
        form.get("csrf_token", "")
    )

    if not _valid_preauth_csrf(
        request,
        supplied_csrf,
    ):
        return render_auth_error(
            request,
            "login",
            (
                "Sesi formulir sudah tidak valid. "
                "Silakan muat ulang halaman."
            ),
            status_code=403,
        )
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    values = {"email": email}

    if not email or "@" not in email:
        return render_auth_error(
            request,
            "login",
            "Masukkan alamat email yang valid.",
            form_values=values,
        )

    if settings.core_integration_enabled:
        if not password:
            return render_auth_error(
                request,
                "login",
                "Masukkan password akun Anda.",
                form_values=values,
            )
        try:
            upstream = core_api_request(
                request,
                settings,
                "POST",
                "/v1/auth/login",
                json_data={"email": email, "password": password},
            )
            payload = upstream.json()
            token = response_session_token(
                upstream,
                settings.core_cookie_name,
            )
            if not token:
                raise CoreAPIError(502, "Cookie sesi akun tidak diterima.")
            request.session["core_csrf_token"] = payload["csrf_token"]
            request.session.pop("user", None)
            request.session.pop("product_access", None)
            request.session.pop("projects", None)
            slug = request.session.get("selected_product")
            destination = (
                str(PRODUCT_MAP[slug]["direct_url"])
                if slug in PRODUCT_MAP and PRODUCT_MAP[slug].get("direct_url")
                else f"/onboarding/{slug}"
                if slug in PRODUCT_MAP
                else "/my-products"
            )
            response = RedirectResponse(destination, status_code=303)
            set_browser_session(response, settings, token)
            return response
        except CoreAPIError as exc:
            return render_auth_error(
                request,
                "login",
                exc.detail,
                status_code=exc.status_code if exc.status_code < 500 else 502,
                form_values=values,
            )

    request.session["user"] = {
        "email": email,
        "name": email.split("@", 1)[0].replace(".", " ").title(),
    }
    slug = request.session.get("selected_product")
    return (
        RedirectResponse(product_destination(request, slug), status_code=303)
        if slug in PRODUCT_MAP
        else RedirectResponse("/my-products", status_code=303)
    )


@app.get("/register", response_class=HTMLResponse)
def register_page(
    request: Request,
    product: str | None = None,
    assistant: str | None = None,
):
    if product in PRODUCT_MAP:
        request.session["selected_product"] = product
    if product == "personal":
        remember_personal_assistant(request, assistant)
    context = base_context(request)
    context.update({
        "mode": "register",
        "selected_product": PRODUCT_MAP.get(request.session.get("selected_product")),
        "switch_url": auth_switch_url(request, "login"),
        "form_values": {},
        "csrf_token": _preauth_csrf_token(request),
    })
    return templates.TemplateResponse(request, "auth.html", context)


@app.post("/register")
async def register_submit(request: Request):
    form = await request.form()

    supplied_csrf = str(
        form.get("csrf_token", "")
    )

    if not _valid_preauth_csrf(
        request,
        supplied_csrf,
    ):
        return render_auth_error(
            request,
            "register",
            (
                "Sesi formulir sudah tidak valid. "
                "Silakan muat ulang halaman."
            ),
            status_code=403,
        )
    name = str(form.get("name", "")).strip()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    values = {"name": name, "email": email}

    if not name or not email or "@" not in email:
        return render_auth_error(
            request,
            "register",
            "Isi nama dan alamat email yang valid.",
            form_values=values,
        )

    if settings.core_integration_enabled:
        if password != confirm_password:
            return render_auth_error(
                request,
                "register",
                "Konfirmasi password tidak sama.",
                form_values=values,
            )
        privacy = form.get("privacy_consent") == "yes"
        terms = form.get("terms_consent") == "yes"
        data_consent = form.get("data_consent") == "yes"
        if not all((privacy, terms, data_consent)):
            return render_auth_error(
                request,
                "register",
                "Semua persetujuan wajib diberikan untuk membuat akun.",
                form_values=values,
            )
        selected = request.session.get("selected_product")
        selected_core = (
            core_slug(selected)
            if selected in PRODUCT_MAP
            else None
        )
        try:
            upstream = core_api_request(
                request,
                settings,
                "POST",
                "/v1/auth/register",
                json_data={
                    "email": email,
                    "password": password,
                    "display_name": name,
                    "selected_product": selected_core,
                    "privacy_consent": privacy,
                    "terms_consent": terms,
                    "job_data_consent": data_consent,
                },
            )
            payload = upstream.json()
            if payload.get("verification_required"):
                return render_auth_error(
                    request,
                    "login",
                    str(payload.get("message") or "Periksa email untuk verifikasi."),
                    status_code=200,
                    form_values={"email": email},
                )
            token = response_session_token(
                upstream,
                settings.core_cookie_name,
            )
            if not token:
                raise CoreAPIError(502, "Cookie sesi akun tidak diterima.")
            request.session["core_csrf_token"] = payload["csrf_token"]
            request.session.pop("user", None)
            request.session.pop("product_access", None)
            request.session.pop("projects", None)
            destination = (
                str(PRODUCT_MAP[selected]["direct_url"])
                if selected in PRODUCT_MAP and PRODUCT_MAP[selected].get("direct_url")
                else f"/onboarding/{selected}"
                if selected in PRODUCT_MAP
                else "/my-products"
            )
            response = RedirectResponse(destination, status_code=303)
            set_browser_session(response, settings, token)
            return response
        except CoreAPIError as exc:
            return render_auth_error(
                request,
                "register",
                exc.detail,
                status_code=exc.status_code if exc.status_code < 500 else 502,
                form_values=values,
            )

    request.session["user"] = {"email": email, "name": name}
    slug = request.session.get("selected_product")
    return (
        RedirectResponse(product_destination(request, slug), status_code=303)
        if slug in PRODUCT_MAP
        else RedirectResponse("/my-products", status_code=303)
    )


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    if settings.core_integration_enabled:
        token = request.cookies.get(settings.core_cookie_name)
        if token:
            try:
                if not request.session.get("core_csrf_token"):
                    try:
                        me_res = core_api_request(request, settings, "GET", "/v1/me")
                        csrf_val = me_res.json().get("csrf_token")
                        if csrf_val:
                            request.session["core_csrf_token"] = csrf_val
                    except Exception:
                        pass

                core_api_request(
                    request,
                    settings,
                    "POST",
                    "/v1/auth/logout",
                    csrf=True,
                )
            except CoreAPIError:
                pass
        clear_browser_session(response, settings)
    request.session.clear()
    return response



# ============================================================
# ACCOUNT RECOVERY PUBLIC ROUTES
# ============================================================

@app.get(
    "/forgot-password",
    response_class=HTMLResponse,
)
def forgot_password_page(
    request: Request,
):
    return _recovery_response(
        request,
        mode="forgot",
    )


@app.post(
    "/forgot-password",
    response_class=HTMLResponse,
)
async def forgot_password_submit(
    request: Request,
):
    form = await request.form()

    supplied_csrf = str(
        form.get("csrf_token", "")
    )

    email = str(
        form.get("email", "")
    ).strip().lower()

    if not _valid_preauth_csrf(
        request,
        supplied_csrf,
    ):
        return _recovery_response(
            request,
            mode="forgot",
            email=email,
            error=(
                "Sesi formulir sudah tidak valid. "
                "Silakan muat ulang halaman."
            ),
            status_code=403,
        )

    if not email or "@" not in email:
        return _recovery_response(
            request,
            mode="forgot",
            email=email,
            error=(
                "Masukkan alamat email yang valid."
            ),
        )

    if not settings.core_integration_enabled:
        return _recovery_response(
            request,
            mode="forgot",
            email=email,
            error=(
                "Layanan akun sedang tidak tersedia."
            ),
            status_code=503,
        )

    try:
        core_api_request(
            request,
            settings,
            "POST",
            "/v1/auth/forgot-password",
            json_data={
                "email": email,
            },
        )

    except CoreAPIError as exc:
        if exc.status_code == 429:
            return _recovery_response(
                request,
                mode="forgot",
                email=email,
                error=(
                    "Terlalu banyak permintaan. "
                    "Silakan coba lagi nanti."
                ),
                status_code=429,
            )

        if exc.status_code >= 500:
            return _recovery_response(
                request,
                mode="forgot",
                email=email,
                error=(
                    "Layanan akun sedang tidak "
                    "tersedia. Silakan coba kembali."
                ),
                status_code=502,
            )

        # Deliberately do not reveal whether
        # an account exists for this email.

    return _recovery_response(
        request,
        mode="forgot_sent",
        email=email,
        message=(
            "Jika alamat tersebut terdaftar, "
            "instruksi reset password akan "
            "dikirim ke email Anda."
        ),
    )


@app.get(
    "/reset-password",
    response_class=HTMLResponse,
)
def reset_password_page(
    request: Request,
):
    token = str(
        request.query_params.get(
            "token",
            "",
        )
    ).strip()

    return _recovery_response(
        request,
        mode="reset",
        token=token,
        error=(
            ""
            if token
            else (
                "Tautan reset password "
                "tidak lengkap."
            )
        ),
    )


@app.post(
    "/reset-password",
    response_class=HTMLResponse,
)
async def reset_password_submit(
    request: Request,
):
    form = await request.form()

    supplied_csrf = str(
        form.get("csrf_token", "")
    )

    token = str(
        form.get("token", "")
    ).strip()

    new_password = str(
        form.get("new_password", "")
    )

    confirm_password = str(
        form.get("confirm_password", "")
    )

    if not _valid_preauth_csrf(
        request,
        supplied_csrf,
    ):
        return _recovery_response(
            request,
            mode="reset",
            token=token,
            error=(
                "Sesi formulir sudah tidak valid. "
                "Silakan buka kembali tautan reset."
            ),
            status_code=403,
        )

    if not token:
        return _recovery_response(
            request,
            mode="reset",
            error=(
                "Token reset password "
                "tidak tersedia."
            ),
        )

    if (
        not new_password
        or new_password != confirm_password
    ):
        return _recovery_response(
            request,
            mode="reset",
            token=token,
            error=(
                "Password dan konfirmasi "
                "password harus sama."
            ),
        )

    try:
        core_api_request(
            request,
            settings,
            "POST",
            "/v1/auth/reset-password",
            json_data={
                "token": token,
                "new_password": new_password,
            },
        )

    except CoreAPIError as exc:
        return _recovery_response(
            request,
            mode="reset",
            token=token,
            error=exc.detail,
            status_code=(
                exc.status_code
                if exc.status_code < 500
                else 502
            ),
        )

    request.session.pop(
        "preauth_csrf_token",
        None,
    )

    return _recovery_response(
        request,
        mode="reset_done",
        message=(
            "Password berhasil diubah. "
            "Silakan masuk menggunakan "
            "password baru."
        ),
    )


@app.get(
    "/verify-email",
    response_class=HTMLResponse,
)
def verify_email_page(
    request: Request,
):
    token = str(
        request.query_params.get(
            "token",
            "",
        )
    ).strip()

    if token:
        return _recovery_response(
            request,
            mode="verify_confirm",
            token=token,
        )

    return _recovery_response(
        request,
        mode="verify_request",
    )


@app.post(
    "/verify-email",
    response_class=HTMLResponse,
)
async def verify_email_submit(
    request: Request,
):
    form = await request.form()

    supplied_csrf = str(
        form.get("csrf_token", "")
    )

    token = str(
        form.get("token", "")
    ).strip()

    email = str(
        form.get("email", "")
    ).strip().lower()

    if not _valid_preauth_csrf(
        request,
        supplied_csrf,
    ):
        return _recovery_response(
            request,
            mode=(
                "verify_confirm"
                if token
                else "verify_request"
            ),
            token=token,
            email=email,
            error=(
                "Sesi formulir sudah tidak valid. "
                "Silakan muat ulang halaman."
            ),
            status_code=403,
        )

    # --------------------------------------------------------
    # TOKEN PRESENT = VERIFY
    # --------------------------------------------------------

    if token:
        try:
            upstream = core_api_request(
                request,
                settings,
                "POST",
                "/v1/auth/verify-email",
                json_data={
                    "token": token,
                },
            )

            payload = upstream.json()

            core_session = response_session_token(
                upstream,
                settings.core_cookie_name,
            )

            csrf = payload.get(
                "csrf_token",
                "",
            )

            if (
                isinstance(csrf, str)
                and csrf
            ):
                request.session[
                    "core_csrf_token"
                ] = csrf

            response = _recovery_response(
                request,
                mode="verified",
                message=(
                    "Email berhasil diverifikasi. "
                    "Akun Anda sekarang aktif."
                ),
            )

            if core_session:
                set_browser_session(
                    response,
                    settings,
                    core_session,
                )

            return response

        except CoreAPIError as exc:
            return _recovery_response(
                request,
                mode="verify_error",
                token=token,
                error=exc.detail,
                status_code=(
                    exc.status_code
                    if exc.status_code < 500
                    else 502
                ),
            )

    # --------------------------------------------------------
    # NO TOKEN = RESEND VERIFICATION EMAIL
    # --------------------------------------------------------

    if not email or "@" not in email:
        return _recovery_response(
            request,
            mode="verify_request",
            email=email,
            error=(
                "Masukkan alamat email yang valid."
            ),
        )

    try:
        core_api_request(
            request,
            settings,
            "POST",
            "/v1/auth/request-verification",
            json_data={
                "email": email,
            },
        )

    except CoreAPIError as exc:
        if exc.status_code == 429:
            return _recovery_response(
                request,
                mode="verify_request",
                email=email,
                error=(
                    "Terlalu banyak permintaan. "
                    "Silakan coba lagi nanti."
                ),
                status_code=429,
            )

        if exc.status_code >= 500:
            return _recovery_response(
                request,
                mode="verify_request",
                email=email,
                error=(
                    "Layanan verifikasi sedang "
                    "tidak tersedia."
                ),
                status_code=502,
            )

    return _recovery_response(
        request,
        mode="verify_sent",
        email=email,
        message=(
            "Jika akun memerlukan verifikasi, "
            "tautan verifikasi akan dikirim "
            "ke email tersebut."
        ),
    )



@app.get("/onboarding/{slug}", response_class=HTMLResponse)
def onboarding_page(
    request: Request,
    slug: str,
    assistant: str | None = None,
):
    product = get_product(slug)
    if product.get("direct_url"):
        return RedirectResponse(str(product["direct_url"]), status_code=303)
    if slug == "personal":
        remember_personal_assistant(request, assistant)
    if not current_user(request):
        request.session["selected_product"] = slug
        return RedirectResponse(f"/login?product={slug}", status_code=303)
    existing_onboarding = None
    if settings.core_integration_enabled and slug in active_products(request):
        try:
            existing_onboarding = core_get_onboarding(request, settings, slug)
        except CoreAPIError as exc:
            request.state.core_error = exc.detail
        if existing_onboarding and existing_onboarding.get("completed_at"):
            return RedirectResponse(f"/app/{slug}", status_code=303)
    elif not settings.core_integration_enabled and slug in active_products(request):
        return RedirectResponse(f"/app/{slug}", status_code=303)
    context = base_context(request)
    context["product"] = product
    saved_answers = (existing_onboarding or {}).get("answers") or {}
    context["preferred_goal"] = (
        selected_personal_goal(request)
        if slug == "personal"
        else saved_answers.get("goal")
    )
    context["saved_notes"] = str(saved_answers.get("notes", ""))
    return templates.TemplateResponse(request, "onboarding.html", context)


@app.post("/onboarding/{slug}")
async def onboarding_submit(request: Request, slug: str):
    get_product(slug)
    if not current_user(request):
        request.session["selected_product"] = slug
        return RedirectResponse(f"/login?product={slug}", status_code=303)
    form = await request.form()
    goal = str(form.get("goal", "")).strip()
    notes = str(form.get("notes", "")).strip()

    if settings.core_integration_enabled:
        try:
            if slug not in active_products(request):
                core_activate_product(request, settings, slug)
            core_update_onboarding(
                request,
                settings,
                slug,
                {
                    "current_step": "complete",
                    "completed_steps": ["start", "goal", "details"],
                    "answers": {
                        "goal": goal,
                        "notes": notes,
                        "assistant": request.session.get("selected_assistant"),
                    },
                    "completed": True,
                },
            )
            request.session["selected_product"] = slug
            if slug == "personal":
                assistant_slug = request.session.get("selected_assistant")
                assistant = PERSONAL_ASSISTANTS.get(str(assistant_slug))
                if assistant:
                    return RedirectResponse(
                        f"/app/personal/{assistant['section']}",
                        status_code=303,
                    )
            return RedirectResponse(f"/app/{slug}", status_code=303)
        except CoreAPIError as exc:
            context = base_context(request)
            context.update({
                "product": get_product(slug),
                "preferred_goal": goal or (selected_personal_goal(request) if slug == "personal" else None),
                "saved_notes": notes,
                "error": exc.detail,
            })
            return templates.TemplateResponse(
                request,
                "onboarding.html",
                context,
                status_code=exc.status_code if exc.status_code < 500 else 502,
            )

    profiles = request.session.get("onboarding_profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
    profiles[slug] = {"goal": goal, "notes": notes}
    request.session["onboarding_profiles"] = profiles
    active = active_products(request)
    if slug not in active:
        active.append(slug)
    request.session["product_access"] = active
    request.session["selected_product"] = slug

    if slug == "personal":
        assistant_slug = request.session.get("selected_assistant")
        assistant = PERSONAL_ASSISTANTS.get(str(assistant_slug))
        if assistant:
            return RedirectResponse(
                f"/app/personal/{assistant['section']}",
                status_code=303,
            )

    return RedirectResponse(f"/app/{slug}", status_code=303)


@app.get("/my-products", response_class=HTMLResponse)
def my_products(request: Request):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "my_products.html", base_context(request))


@app.get("/app")
def app_home(request: Request):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    active = active_products(request)
    return RedirectResponse(f"/app/{active[0]}", status_code=303) if len(active) == 1 else RedirectResponse("/my-products", status_code=303)


@app.get("/app/{slug}", response_class=HTMLResponse)
def product_dashboard(request: Request, slug: str):
    product = get_product(slug)
    if product.get("direct_url"):
        return RedirectResponse(str(product["direct_url"]), status_code=303)
    return product_dashboard_section(request, slug, product["menu"][0]["slug"])


@app.get("/app/{slug}/{section_slug}", response_class=HTMLResponse)
def product_dashboard_section(request: Request, slug: str, section_slug: str):
    product = get_product(slug)
    denied = require_product_access(request, slug)
    if denied:
        return denied
    section = get_section(product, section_slug)
    guide_data = get_guide(slug, section_slug)
    request.session["selected_product"] = slug
    current_project_data = current_project(request, slug, section_slug, guide_data)
    context = base_context(request)
    context.update({
        "product": product,
        "section": section,
        "guide": guide_data,
        "project": current_project_data,
        "show_product_switcher": len(active_products(request)) > 1,
    })
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/app/{slug}/{section_slug}/create", response_class=HTMLResponse)
def create_page(request: Request, slug: str, section_slug: str):
    product = get_product(slug)
    denied = require_product_access(request, slug)
    if denied:
        return denied
    section = get_section(product, section_slug)
    guide_data = get_guide(slug, section_slug)
    existing = current_project(request, slug, section_slug, guide_data)
    context = base_context(request)
    context.update({"product": product, "section": section, "guide": guide_data, "project": existing})
    return templates.TemplateResponse(request, "create.html", context)


@app.post("/app/{slug}/{section_slug}/create")
async def create_submit(request: Request, slug: str, section_slug: str):
    product = get_product(slug)
    denied = require_product_access(request, slug)
    if denied:
        return denied
    section = get_section(product, section_slug)
    guide_data = get_guide(slug, section_slug)
    form = await request.form()
    need = str(form.get("need", "")).strip()
    choice = str(form.get("choice", "")).strip()
    if not need:
        context = base_context(request)
        context.update({"product": product, "section": section, "guide": guide_data, "project": None, "error": "Ceritakan kebutuhan Anda terlebih dahulu."})
        return templates.TemplateResponse(request, "create.html", context, status_code=400)
    if settings.core_integration_enabled:
        try:
            input_data = {
                "candidate_slug": slug,
                "section_slug": section_slug,
                "need": need,
                "choice": choice or "Belum dipilih",
                "deliverables": guide_data["deliverables"],
                "steps": product_steps(slug),
                "stage": "draft",
                "stage_label": "Rancangan tersimpan",
                "revision": "",
                "status_message": "Rancangan awal sudah disimpan pada akun Anda.",
                "assistant": request.session.get("selected_assistant"),
                "ai_error": "",
            }
            created = core_create_project(
                request,
                settings,
                slug,
                {
                    "title": guide_data["title"],
                    "project_type": core_project_type(slug, section_slug),
                    "input_data": input_data,
                },
            )

            if (
                slug == "personal"
                and personal_ai_enabled(section_slug)
            ):
                try:
                    generated = await run_in_threadpool(
                        generate_personal_plan,
                        section_slug,
                        need=need,
                        choice=choice or "Belum dipilih",
                    )
                    input_data.update({
                        "stage": "review",
                        "stage_label": "Hasil AI siap diperiksa",
                        "status_message": personal_ai_success_message(
                            section_slug,
                            revision=False,
                        ),
                        "ai_error": "",
                    })
                    core_update_project(
                        request,
                        settings,
                        str(created["id"]),
                        {
                            "status": "review",
                            "input_data": input_data,
                            "output_data": {
                                personal_ai_output_key(
                                    section_slug
                                ): generated["plan"],
                                "ai_meta": generated["meta"],
                            },
                        },
                    )
                except PersonalAIError as ai_exc:
                    input_data.update({
                        "stage": "draft",
                        "stage_label": "Rancangan tersimpan",
                        "status_message": (
                            "Kebutuhan sudah tersimpan. Mesin AI belum "
                            "berhasil dan dapat dicoba kembali."
                        ),
                        "ai_error": str(ai_exc),
                    })
                    core_update_project(
                        request,
                        settings,
                        str(created["id"]),
                        {
                            "status": "draft",
                            "input_data": input_data,
                        },
                    )

            return RedirectResponse(
                f"/app/{slug}/{section_slug}/project",
                status_code=303,
            )
        except CoreAPIError as exc:
            context = base_context(request)
            context.update({
                "product": product,
                "section": section,
                "guide": guide_data,
                "project": None,
                "error": exc.detail,
            })
            return templates.TemplateResponse(
                request,
                "create.html",
                context,
                status_code=exc.status_code if exc.status_code < 500 else 502,
            )

    all_projects = projects(request)
    all_projects[project_key(slug, section_slug)] = {
        "slug": slug,
        "section_slug": section_slug,
        "title": guide_data["title"],
        "need": need,
        "choice": choice or "Belum dipilih",
        "deliverables": guide_data["deliverables"],
        "steps": product_steps(slug),
        "stage": "draft",
        "stage_label": "Rancangan siap diperiksa",
        "revision": "",
        "status_message": "Rancangan awal sudah dibuat berdasarkan kebutuhan Anda.",
    }
    request.session["projects"] = all_projects
    return RedirectResponse(f"/app/{slug}/{section_slug}/project", status_code=303)


@app.get("/app/{slug}/{section_slug}/project", response_class=HTMLResponse)
def project_page(request: Request, slug: str, section_slug: str):
    product = get_product(slug)
    denied = require_product_access(request, slug)
    if denied:
        return denied
    section = get_section(product, section_slug)
    guide_data = get_guide(slug, section_slug)
    current_project_data = current_project(request, slug, section_slug, guide_data)
    if not current_project_data:
        return RedirectResponse(f"/app/{slug}/{section_slug}/create", status_code=303)
    context = base_context(request)
    context.update({"product": product, "section": section, "guide": guide_data, "project": current_project_data})
    return templates.TemplateResponse(request, "project.html", context)


@app.post("/app/{slug}/{section_slug}/project/action")
async def project_action(request: Request, slug: str, section_slug: str):
    product = get_product(slug)
    denied = require_product_access(request, slug)
    if denied:
        return denied
    get_section(product, section_slug)
    form = await request.form()
    action = str(form.get("action", "")).strip()
    revision = str(form.get("revision", "")).strip()

    if settings.core_integration_enabled:
        guide_data = get_guide(slug, section_slug)
        current = current_project(
            request,
            slug,
            section_slug,
            guide_data,
        )
        if not current:
            return RedirectResponse(
                f"/app/{slug}/{section_slug}/create",
                status_code=303,
            )
        input_data = dict(current.get("_input_data") or {})
        output_data = dict(current.get("_output_data") or {})
        status = "draft"

        if (
            slug == "business"
            and section_slug == "operations"
            and settings.business_operations_enabled
            and action in {
                "save_business_profile",
                "add_service",
                "add_lead",
                "update_lead_status",
                "create_booking",
                "schedule_followup",
                "approve_draft",
                "reject_draft",
                "add_reply_template",
                "save_sla_rule",
            }
        ):
            state = normalize_business_operations_state(
                current.get("ai_output")
            )
            record_limit = settings.business_operations_record_limit
            audit_limit = settings.business_operations_audit_limit
            action_message = "Perubahan operasional disimpan."
            ai_error = ""

            if action == "save_business_profile":
                business_name = limited_text(
                    form.get("business_name"),
                    max_length=180,
                )
                if not business_name:
                    raise HTTPException(
                        status_code=400,
                        detail="Nama bisnis wajib diisi.",
                    )
                state["profile"] = {
                    "business_name": business_name,
                    "industry": limited_text(
                        form.get("industry"),
                        max_length=180,
                    ),
                    "admin_name": limited_text(
                        form.get("admin_name"),
                        max_length=180,
                    ),
                    "timezone": limited_text(
                        form.get("timezone"),
                        max_length=80,
                    ) or "Asia/Jakarta",
                    "operating_hours": limited_text(
                        form.get("operating_hours"),
                        max_length=1200,
                    ),
                    "reply_tone": limited_text(
                        form.get("reply_tone"),
                        max_length=500,
                    ),
                    "escalation_rules": limited_text(
                        form.get("escalation_rules"),
                        max_length=1800,
                    ),
                    "updated_at": utc_now_iso(),
                }
                append_business_audit(
                    state,
                    "profile_saved",
                    f"Profil {business_name} diperbarui.",
                    limit=audit_limit,
                )
                action_message = "Profil operasional bisnis disimpan."

            elif action == "add_service":
                service_name = limited_text(
                    form.get("service_name"),
                    max_length=180,
                )
                if not service_name:
                    raise HTTPException(
                        status_code=400,
                        detail="Nama layanan wajib diisi.",
                    )
                services = state["services"]
                service = {
                    "id": (
                        f"service-{current['current_version'] + 1}-"
                        f"{len(services) + 1}"
                    ),
                    "name": service_name,
                    "duration": limited_text(
                        form.get("service_duration"),
                        max_length=180,
                    ),
                    "price_note": limited_text(
                        form.get("service_price_note"),
                        max_length=500,
                    ),
                    "availability": limited_text(
                        form.get("service_availability"),
                        max_length=500,
                    ),
                    "status": "active",
                    "created_at": utc_now_iso(),
                }
                services.append(service)
                state["services"] = services[-record_limit:]
                append_business_audit(
                    state,
                    "service_added",
                    f"Layanan {service_name} ditambahkan.",
                    limit=audit_limit,
                )
                action_message = "Layanan ditambahkan ke katalog."

            elif action == "add_lead":
                lead_name = limited_text(
                    form.get("lead_name"),
                    max_length=180,
                )
                if not lead_name:
                    raise HTTPException(
                        status_code=400,
                        detail="Nama prospek wajib diisi.",
                    )
                contact = limited_text(
                    form.get("lead_contact"),
                    max_length=240,
                )
                lead = {
                    "id": (
                        f"lead-{current['current_version'] + 1}-"
                        f"{len(state['leads']) + 1}"
                    ),
                    "name": lead_name,
                    "contact": contact,
                    "source": limited_text(
                        form.get("lead_source"),
                        max_length=120,
                    ) or "manual",
                    "interest": limited_text(
                        form.get("lead_interest"),
                        max_length=500,
                    ),
                    "notes": limited_text(
                        form.get("lead_notes"),
                        max_length=1800,
                    ),
                    "status": "new",
                    "priority": "medium",
                    "lead_score": 0,
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }

                customer_key = (
                    contact.lower()
                    if contact
                    else lead_name.lower()
                )
                existing_customer = next(
                    (
                        item for item in state["customers"]
                        if isinstance(item, dict)
                        and item.get("customer_key") == customer_key
                    ),
                    None,
                )
                if not existing_customer:
                    state["customers"].append({
                        "id": (
                            f"customer-{current['current_version'] + 1}-"
                            f"{len(state['customers']) + 1}"
                        ),
                        "customer_key": customer_key,
                        "name": lead_name,
                        "contact": contact,
                        "source": lead["source"],
                        "created_at": utc_now_iso(),
                    })
                    state["customers"] = state["customers"][
                        -record_limit:
                    ]

                try:
                    generated = await run_in_threadpool(
                        assist_business_lead,
                        settings,
                        business_context=current["need"],
                        profile=state["profile"],
                        lead=lead,
                    )
                    assist = generated["assist"]
                    lead.update({
                        "priority": assist["priority"],
                        "lead_score": assist["lead_score"],
                        "ai_summary": assist["summary"],
                        "recommended_status": (
                            assist["recommended_status"]
                        ),
                        "next_action": assist["next_action"],
                        "missing_information": (
                            assist["missing_information"]
                        ),
                        "should_escalate": (
                            assist["should_escalate"]
                        ),
                        "escalation_reason": (
                            assist["escalation_reason"]
                        ),
                        "admin_note": assist["admin_note"],
                        "ai_meta": generated["meta"],
                    })
                    lead["sla_due_at"] = compute_sla_due_at(
                        state,
                        assist["priority"],
                        created_at=lead["created_at"],
                    )
                    approval = {
                        "id": (
                            f"approval-{current['current_version'] + 1}-"
                            f"{len(state['approvals']) + 1}"
                        ),
                        "lead_id": lead["id"],
                        "lead_name": lead_name,
                        "type": "follow_up_draft",
                        "content": assist["follow_up_draft"],
                        "suggested_due": assist["suggested_due"],
                        "required_level": (
                            2
                            if assist["priority"] in {"high", "urgent"}
                            or assist["should_escalate"]
                            else 1
                        ),
                        "required_role": (
                            "manager"
                            if assist["priority"] in {"high", "urgent"}
                            or assist["should_escalate"]
                            else "admin"
                        ),
                        "current_level": 0,
                        "status": "pending_admin",
                        "delivery_status": "not_sent",
                        "review_history": [],
                        "sla_due_at": compute_sla_due_at(
                            state,
                            assist["priority"],
                            created_at=lead["created_at"],
                        ),
                        "created_at": utc_now_iso(),
                    }
                    state["approvals"].append(approval)
                    state["approvals"] = state["approvals"][
                        -record_limit:
                    ]
                except BusinessAIError as exc:
                    ai_error = str(exc)
                    lead["ai_error"] = ai_error

                state["leads"].append(lead)
                state["leads"] = state["leads"][-record_limit:]
                append_business_audit(
                    state,
                    "lead_added",
                    f"Prospek {lead_name} ditambahkan.",
                    limit=audit_limit,
                )
                action_message = (
                    "Prospek disimpan dan draft follow-up masuk "
                    "antrean persetujuan."
                    if not ai_error
                    else (
                        "Prospek disimpan. Analisis AI dapat dicoba "
                        "kembali nanti."
                    )
                )

            elif action == "update_lead_status":
                lead_id = limited_text(
                    form.get("lead_id"),
                    max_length=180,
                )
                new_status = limited_text(
                    form.get("lead_status"),
                    max_length=40,
                )
                if new_status not in BUSINESS_PIPELINE_STATUSES:
                    raise HTTPException(
                        status_code=400,
                        detail="Status pipeline tidak valid.",
                    )
                target = next(
                    (
                        item for item in state["leads"]
                        if isinstance(item, dict)
                        and item.get("id") == lead_id
                    ),
                    None,
                )
                if not target:
                    raise HTTPException(
                        status_code=404,
                        detail="Prospek tidak ditemukan.",
                    )
                target["status"] = new_status
                target["updated_at"] = utc_now_iso()
                append_business_audit(
                    state,
                    "lead_status_changed",
                    (
                        f"Status {target.get('name', lead_id)} "
                        f"menjadi {new_status}."
                    ),
                    limit=audit_limit,
                )
                action_message = "Status pipeline diperbarui."

            elif action == "create_booking":
                customer_name = limited_text(
                    form.get("booking_customer"),
                    max_length=180,
                )
                service_name = limited_text(
                    form.get("booking_service"),
                    max_length=180,
                )
                schedule_text = limited_text(
                    form.get("booking_schedule"),
                    max_length=300,
                )
                if not all(
                    (customer_name, service_name, schedule_text)
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Pelanggan, layanan, dan jadwal booking "
                            "wajib diisi."
                        ),
                    )
                booking = {
                    "id": (
                        f"booking-{current['current_version'] + 1}-"
                        f"{len(state['bookings']) + 1}"
                    ),
                    "customer_name": customer_name,
                    "service_name": service_name,
                    "schedule_text": schedule_text,
                    "notes": limited_text(
                        form.get("booking_notes"),
                        max_length=1200,
                    ),
                    "status": "tentative",
                    "confirmation_status": "not_sent",
                    "execution": "simulation_only",
                    "created_at": utc_now_iso(),
                }
                state["bookings"].append(booking)
                state["bookings"] = state["bookings"][
                    -record_limit:
                ]
                append_business_audit(
                    state,
                    "booking_planned",
                    (
                        f"Booking simulasi {customer_name} untuk "
                        f"{service_name} dicatat."
                    ),
                    limit=audit_limit,
                )
                action_message = (
                    "Booking simulasi dicatat; konfirmasi belum dikirim."
                )

            elif action == "schedule_followup":
                target_name = limited_text(
                    form.get("followup_target"),
                    max_length=180,
                )
                due_text = limited_text(
                    form.get("followup_due"),
                    max_length=300,
                )
                draft_message = limited_text(
                    form.get("followup_message"),
                    max_length=2500,
                )
                if not all(
                    (target_name, due_text, draft_message)
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Target, jadwal, dan draft follow-up "
                            "wajib diisi."
                        ),
                    )
                followup = {
                    "id": (
                        f"followup-{current['current_version'] + 1}-"
                        f"{len(state['followups']) + 1}"
                    ),
                    "target_name": target_name,
                    "due_text": due_text,
                    "draft_message": draft_message,
                    "status": "planned_not_sent",
                    "scheduler_connected": False,
                    "delivery_status": "not_sent",
                    "created_at": utc_now_iso(),
                }
                state["followups"].append(followup)
                state["followups"] = state["followups"][
                    -record_limit:
                ]
                append_business_audit(
                    state,
                    "followup_planned",
                    (
                        f"Follow-up untuk {target_name} direncanakan "
                        f"pada {due_text}."
                    ),
                    limit=audit_limit,
                )
                action_message = (
                    "Follow-up disimpan sebagai rencana; belum dijadwalkan "
                    "ke sistem pengiriman."
                )

            elif action == "add_reply_template":
                template_name = limited_text(
                    form.get("template_name"),
                    max_length=180,
                )
                template_content = limited_text(
                    form.get("template_content"),
                    max_length=2500,
                )
                if not template_name or not template_content:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Nama dan isi template wajib diisi."
                        ),
                    )
                template = {
                    "id": (
                        f"template-{current['current_version'] + 1}-"
                        f"{len(state['reply_templates']) + 1}"
                    ),
                    "name": template_name,
                    "category": limited_text(
                        form.get("template_category"),
                        max_length=80,
                    ) or "general",
                    "content": template_content,
                    "status": "active",
                    "created_at": utc_now_iso(),
                    "delivery_status": "not_sent",
                }
                state["reply_templates"].append(template)
                state["reply_templates"] = state[
                    "reply_templates"
                ][-record_limit:]
                append_business_audit(
                    state,
                    "reply_template_added",
                    f"Template {template_name} ditambahkan.",
                    limit=audit_limit,
                )
                action_message = (
                    "Template disimpan dan belum digunakan untuk "
                    "pengiriman otomatis."
                )

            elif action == "save_sla_rule":
                priority = limited_text(
                    form.get("sla_priority"),
                    max_length=20,
                )
                if priority not in {
                    "low",
                    "medium",
                    "high",
                    "urgent",
                }:
                    raise HTTPException(
                        status_code=400,
                        detail="Prioritas SLA tidak valid.",
                    )
                try:
                    target_minutes = int(
                        str(form.get("sla_target_minutes", "")).strip()
                    )
                    approval_level = int(
                        str(form.get("sla_approval_level", "1")).strip()
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="Nilai SLA harus berupa angka.",
                    ) from exc
                if not 1 <= target_minutes <= 10080:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Target SLA harus antara 1 dan 10080 menit."
                        ),
                    )
                approval_level = 2 if approval_level >= 2 else 1
                rule = next(
                    (
                        item for item in state["sla_rules"]
                        if item.get("priority") == priority
                    ),
                    None,
                )
                payload = {
                    "priority": priority,
                    "target_minutes": target_minutes,
                    "approval_level": approval_level,
                    "label": f"{target_minutes} menit",
                    "updated_at": utc_now_iso(),
                }
                if rule is None:
                    state["sla_rules"].append(payload)
                else:
                    rule.update(payload)
                append_business_audit(
                    state,
                    "sla_rule_saved",
                    (
                        f"SLA {priority} menjadi {target_minutes} menit "
                        f"dengan approval level {approval_level}."
                    ),
                    limit=audit_limit,
                )
                action_message = "Aturan SLA diperbarui."

            elif action in {"approve_draft", "reject_draft"}:
                approval_id = limited_text(
                    form.get("approval_id"),
                    max_length=180,
                )
                reviewer_role = limited_text(
                    form.get("reviewer_role"),
                    max_length=20,
                ) or "admin"
                index = next(
                    (
                        idx for idx, item in enumerate(
                            state["approvals"]
                        )
                        if isinstance(item, dict)
                        and item.get("id") == approval_id
                    ),
                    None,
                )
                if index is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Draft approval tidak ditemukan.",
                    )
                try:
                    reviewed = apply_approval_decision(
                        state["approvals"][index],
                        decision=(
                            "approve"
                            if action == "approve_draft"
                            else "reject"
                        ),
                        reviewer_role=reviewer_role,
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=str(exc),
                    ) from exc
                state["approvals"][index] = reviewed
                event = (
                    "draft_approved"
                    if action == "approve_draft"
                    else "draft_rejected"
                )
                action_message = (
                    "Draft masuk approval manager dan tetap tidak dikirim."
                    if reviewed["status"] == "pending_manager"
                    else (
                        "Draft disetujui, tetapi tetap tidak dikirim."
                        if reviewed["status"] == "approved_not_sent"
                        else "Draft ditolak dan tidak dikirim."
                    )
                )
                append_business_audit(
                    state,
                    event,
                    (
                        f"Draft untuk "
                        f"{reviewed.get('lead_name', '')} "
                        f"menjadi {reviewed['status']} oleh "
                        f"{reviewer_role}."
                    ),
                    limit=audit_limit,
                )

            state = normalize_business_operations_state(state)
            output_data["business_operations"] = state
            input_data.update({
                "stage": "testing",
                "stage_label": "Operasional tersimpan",
                "status_message": action_message,
                "ai_error": ai_error,
            })

            try:
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "testing",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )
            except CoreAPIError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.detail,
                ) from exc

            return RedirectResponse(
                "/app/business/operations/project",
                status_code=303,
            )

        if (
            slug == "business"
            and section_slug == "chat"
            and settings.business_ai_enabled
            and action == "simulate_message"
        ):
            customer_message = str(
                form.get("customer_message", "")
            ).strip()
            customer_name = str(
                form.get("customer_name", "")
            ).strip()
            customer_contact = str(
                form.get("customer_contact", "")
            ).strip()

            if not customer_message:
                input_data.update({
                    "stage": "testing",
                    "stage_label": "Pesan simulasi diperlukan",
                    "status_message": (
                        "Masukkan contoh pesan pelanggan untuk diuji."
                    ),
                    "ai_error": (
                        "Pesan pelanggan simulasi belum diisi."
                    ),
                })
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "testing",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )
                return RedirectResponse(
                    "/app/business/chat/project",
                    status_code=303,
                )

            state = current.get("ai_output")
            if not isinstance(state, dict):
                state = {}
            messages = state.get("messages")
            if not isinstance(messages, list):
                messages = []

            previous = [
                {
                    "customer_message": item.get(
                        "customer_message",
                        "",
                    ),
                    "draft_reply": (
                        item.get("analysis", {}).get(
                            "draft_reply",
                            "",
                        )
                        if isinstance(
                            item.get("analysis"),
                            dict,
                        )
                        else ""
                    ),
                }
                for item in messages[-8:]
                if isinstance(item, dict)
            ]

            try:
                generated = await run_in_threadpool(
                    simulate_whatsapp_admin,
                    settings,
                    business_context=current["need"],
                    customer_message=customer_message,
                    customer_name=customer_name,
                    previous_messages=previous,
                )

                message_id = f"sim-{uuid4().hex}"
                record = {
                    "id": message_id,
                    "customer_name": (
                        customer_name or "Pelanggan simulasi"
                    ),
                    "customer_contact": customer_contact,
                    "customer_message": customer_message,
                    "analysis": generated["analysis"],
                    "meta": generated["meta"],
                    "delivery_status": "not_sent",
                }

                if settings.business_workflow_enabled:
                    try:
                        operations_detail = (
                            get_or_create_operations_project(
                                request,
                                business_context=current["need"],
                            )
                        )
                        operations_project = normalize_core_project(
                            operations_detail,
                            "business",
                            "operations",
                            get_guide("business", "operations"),
                        )
                        operations_state, sync_result = (
                            sync_whatsapp_record_to_operations(
                                operations_project.get("ai_output"),
                                record,
                                current_version=int(
                                    operations_project.get(
                                        "current_version",
                                        1,
                                    )
                                ),
                                record_limit=(
                                    settings
                                    .business_operations_record_limit
                                ),
                                audit_limit=(
                                    settings
                                    .business_operations_audit_limit
                                ),
                            )
                        )
                        operations_input = dict(
                            operations_project.get(
                                "_input_data",
                                {},
                            )
                        )
                        operations_output = dict(
                            operations_project.get(
                                "_output_data",
                                {},
                            )
                        )
                        operations_input.update({
                            "stage": "testing",
                            "stage_label": (
                                "WhatsApp simulator tersinkron"
                            ),
                            "status_message": (
                                "Pesan simulasi masuk ke database "
                                "pelanggan, pipeline prospek, dan "
                                "approval queue."
                            ),
                            "ai_error": "",
                        })
                        operations_output[
                            "business_operations"
                        ] = operations_state
                        core_update_project(
                            request,
                            settings,
                            operations_project["id"],
                            {
                                "status": "testing",
                                "input_data": operations_input,
                                "output_data": operations_output,
                            },
                        )
                        record["operations_sync"] = sync_result
                    except (
                        CoreAPIError,
                        ValueError,
                    ) as sync_exc:
                        record["operations_sync"] = {
                            "synced": False,
                            "error": str(sync_exc),
                            "live_sent": False,
                        }
                else:
                    record["operations_sync"] = {
                        "synced": False,
                        "error": "Business Workflow belum diaktifkan.",
                        "live_sent": False,
                    }

                messages.append(record)
                messages = messages[
                    -settings.business_simulation_history_limit:
                ]

                state = {
                    "mode": "simulation",
                    "live_whatsapp_connected": False,
                    "messages": messages,
                    "last_analysis": generated["analysis"],
                    "last_meta": generated["meta"],
                }
                output_data["whatsapp_admin"] = state
                output_data["ai_meta"] = generated["meta"]
                input_data.update({
                    "stage": "testing",
                    "stage_label": "Simulasi AI selesai",
                    "status_message": (
                        "Pesan dianalisis, draft dibuat, dan workflow "
                        "operasional diproses. Tidak ada pesan yang "
                        "dikirim."
                    ),
                    "ai_error": "",
                })
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "testing",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )
            except BusinessAIError as ai_exc:
                input_data.update({
                    "stage": "testing",
                    "stage_label": "Simulasi belum berhasil",
                    "status_message": (
                        "Profil bisnis tetap tersimpan dan simulasi "
                        "dapat dicoba kembali."
                    ),
                    "ai_error": str(ai_exc),
                })
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "testing",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )

            return RedirectResponse(
                "/app/business/chat/project",
                status_code=303,
            )

        if (
            slug == "personal"
            and section_slug in {"creator", "freelancer"}
            and personal_ai_enabled(section_slug)
            and action in {"generate_ai", "revise_ai"}
        ):
            try:
                generated = await run_in_threadpool(
                    generate_personal_plan,
                    section_slug,
                    need=current["need"],
                    choice=current["choice"],
                    revision=revision if action == "revise_ai" else "",
                    current_plan=(
                        current.get("ai_output")
                        if action == "revise_ai"
                        else None
                    ),
                )
                input_data.update({
                    "stage": "review",
                    "stage_label": (
                        "Revisi AI siap diperiksa"
                        if action == "revise_ai"
                        else "Hasil AI siap diperiksa"
                    ),
                    "revision": (
                        revision
                        if action == "revise_ai"
                        else input_data.get("revision", "")
                    ),
                    "status_message": personal_ai_success_message(
                        section_slug,
                        revision=action == "revise_ai",
                    ),
                    "ai_error": "",
                })
                output_data.update({
                    personal_ai_output_key(
                        section_slug
                    ): generated["plan"],
                    "ai_meta": generated["meta"],
                })
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "review",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )
            except PersonalAIError as ai_exc:
                input_data.update({
                    "stage": "draft",
                    "stage_label": "AI belum berhasil",
                    "status_message": (
                        "Proyek tetap aman. Coba kembali setelah provider "
                        "AI tersedia."
                    ),
                    "ai_error": str(ai_exc),
                })
                core_update_project(
                    request,
                    settings,
                    current["id"],
                    {
                        "status": "draft",
                        "input_data": input_data,
                        "output_data": output_data,
                    },
                )
            return RedirectResponse(
                f"/app/{slug}/{section_slug}/project",
                status_code=303,
            )

        if action == "revise":
            input_data.update({
                "stage": "revision",
                "stage_label": "Revisi tersimpan",
                "revision": revision,
                "status_message": "Masukan revisi disimpan sebagai versi baru proyek.",
            })
            status = "review"
        elif action == "test":
            input_data.update({
                "stage": "testing",
                "stage_label": "Siap diuji",
                "status_message": "Skenario uji sudah disiapkan. Eksekusi otomatis belum dijalankan.",
            })
            status = "testing"
        elif action == "ready":
            input_data.update({
                "stage": "ready",
                "stage_label": "Siap diterapkan",
                "status_message": "Rancangan ditandai siap diterapkan setelah integrasi fungsi tersedia.",
            })
            status = "ready"
        else:
            raise HTTPException(status_code=400, detail="Aksi tidak dikenal")
        try:
            core_update_project(
                request,
                settings,
                current["id"],
                {"status": status, "input_data": input_data},
            )
        except CoreAPIError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc
        return RedirectResponse(
            f"/app/{slug}/{section_slug}/project",
            status_code=303,
        )

    all_projects = projects(request)
    key = project_key(slug, section_slug)
    current_project_data = all_projects.get(key)
    if not current_project_data:
        return RedirectResponse(f"/app/{slug}/{section_slug}/create", status_code=303)
    if action == "revise":
        current_project_data["stage"] = "revision"
        current_project_data["stage_label"] = "Revisi tersimpan"
        current_project_data["revision"] = revision
        current_project_data["status_message"] = "Masukan revisi sudah dicatat dan menjadi bagian dari rancangan berikutnya."
    elif action == "test":
        current_project_data["stage"] = "testing"
        current_project_data["stage_label"] = "Siap diuji"
        current_project_data["status_message"] = "Skenario uji candidate sudah disiapkan. Integrasi nyata belum dijalankan."
    elif action == "ready":
        current_project_data["stage"] = "ready"
        current_project_data["stage_label"] = "Siap diterapkan"
        current_project_data["status_message"] = "Rancangan ditandai siap diterapkan setelah integrasi production tersedia."
    else:
        raise HTTPException(status_code=400, detail="Aksi tidak dikenal")
    all_projects[key] = current_project_data
    request.session["projects"] = all_projects
    return RedirectResponse(f"/app/{slug}/{section_slug}/project", status_code=303)


@app.get("/webhook")
def webhook_product(request: Request):
    return RedirectResponse("/choose/webhook", status_code=303)


@app.get("/business", response_class=HTMLResponse)
def business_product(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get(
    "/business/whatsapp-ai-admin",
    response_class=HTMLResponse,
)
def whatsapp_ai_admin_public(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/app/business/operations/export.csv")
def export_business_operations_csv(request: Request):
    denied = require_product_access(request, "business")
    if denied:
        return denied
    current = current_project(
        request,
        "business",
        "operations",
        get_guide("business", "operations"),
    )
    if not current:
        raise HTTPException(
            status_code=404,
            detail="Business Operations belum dibuat.",
        )

    rows = business_operations_csv_rows(
        current.get("ai_output"),
        limit=settings.business_workflow_export_limit,
    )
    fieldnames = [
        "record_type",
        "record_id",
        "name",
        "contact",
        "status",
        "priority",
        "lead_score",
        "detail",
        "delivery_status",
        "created_at",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    filename = (
        "botconnector-business-operations-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".csv"
    )
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
            "X-BotConnector-Execution": "export-only",
        },
    )


@app.get(
    "/business/operations",
    response_class=HTMLResponse,
)
def business_operations_public(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/business/open/operations")
def open_business_operations(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/business/open/whatsapp-ai-admin")
def open_whatsapp_ai_admin(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/personal", response_class=HTMLResponse)
def personal_product(request: Request):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get(
    "/personal/{assistant_slug}",
    response_class=HTMLResponse,
)
def personal_assistant_public(
    request: Request,
    assistant_slug: str,
):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/personal/open/{assistant_slug}")
def open_personal_assistant(
    request: Request,
    assistant_slug: str,
):
    return RedirectResponse("/staging-closed", status_code=303)


@app.get("/monitor")
def monitor_product(request: Request):
    return RedirectResponse("/choose/monitor", status_code=303)


@app.get("/docs", response_class=HTMLResponse)
def docs_page(request: Request):
    context = base_context(request)
    return templates.TemplateResponse(request, "docs.html", context)


def dependency_statuses() -> list[dict[str, Any]]:
    targets = [
        ("platform", "Website & Portal Platform", "Antarmuka web publik, dokumentasi, dan status sistem.", "http://127.0.0.1:8000/health", {"Host": "botconnector-platform-home"}, [200]),
        ("platform", "Akun & Autentikasi (Core API)", "Manajemen akun terpusat, session registry, dan otentikasi aman.", "http://botconnector-backend-api:8050/health", {"Host": "botconnector-backend-api"}, [200]),
        ("products", "Business Suite", "POS kasir, restoran KDS, inventori multi-cabang, dan laporan operasional.", "https://103.58.101.207/bisnis/api/health", {"Host": "botconnector.id"}, [200]),
        ("products", "BotConnector Connect", "Jembatan webhook, eksekusi sinyal TradingView, dan integrasi trading.", "https://103.58.101.207/connect-v2/api/health", {"Host": "botconnector.id"}, [200]),
        ("products", "My Drive", "Penyimpanan berkas cloud terpadu dan manajemen dokumen akun.", "http://botconnector-drive:8000/health", {}, [200]),
        ("integrations", "Integrasi Telegram (V2)", "Notifikasi operasional real-time, ringkasan harian, dan bot pairing.", "https://103.58.101.207/bisnis/api/telegram/health", {"Host": "botconnector.id"}, [200]),
    ]
    results: list[dict[str, Any]] = []
    with httpx.Client(verify=False, timeout=3.0, follow_redirects=True) as client:
        for group, name, desc, url, headers, allowed_codes in targets:
            try:
                response = client.get(url, headers=headers)
                if response.status_code not in allowed_codes:
                    raise ValueError(f"HTTP {response.status_code}")
                results.append({
                    "group": group,
                    "name": name,
                    "description": desc,
                    "ok": True,
                    "status_code": "OPERASIONAL",
                    "label": "Operasional",
                    "badge_class": "live",
                })
            except Exception:
                results.append({
                    "group": group,
                    "name": name,
                    "description": desc,
                    "ok": False,
                    "status_code": "GANGGUAN",
                    "label": "Perlu Pemeriksaan",
                    "badge_class": "soon",
                })
    return results


@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request):
    context = base_context(request)
    services = dependency_statuses()
    context.update({
        "services": services,
        "platform_services": [s for s in services if s["group"] == "platform"],
        "product_services": [s for s in services if s["group"] == "products"],
        "integration_services": [s for s in services if s["group"] == "integrations"],
        "overall_ok": all(bool(item["ok"]) for item in services),
        "checked_at": datetime.now(timezone.utc),
    })
    return templates.TemplateResponse(request, "status.html", context)


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    context = base_context(request)
    return templates.TemplateResponse(request, "privacy.html", context)


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    context = base_context(request)
    return templates.TemplateResponse(request, "terms.html", context)


@app.get("/security", response_class=HTMLResponse)
def security_page(request: Request):
    context = base_context(request)
    return templates.TemplateResponse(request, "security.html", context)


@app.get("/api/status")
def api_status():
    services = dependency_statuses()
    safe_services = [
        {
            "group": s["group"],
            "name": s["name"],
            "description": s["description"],
            "status": s["status_code"],
            "label": s["label"],
        }
        for s in services
    ]
    return {
        "ok": all(bool(item["ok"]) for item in services),
        "status": "OPERASIONAL" if all(bool(item["ok"]) for item in services) else "GANGGUAN",
        "service": "botconnector-platform",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": safe_services,
    }


# ============================================================
# BOTCONNECTOR_SUPPORT_CENTER_V1
# ============================================================
from app.support import (
    ticket_mgr,
    validate_ticket_data,
    send_user_acknowledgement,
    send_admin_notification,
    get_security_txt_content,
    check_redis_rate_limit,
    TicketCategory,
    TicketStatus,
    TicketPriority,
)

CATEGORY_PARAM_MAP = {
    'privacy': TicketCategory.PRIVACY_REQUEST.value,
    'privacy_request': TicketCategory.PRIVACY_REQUEST.value,
    'security': TicketCategory.SECURITY_REPORT.value,
    'security_report': TicketCategory.SECURITY_REPORT.value,
    'general': TicketCategory.GENERAL.value,
    'account': TicketCategory.ACCOUNT_LOGIN.value,
    'account_login': TicketCategory.ACCOUNT_LOGIN.value,
    'business': TicketCategory.BUSINESS_SUITE.value,
    'business_suite': TicketCategory.BUSINESS_SUITE.value,
    'connect': TicketCategory.CONNECT.value,
    'drive': TicketCategory.MY_DRIVE.value,
    'my_drive': TicketCategory.MY_DRIVE.value,
    'telegram': TicketCategory.TELEGRAM.value,
    'other': TicketCategory.OTHER.value,
}

@app.get("/support", response_class=HTMLResponse)
def support_page_get(request: Request):
    context = base_context(request)
    current_user = core_current_user(request, settings)
    user_id = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
    
    raw_cat = (request.query_params.get("category") or "").strip().lower()
    selected_cat = CATEGORY_PARAM_MAP.get(raw_cat, "GENERAL")
    
    tickets = ticket_mgr.get_user_tickets(user_id) if user_id else []
    context.update({
        "selected_category": selected_cat,
        "tickets": tickets,
        "is_logged_in": bool(current_user),
    })
    return templates.TemplateResponse(request, "support.html", context)


@app.post("/support")
async def support_page_post(request: Request):
    current_user = core_current_user(request, settings)
    user_id = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    # Redis rate limit check (20 per minute)
    if not check_redis_rate_limit(client_ip, action="create_ticket", limit=20, window_seconds=60):
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"success": False, "message": "Terlalu banyak permintaan. Silakan tunggu beberapa saat."}, status_code=429)
        context = base_context(request)
        context.update({"error_message": "Terlalu banyak permintaan. Silakan tunggu beberapa saat."})
        return templates.TemplateResponse(request, "support.html", context, status_code=429)

    is_json = "application/json" in request.headers.get("content-type", "")
    if is_json:
        try:
            form_data = await request.json()
        except Exception:
            form_data = {}
    else:
        form_data_raw = await request.form()
        form_data = dict(form_data_raw)

    errors = validate_ticket_data(form_data)
    if errors:
        if is_json:
            return JSONResponse({"success": False, "message": "Data tidak valid: " + ", ".join(errors), "errors": errors}, status_code=400)
        context = base_context(request)
        context.update({
            "error_message": ", ".join(errors),
            "form_data": form_data,
            "selected_category": form_data.get("category", "GENERAL"),
            "tickets": ticket_mgr.get_user_tickets(user_id) if user_id else [],
            "is_logged_in": bool(current_user),
        })
        return templates.TemplateResponse(request, "support.html", context, status_code=400)

    ticket_id, public_reference = ticket_mgr.create_ticket(form_data, user_id=user_id)
    ticket = ticket_mgr.get_ticket(ticket_id)
    if ticket:
        send_user_acknowledgement(ticket)
        send_admin_notification(ticket)

    if is_json:
        return JSONResponse({
            "success": True,
            "message": "Permintaan bantuan Anda telah berhasil diterima. Simpan nomor referensi ini untuk korespondensi.",
            "reference": public_reference,
            "ticket": {
                "id": ticket_id,
                "public_reference": public_reference,
                "category": form_data.get("category"),
                "subject": form_data.get("subject"),
                "status": "OPEN",
                "created_at": ticket.created_at if ticket else datetime.now(timezone.utc).isoformat(),
            }
        }, status_code=200)

    context = base_context(request)
    context.update({
        "public_reference": public_reference,
        "selected_category": form_data.get("category", "GENERAL"),
        "tickets": ticket_mgr.get_user_tickets(user_id) if user_id else [],
        "is_logged_in": bool(current_user),
    })
    return templates.TemplateResponse(request, "support.html", context)


@app.get("/support/tickets")
def support_tickets_list(request: Request):
    current_user = core_current_user(request, settings)
    if not current_user:
        return JSONResponse({"success": False, "message": "Autentikasi diperlukan"}, status_code=401)
    user_id = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
    tickets = ticket_mgr.get_user_tickets(user_id)
    return JSONResponse({
        "success": True,
        "tickets": [
            {
                "id": t.id,
                "public_reference": t.public_reference,
                "category": t.category,
                "subject": t.subject,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tickets
        ],
        "total": len(tickets)
    })


@app.get("/support/ticket/{public_reference}")
def support_ticket_detail(public_reference: str, request: Request):
    current_user = core_current_user(request, settings)
    if not current_user:
        return JSONResponse({"success": False, "message": "Autentikasi diperlukan untuk melihat detail tiket"}, status_code=401)
    user_id = current_user.get("email") if isinstance(current_user, dict) else getattr(current_user, "email", None)
    
    ticket = ticket_mgr.get_ticket_by_reference(public_reference) or ticket_mgr.get_ticket(public_reference)
    if not ticket:
        return JSONResponse({"success": False, "message": "Tiket tidak ditemukan"}, status_code=404)
        
    if ticket.user_id != user_id:
        return JSONResponse({"success": False, "message": "Akses ditolak: Anda bukan pemilik tiket ini"}, status_code=403)
        
    messages = ticket_mgr.get_ticket_messages(ticket.id)
    return JSONResponse({
        "success": True,
        "ticket": {
            "id": ticket.id,
            "public_reference": ticket.public_reference,
            "requester_name": ticket.requester_name,
            "requester_email": ticket.requester_email,
            "category": ticket.category,
            "product_context": ticket.product_context,
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "resolved_at": ticket.resolved_at,
            "messages": [
                {
                    "id": m.id,
                    "sender_type": m.sender_type,
                    "sender_id": m.sender_id,
                    "message": m.message,
                    "created_at": m.created_at
                }
                for m in messages
            ]
        }
    })


@app.post("/api/support/tickets")
async def api_create_support_ticket(request: Request):
    return await support_page_post(request)


@app.get("/api/support/tickets")
def api_get_support_tickets(request: Request):
    return support_tickets_list(request)


@app.get("/api/support/tickets/{identifier}")
def api_get_single_support_ticket(identifier: str, request: Request):
    return support_ticket_detail(identifier, request)


@app.get("/.well-known/security.txt", response_class=PlainTextResponse)
def well_known_security_txt():
    content = get_security_txt_content()
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")



# ============================================================
# BOTCONNECTOR_PRESENTATION_PROJECTS_API_V1
#
# Account-bound PowerPoint project persistence.
#
# Security:
# - bc_session remains on botconnector.id
# - Studio calls credentialed API on botconnector.id
# - exact allowed origin: studio.botconnector.id
# - mutations require dedicated CSRF token
#
# Storage:
# /var/lib/botconnector-platform/
# presentation-projects.sqlite3
# ============================================================

import sqlite3 as _ppt_sqlite3
import json as _ppt_json
import uuid as _ppt_uuid
import secrets as _ppt_secrets

from datetime import (
    datetime as _ppt_datetime,
    timezone as _ppt_timezone,
)

from pathlib import (
    Path as _ppt_Path,
)


_PPT_PROJECT_ORIGIN = (
    "https://studio.botconnector.id"
)

_PPT_PLATFORM_ORIGIN = (
    "https://botconnector.id"
)

_PPT_PROJECT_DB = _ppt_Path(
    "/var/lib/botconnector-platform/"
    "presentation-projects.sqlite3"
)

_PPT_PROJECT_MAX_BYTES = (
    6 * 1024 * 1024
)

_PPT_PROJECT_MAX_PER_USER = 200


def _ppt_now() -> str:
    return (
        _ppt_datetime.now(
            _ppt_timezone.utc
        )
        .isoformat()
    )


def _ppt_project_headers(
    request: Request,
) -> dict[str, str]:

    origin = (
        request.headers.get(
            "origin",
            "",
        )
        .strip()
    )

    headers = {
        "Vary": "Origin",
        "Cache-Control": "no-store",
    }

    if (
        origin
        == _PPT_PROJECT_ORIGIN
    ):

        headers.update(
            {
                "Access-Control-Allow-Origin":
                    _PPT_PROJECT_ORIGIN,

                "Access-Control-Allow-Credentials":
                    "true",
            }
        )

    return headers


def _ppt_project_response(
    request: Request,
    payload: dict,
    status_code: int = 200,
) -> Response:

    return Response(
        content=_ppt_json.dumps(
            payload,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ),
        status_code=status_code,
        media_type="application/json",
        headers=_ppt_project_headers(
            request
        ),
    )


def _ppt_project_origin_ok(
    request: Request,
    *,
    mutation: bool = False,
) -> bool:

    origin = (
        request.headers.get(
            "origin",
            "",
        )
        .strip()
    )

    if mutation:
        return origin in {
            _PPT_PROJECT_ORIGIN,
            _PPT_PLATFORM_ORIGIN,
        }

    return (
        not origin
        or origin
        in {
            _PPT_PROJECT_ORIGIN,
            _PPT_PLATFORM_ORIGIN,
        }
    )


def _ppt_project_user(
    request: Request,
):

    user = current_user(
        request
    )

    if not isinstance(
        user,
        dict,
    ):
        return None

    user_id = str(
        user.get(
            "id",
            "",
        )
    ).strip()

    if not user_id:
        return None

    return user


def _ppt_csrf(
    request: Request,
) -> str:

    value = request.session.get(
        "presentation_project_csrf"
    )

    if (
        isinstance(
            value,
            str,
        )
        and len(value) >= 24
    ):
        return value

    value = (
        _ppt_secrets
        .token_urlsafe(32)
    )

    request.session[
        "presentation_project_csrf"
    ] = value

    return value


def _ppt_csrf_valid(
    request: Request,
) -> bool:

    expected = request.session.get(
        "presentation_project_csrf"
    )

    supplied = request.headers.get(
        "x-bc-ppt-csrf",
        "",
    )

    if (
        not isinstance(
            expected,
            str,
        )
        or not expected
        or not supplied
    ):
        return False

    try:

        return (
            _ppt_secrets
            .compare_digest(
                expected,
                supplied,
            )
        )

    except Exception:

        return False


def _ppt_db_connect():

    _PPT_PROJECT_DB.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    db = _ppt_sqlite3.connect(
        str(
            _PPT_PROJECT_DB
        ),
        timeout=20,
    )

    db.row_factory = (
        _ppt_sqlite3.Row
    )

    db.execute(
        "PRAGMA foreign_keys=ON"
    )

    return db


def _ppt_db_init():

    with _ppt_db_connect() as db:

        db.execute(
            "PRAGMA journal_mode=WAL"
        )

        db.execute(
            "PRAGMA synchronous=NORMAL"
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                deck_json TEXT NOT NULL,
                slide_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_projects_user_updated
            ON presentation_projects(
                user_id,
                updated_at DESC
            )
            """
        )


def _ppt_deck_payload(
    deck,
):

    if not isinstance(
        deck,
        dict,
    ):
        raise ValueError(
            "deck harus berupa object"
        )

    slides = deck.get(
        "slides"
    )

    if (
        not isinstance(
            slides,
            list,
        )
        or not slides
    ):
        raise ValueError(
            "deck tidak memiliki slide"
        )

    encoded = (
        _ppt_json.dumps(
            deck,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )
    )

    size = len(
        encoded.encode(
            "utf-8"
        )
    )

    if (
        size
        > _PPT_PROJECT_MAX_BYTES
    ):
        raise ValueError(
            "project terlalu besar; "
            "batas data deck 6 MB"
        )

    return (
        encoded,
        len(slides),
    )


def _ppt_title(
    value,
) -> str:

    title = "Presentasi"

    if isinstance(
        value,
        str,
    ):

        value = (
            " ".join(
                value.split()
            )
            .strip()
        )

        if value:
            title = value

    return title[:200]


_ppt_db_init()


@app.options(
    "/api/presentation/{rest:path}",
    include_in_schema=False,
)
def presentation_projects_options(
    request: Request,
    rest: str,
):

    origin = (
        request.headers.get(
            "origin",
            "",
        )
        .strip()
    )

    if (
        origin
        != _PPT_PROJECT_ORIGIN
    ):

        return Response(
            status_code=403
        )

    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin":
                _PPT_PROJECT_ORIGIN,

            "Access-Control-Allow-Credentials":
                "true",

            "Access-Control-Allow-Methods":
                "GET,POST,PUT,DELETE,OPTIONS",

            "Access-Control-Allow-Headers":
                (
                    "Content-Type,"
                    "X-BC-PPT-CSRF"
                ),

            "Access-Control-Max-Age":
                "600",

            "Vary":
                "Origin",

            "Cache-Control":
                "no-store",
        },
    )


@app.get(
    "/api/presentation/session",
    include_in_schema=False,
)
def presentation_project_session(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "authenticated":
                    False,

                "detail":
                    "login diperlukan",
            },
            401,
        )

    token = _ppt_csrf(
        request
    )

    return _ppt_project_response(
        request,
        {
            "authenticated":
                True,

            "user": {
                "id":
                    str(
                        user.get(
                            "id",
                            "",
                        )
                    ),

                "email":
                    str(
                        user.get(
                            "email",
                            "",
                        )
                    ),
            },

            "csrf":
                token,
        },
    )


@app.get(
    "/api/presentation/projects",
    include_in_schema=False,
)
def presentation_projects_list(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )

    user_id = str(
        user["id"]
    )

    try:

        limit = int(
            request
            .query_params
            .get(
                "limit",
                "40",
            )
        )

    except Exception:

        limit = 40

    limit = max(
        1,
        min(
            100,
            limit,
        ),
    )

    with _ppt_db_connect() as db:

        rows = db.execute(
            """
            SELECT
                id,
                title,
                slide_count,
                created_at,
                updated_at
            FROM presentation_projects
            WHERE user_id=?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                user_id,
                limit,
            ),
        ).fetchall()

    projects = [
        {
            "id":
                row["id"],

            "title":
                row["title"],

            "slide_count":
                row[
                    "slide_count"
                ],

            "created_at":
                row[
                    "created_at"
                ],

            "updated_at":
                row[
                    "updated_at"
                ],
        }
        for row in rows
    ]

    return _ppt_project_response(
        request,
        {
            "projects":
                projects
        },
    )


@app.post(
    "/api/presentation/projects",
    include_in_schema=False,
)
async def presentation_project_create(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )

    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )

    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )

    try:

        deck_json, slide_count = (
            _ppt_deck_payload(
                body.get(
                    "deck"
                )
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )

    user_id = str(
        user["id"]
    )

    with _ppt_db_connect() as db:

        count = db.execute(
            """
            SELECT COUNT(*) AS n
            FROM presentation_projects
            WHERE user_id=?
            """,
            (
                user_id,
            ),
        ).fetchone()["n"]

        if (
            count
            >= _PPT_PROJECT_MAX_PER_USER
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "batas project tercapai"
                },
                409,
            )

        project_id = str(
            _ppt_uuid.uuid4()
        )

        now = _ppt_now()

        title = _ppt_title(
            body.get(
                "title"
            )
        )

        db.execute(
            """
            INSERT INTO presentation_projects(
                id,
                user_id,
                title,
                deck_json,
                slide_count,
                created_at,
                updated_at
            )
            VALUES(
                ?,?,?,?,?,?,?
            )
            """,
            (
                project_id,
                user_id,
                title,
                deck_json,
                slide_count,
                now,
                now,
            ),
        )

    return _ppt_project_response(
        request,
        {
            "project": {
                "id":
                    project_id,

                "title":
                    title,

                "slide_count":
                    slide_count,

                "created_at":
                    now,

                "updated_at":
                    now,
            }
        },
        201,
    )


@app.get(
    "/api/presentation/projects/{project_id}",
    include_in_schema=False,
)
def presentation_project_get(
    project_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )

    with _ppt_db_connect() as db:

        row = db.execute(
            """
            SELECT
                id,
                title,
                deck_json,
                slide_count,
                created_at,
                updated_at
            FROM presentation_projects
            WHERE id=?
              AND user_id=?
            """,
            (
                project_id,
                str(
                    user["id"]
                ),
            ),
        ).fetchone()

    if row is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "project tidak ditemukan"
            },
            404,
        )

    return _ppt_project_response(
        request,
        {
            "project": {
                "id":
                    row["id"],

                "title":
                    row["title"],

                "deck":
                    _ppt_json.loads(
                        row[
                            "deck_json"
                        ]
                    ),

                "slide_count":
                    row[
                        "slide_count"
                    ],

                "created_at":
                    row[
                        "created_at"
                    ],

                "updated_at":
                    row[
                        "updated_at"
                    ],
            }
        },
    )


@app.put(
    "/api/presentation/projects/{project_id}",
    include_in_schema=False,
)
async def presentation_project_update(
    project_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )

    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )

    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )

    try:

        deck_json, slide_count = (
            _ppt_deck_payload(
                body.get(
                    "deck"
                )
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )

    title = _ppt_title(
        body.get(
            "title"
        )
    )

    updated_at = _ppt_now()

    with _ppt_db_connect() as db:

        cursor = db.execute(
            """
            UPDATE presentation_projects
            SET
                title=?,
                deck_json=?,
                slide_count=?,
                updated_at=?
            WHERE id=?
              AND user_id=?
            """,
            (
                title,
                deck_json,
                slide_count,
                updated_at,
                project_id,
                str(
                    user["id"]
                ),
            ),
        )

        if cursor.rowcount != 1:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "project tidak ditemukan"
                },
                404,
            )

    return _ppt_project_response(
        request,
        {
            "project": {
                "id":
                    project_id,

                "title":
                    title,

                "slide_count":
                    slide_count,

                "updated_at":
                    updated_at,
            }
        },
    )


@app.delete(
    "/api/presentation/projects/{project_id}",
    include_in_schema=False,
)
def presentation_project_delete(
    project_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )

    user = _ppt_project_user(
        request
    )

    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )

    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )

    with _ppt_db_connect() as db:

        cursor = db.execute(
            """
            DELETE FROM presentation_projects
            WHERE id=?
              AND user_id=?
            """,
            (
                project_id,
                str(
                    user["id"]
                ),
            ),
        )

    if cursor.rowcount != 1:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "project tidak ditemukan"
            },
            404,
        )

    return _ppt_project_response(
        request,
        {
            "ok":
                True
        },
    )



# ============================================================
# BOTCONNECTOR_PRESENTATION_BRAND_PROFILE_V1
#
# Account-bound presentation Brand Profile.
#
# V1:
# - Brand name
# - Primary / secondary / accent colors
# - Heading font
# - Body font
# - PNG / JPEG / WEBP logo
#
# V1 intentionally does NOT modify existing decks.
# P2.6B will apply the saved profile to presentations.
# ============================================================

import base64 as _ppt_brand_base64
import binascii as _ppt_brand_binascii
import re as _ppt_brand_re


_PPT_BRAND_MAX_LOGO_BYTES = (
    2 * 1024 * 1024
)


_PPT_BRAND_FONTS = {
    "Aptos",
    "Arial",
    "Calibri",
    "Georgia",
    "Tahoma",
    "Times New Roman",
    "Trebuchet MS",
    "Verdana",
}


_PPT_BRAND_DEFAULTS = {
    "brand_name": "",
    "primary_color": "#3157FF",
    "secondary_color": "#15171B",
    "accent_color": "#22C55E",
    "heading_font": "Aptos",
    "body_font": "Aptos",
}


_PPT_BRAND_COLOR_RE = (
    _ppt_brand_re.compile(
        r"^#[0-9A-Fa-f]{6}$"
    )
)


def _ppt_brand_db_init():

    with _ppt_db_connect() as db:

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_brand_profiles (
                user_id TEXT PRIMARY KEY,
                brand_name TEXT NOT NULL,
                primary_color TEXT NOT NULL,
                secondary_color TEXT NOT NULL,
                accent_color TEXT NOT NULL,
                heading_font TEXT NOT NULL,
                body_font TEXT NOT NULL,
                logo_mime TEXT,
                logo_blob BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _ppt_brand_color(
    value,
    field: str,
) -> str:

    value = str(
        value or ""
    ).strip()

    if not _PPT_BRAND_COLOR_RE.match(
        value
    ):
        raise ValueError(
            f"{field} harus berupa hex #RRGGBB"
        )

    return value.upper()


def _ppt_brand_font(
    value,
    field: str,
) -> str:

    value = str(
        value or ""
    ).strip()

    if value not in _PPT_BRAND_FONTS:
        raise ValueError(
            f"{field} tidak didukung"
        )

    return value


def _ppt_brand_name(
    value,
) -> str:

    name = " ".join(
        str(
            value or ""
        ).split()
    ).strip()

    if not name:
        raise ValueError(
            "nama brand wajib diisi"
        )

    if len(name) > 120:
        raise ValueError(
            "nama brand maksimal 120 karakter"
        )

    return name


def _ppt_brand_logo_decode(
    data_url,
):

    if not isinstance(
        data_url,
        str,
    ):
        raise ValueError(
            "logo tidak valid"
        )

    match = _ppt_brand_re.match(
        r"^data:"
        r"(image/(?:png|jpeg|webp));"
        r"base64,"
        r"([A-Za-z0-9+/=\r\n]+)$",
        data_url,
        flags=_ppt_brand_re.I,
    )

    if not match:
        raise ValueError(
            "logo harus PNG, JPEG, atau WEBP"
        )

    mime = (
        match.group(1)
        .lower()
    )

    try:

        blob = (
            _ppt_brand_base64.b64decode(
                match.group(2),
                validate=True,
            )
        )

    except (
        ValueError,
        _ppt_brand_binascii.Error,
    ) as exc:

        raise ValueError(
            "data logo rusak"
        ) from exc


    if not blob:
        raise ValueError(
            "logo kosong"
        )


    if (
        len(blob)
        > _PPT_BRAND_MAX_LOGO_BYTES
    ):
        raise ValueError(
            "logo maksimal 2 MB"
        )


    if mime == "image/png":

        if not blob.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise ValueError(
                "signature PNG tidak valid"
            )


    elif mime == "image/jpeg":

        if not blob.startswith(
            b"\xff\xd8\xff"
        ):
            raise ValueError(
                "signature JPEG tidak valid"
            )


    elif mime == "image/webp":

        if not (
            len(blob) >= 12
            and blob[:4] == b"RIFF"
            and blob[8:12] == b"WEBP"
        ):
            raise ValueError(
                "signature WEBP tidak valid"
            )


    return mime, blob


def _ppt_brand_logo_data_url(
    mime,
    blob,
):

    if not mime or not blob:
        return None

    encoded = (
        _ppt_brand_base64
        .b64encode(blob)
        .decode("ascii")
    )

    return (
        f"data:{mime};base64,"
        + encoded
    )


def _ppt_brand_row_payload(
    row,
):

    if row is None:

        return {
            **_PPT_BRAND_DEFAULTS,
            "logo_data_url": None,
            "created_at": None,
            "updated_at": None,
            "exists": False,
        }


    return {
        "brand_name":
            row["brand_name"],

        "primary_color":
            row["primary_color"],

        "secondary_color":
            row["secondary_color"],

        "accent_color":
            row["accent_color"],

        "heading_font":
            row["heading_font"],

        "body_font":
            row["body_font"],

        "logo_data_url":
            _ppt_brand_logo_data_url(
                row["logo_mime"],
                row["logo_blob"],
            ),

        "created_at":
            row["created_at"],

        "updated_at":
            row["updated_at"],

        "exists":
            True,
    }


_ppt_brand_db_init()


@app.get(
    "/api/presentation/brand",
    include_in_schema=False,
)
def presentation_brand_get(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    with _ppt_db_connect() as db:

        row = db.execute(
            """
            SELECT
                user_id,
                brand_name,
                primary_color,
                secondary_color,
                accent_color,
                heading_font,
                body_font,
                logo_mime,
                logo_blob,
                created_at,
                updated_at
            FROM presentation_brand_profiles
            WHERE user_id=?
            """,
            (
                str(
                    user["id"]
                ),
            ),
        ).fetchone()


    return _ppt_project_response(
        request,
        {
            "profile":
                _ppt_brand_row_payload(
                    row
                ),

            "allowed_fonts":
                sorted(
                    _PPT_BRAND_FONTS
                ),
        },
    )


@app.put(
    "/api/presentation/brand",
    include_in_schema=False,
)
async def presentation_brand_put(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        brand_name = (
            _ppt_brand_name(
                body.get(
                    "brand_name"
                )
            )
        )

        primary_color = (
            _ppt_brand_color(
                body.get(
                    "primary_color"
                ),
                "primary_color",
            )
        )

        secondary_color = (
            _ppt_brand_color(
                body.get(
                    "secondary_color"
                ),
                "secondary_color",
            )
        )

        accent_color = (
            _ppt_brand_color(
                body.get(
                    "accent_color"
                ),
                "accent_color",
            )
        )

        heading_font = (
            _ppt_brand_font(
                body.get(
                    "heading_font"
                ),
                "heading_font",
            )
        )

        body_font = (
            _ppt_brand_font(
                body.get(
                    "body_font"
                ),
                "body_font",
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        existing = db.execute(
            """
            SELECT
                logo_mime,
                logo_blob,
                created_at
            FROM presentation_brand_profiles
            WHERE user_id=?
            """,
            (
                user_id,
            ),
        ).fetchone()


        logo_mime = (
            existing["logo_mime"]
            if existing
            else None
        )

        logo_blob = (
            existing["logo_blob"]
            if existing
            else None
        )


        if (
            body.get(
                "remove_logo"
            )
            is True
        ):

            logo_mime = None
            logo_blob = None


        elif body.get(
            "logo_data_url"
        ):

            try:

                (
                    logo_mime,
                    logo_blob,
                ) = (
                    _ppt_brand_logo_decode(
                        body[
                            "logo_data_url"
                        ]
                    )
                )

            except ValueError as exc:

                return _ppt_project_response(
                    request,
                    {
                        "detail":
                            str(exc)
                    },
                    400,
                )


        now = _ppt_now()


        created_at = (
            existing["created_at"]
            if existing
            else now
        )


        db.execute(
            """
            INSERT INTO
            presentation_brand_profiles(
                user_id,
                brand_name,
                primary_color,
                secondary_color,
                accent_color,
                heading_font,
                body_font,
                logo_mime,
                logo_blob,
                created_at,
                updated_at
            )
            VALUES(
                ?,?,?,?,?,?,?,?,?,?,?
            )
            ON CONFLICT(user_id)
            DO UPDATE SET
                brand_name=excluded.brand_name,
                primary_color=excluded.primary_color,
                secondary_color=excluded.secondary_color,
                accent_color=excluded.accent_color,
                heading_font=excluded.heading_font,
                body_font=excluded.body_font,
                logo_mime=excluded.logo_mime,
                logo_blob=excluded.logo_blob,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                brand_name,
                primary_color,
                secondary_color,
                accent_color,
                heading_font,
                body_font,
                logo_mime,
                logo_blob,
                created_at,
                now,
            ),
        )


        row = db.execute(
            """
            SELECT
                user_id,
                brand_name,
                primary_color,
                secondary_color,
                accent_color,
                heading_font,
                body_font,
                logo_mime,
                logo_blob,
                created_at,
                updated_at
            FROM presentation_brand_profiles
            WHERE user_id=?
            """,
            (
                user_id,
            ),
        ).fetchone()


    return _ppt_project_response(
        request,
        {
            "ok":
                True,

            "profile":
                _ppt_brand_row_payload(
                    row
                ),
        },
    )


# END BOTCONNECTOR_PRESENTATION_BRAND_PROFILE_V1


# END BOTCONNECTOR_PRESENTATION_PROJECTS_API_V1


@app.get("/api/auth/check", include_in_schema=False)
def auth_check(request: Request):
    user = current_user(request)

    if not isinstance(user, dict):
        return Response(status_code=401)

    user_id = str(user.get("id", "")).strip()

    if not user_id:
        return Response(status_code=401)

    return Response(
        status_code=204,
        headers={
            "X-BotConnector-User-ID": user_id,
        },
    )


@app.get("/health")
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "botconnector-platform-home",
        "version": "0.15.4",
        "creator_ai": (
            "enabled" if settings.creator_ai_enabled else "disabled"
        ),
        "freelancer_ai": (
            "enabled" if settings.freelancer_ai_enabled else "disabled"
        ),
        "business_ai": (
            "enabled" if settings.business_ai_enabled else "disabled"
        ),
        "business_operations": (
            "enabled"
            if settings.business_operations_enabled
            else "disabled"
        ),
        "business_workflow": (
            "enabled"
            if settings.business_workflow_enabled
            else "disabled"
        ),
        "whatsapp_operations_sync": (
            "enabled"
            if settings.business_workflow_enabled
            else "disabled"
        ),
        "live_whatsapp": "disabled",
        "automatic_booking": "disabled",
        "automatic_followup": "disabled",
    }


@app.get("/api/public-products")
def api_public_products():
    return [
        {
            "slug": product["slug"],
            "name": product["name"],
            "short_name": product["short_name"],
            "summary": product["summary"],
            "short_summary": product["short_summary"],
            "category": product["category"],
            "public_url": product["public_url"],
            "status": product["status"],
            "requires_auth": product["requires_auth"],
            "capabilities": product["capabilities"],
        }
        for product in PUBLIC_PRODUCTS
    ]


@app.get("/api/products")
def api_products():
    return [
        {
            "slug": product["slug"],
            "name": product["name"],
            "summary": product["summary"],
            "status": product["status"],
            "choose_url": product.get("direct_url", f"/choose/{product['slug']}"),
            "public_url": (
                product["direct_url"]
                if product.get("direct_url")
                else "/personal"
                if product["slug"] == "personal"
                else f"/choose/{product['slug']}"
            ),
        }
        for product in PRODUCTS
    ]

# BOTCONNECTOR_AUTOMATION_PROXY_V0155
from app.automation_proxy import install_automation_proxy

install_automation_proxy(
    app,
    current_user=current_user,
    require_product_access=require_product_access,
)

# BOTCONNECTOR_PUBLIC_TRIAL_V0157
from app.public_trial import install_public_trial

install_public_trial(
    app,
    templates=templates,
    base_context=base_context,
)

# BOTCONNECTOR_WEBSITE_V0160_CREATOR_VISUAL
try:
    from .creator_visual import (
        install_creator_visual_routes,
    )
except ImportError:
    from creator_visual import (
        install_creator_visual_routes,
    )

install_creator_visual_routes(app)

# BOTCONNECTOR_WEBSITE_V0164_VISUAL_WIZARD
try:
    from .visual_wizard import (
        install_visual_wizard_routes,
    )
except ImportError:
    from visual_wizard import (
        install_visual_wizard_routes,
    )

install_visual_wizard_routes(app)

# SMARTBIZ_DASHBOARD_V0_3_BEGIN
from app.smartbiz_dashboard import register_smartbiz_dashboard
register_smartbiz_dashboard(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
    core_api_request=core_api_request,
    CoreAPIError=CoreAPIError,
    base_context=base_context,
)
# SMARTBIZ_DASHBOARD_V0_3_END

# SMARTBIZ_OPERATIONS_UI_V0_4_BEGIN
from app.smartbiz_operations_ui import register_smartbiz_operations
register_smartbiz_operations(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
    core_api_request=core_api_request,
    CoreAPIError=CoreAPIError,
    base_context=base_context,
)
# SMARTBIZ_OPERATIONS_UI_V0_4_END


register_staging_control(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
    base_context=base_context,
)

# SMARTBIZ_AI_STUDIO_PLATFORM_V075
from app.smartbiz_ai_studio import register_smartbiz_ai_studio

register_smartbiz_ai_studio(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
    core_api_request=core_api_request,
    CoreAPIError=CoreAPIError,
    base_context=base_context,
)

# BOTCONNECTOR_DRIVE_UI_V010_BEGIN
from app.drive_ui import register_drive_ui

register_drive_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)
# BOTCONNECTOR_DRIVE_UI_V010_END

# BOTCONNECTOR_GOOGLE_DRIVE_UI_V010_BEGIN
from .google_drive_ui import (
    register_google_drive_ui,
)

register_google_drive_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)
# BOTCONNECTOR_GOOGLE_DRIVE_UI_V010_END

# BOTCONNECTOR_GOOGLE_SAVE_UI_V010
from .google_drive_save_ui import (
    register_google_drive_save_ui,
)

register_google_drive_save_ui(
    app=app,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_GOOGLE_SHARE_UI_V020
from .google_drive_share_ui import (
    register_google_drive_share_ui,
)

register_google_drive_share_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_GOOGLE_FOLDER_UI_V030
from .google_drive_folder_ui import (
    register_google_drive_folder_ui,
)

register_google_drive_folder_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_DRIVE_SHARED_UI_V010
from .drive_shared_ui import (
    register_drive_shared_ui,
)

register_drive_shared_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)


# BOTCONNECTOR_DRIVE_PUBLIC_SHARE_UI_V010
from .drive_public_share_ui import (
    register_drive_public_share_ui,
)

register_drive_public_share_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_DRIVE_FILE_REQUEST_UI_V010
from .drive_file_request_ui import (
    register_drive_file_request_ui,
)

register_drive_file_request_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_DRIVE_PREVIEW_UI_V010
from .drive_preview_ui import (
    register_drive_preview_ui,
)

register_drive_preview_ui(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)

# BOTCONNECTOR_ADMIN_STORAGE_UI_V010
from .admin_storage import (
    register_admin_storage,
)

register_admin_storage(
    app=app,
    templates=templates,
    settings=settings,
    current_user=current_user,
)


# ============================================================
# BOTCONNECTOR_PRESENTATION_USER_TEMPLATES_V1
#
# Account-bound reusable presentation templates.
#
# Reuses existing:
# - session/current user
# - CSRF
# - CORS
# - project SQLite connection
# - project deck validation
#
# ============================================================


_PPT_USER_TEMPLATE_MAX_PER_USER = 40
_PPT_USER_TEMPLATE_DESCRIPTION_MAX = 500


def _ppt_user_template_db_init():

    with _ppt_db_connect() as db:

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_user_templates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_project_id TEXT,
                template_json TEXT NOT NULL,
                slide_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_user_templates_user_updated
            ON presentation_user_templates(
                user_id,
                updated_at DESC
            )
            """
        )


def _ppt_user_template_description(value):

    value = str(
        value
        if value is not None
        else ""
    ).strip()

    if (
        len(value)
        > _PPT_USER_TEMPLATE_DESCRIPTION_MAX
    ):

        raise ValueError(
            "description terlalu panjang"
        )

    return value


def _ppt_user_template_deck_payload(value):

    if not isinstance(
        value,
        dict,
    ):

        raise ValueError(
            "deck template tidak valid"
        )


    try:

        cloned = _ppt_json.loads(
            _ppt_json.dumps(
                value
            )
        )

    except Exception as exc:

        raise ValueError(
            "deck template tidak valid"
        ) from exc


    cloned.pop(
        "_brand_export_logo_data_url",
        None,
    )


    return _ppt_deck_payload(
        cloned
    )


def _ppt_user_template_has_brand(raw):

    try:

        deck = _ppt_json.loads(
            raw
        )

    except Exception:

        return False


    return isinstance(
        deck.get("_brand"),
        dict,
    )


def _ppt_user_template_meta(row):

    return {
        "id":
            row["id"],

        "title":
            row["title"],

        "description":
            row["description"],

        "source_project_id":
            row["source_project_id"],

        "slide_count":
            row["slide_count"],

        "created_at":
            row["created_at"],

        "updated_at":
            row["updated_at"],

        "has_brand":
            _ppt_user_template_has_brand(
                row["template_json"]
            ),
    }


_ppt_user_template_db_init()


@app.get(
    "/api/presentation/templates"
)
def presentation_user_templates_list(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    try:

        limit = int(
            request.query_params.get(
                "limit",
                "40",
            )
        )

    except Exception:

        limit = 40


    limit = max(
        1,
        min(
            100,
            limit,
        ),
    )


    with _ppt_db_connect() as db:

        rows = db.execute(
            """
            SELECT
                id,
                title,
                description,
                source_project_id,
                template_json,
                slide_count,
                created_at,
                updated_at
            FROM presentation_user_templates
            WHERE user_id=?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                str(
                    user["id"]
                ),
                limit,
            ),
        ).fetchall()


    return _ppt_project_response(
        request,
        {
            "templates": [
                _ppt_user_template_meta(
                    row
                )
                for row in rows
            ]
        },
    )


@app.post(
    "/api/presentation/templates"
)
async def presentation_user_template_create(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        title = _ppt_title(
            body.get("title")
        )

        description = (
            _ppt_user_template_description(
                body.get(
                    "description"
                )
            )
        )

        template_json, slide_count = (
            _ppt_user_template_deck_payload(
                body.get("deck")
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    source_project_id = str(
        body.get(
            "source_project_id"
        )
        or ""
    ).strip() or None


    with _ppt_db_connect() as db:

        if source_project_id:

            source = db.execute(
                """
                SELECT id
                FROM presentation_projects
                WHERE id=?
                  AND user_id=?
                """,
                (
                    source_project_id,
                    user_id,
                ),
            ).fetchone()


            if source is None:

                return _ppt_project_response(
                    request,
                    {
                        "detail":
                            "source project tidak ditemukan"
                    },
                    404,
                )


        count = db.execute(
            """
            SELECT COUNT(*) AS n
            FROM presentation_user_templates
            WHERE user_id=?
            """,
            (
                user_id,
            ),
        ).fetchone()["n"]


        if (
            count
            >= _PPT_USER_TEMPLATE_MAX_PER_USER
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "batas template tercapai"
                },
                409,
            )


        template_id = str(
            _ppt_uuid.uuid4()
        )

        now = _ppt_now()


        db.execute(
            """
            INSERT INTO presentation_user_templates(
                id,
                user_id,
                title,
                description,
                source_project_id,
                template_json,
                slide_count,
                created_at,
                updated_at
            )
            VALUES(
                ?,?,?,?,?,?,?,?,?
            )
            """,
            (
                template_id,
                user_id,
                title,
                description,
                source_project_id,
                template_json,
                slide_count,
                now,
                now,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "template": {
                "id":
                    template_id,

                "title":
                    title,

                "description":
                    description,

                "source_project_id":
                    source_project_id,

                "slide_count":
                    slide_count,

                "created_at":
                    now,

                "updated_at":
                    now,

                "has_brand":
                    _ppt_user_template_has_brand(
                        template_json
                    ),
            }
        },
        201,
    )


@app.get(
    "/api/presentation/templates/{template_id}"
)
def presentation_user_template_get(
    template_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    with _ppt_db_connect() as db:

        row = db.execute(
            """
            SELECT
                id,
                title,
                description,
                source_project_id,
                template_json,
                slide_count,
                created_at,
                updated_at
            FROM presentation_user_templates
            WHERE id=?
              AND user_id=?
            """,
            (
                template_id,
                str(
                    user["id"]
                ),
            ),
        ).fetchone()


    if row is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "template tidak ditemukan"
            },
            404,
        )


    payload = _ppt_user_template_meta(
        row
    )


    payload["deck"] = (
        _ppt_json.loads(
            row["template_json"]
        )
    )


    return _ppt_project_response(
        request,
        {
            "template":
                payload
        },
    )


@app.put(
    "/api/presentation/templates/{template_id}"
)
async def presentation_user_template_update(
    template_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        current = db.execute(
            """
            SELECT
                title,
                description
            FROM presentation_user_templates
            WHERE id=?
              AND user_id=?
            """,
            (
                template_id,
                user_id,
            ),
        ).fetchone()


        if current is None:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "template tidak ditemukan"
                },
                404,
            )


        try:

            title = (
                _ppt_title(
                    body.get("title")
                )
                if "title" in body
                else current["title"]
            )

            description = (
                _ppt_user_template_description(
                    body.get(
                        "description"
                    )
                )
                if "description" in body
                else current["description"]
            )

        except ValueError as exc:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        str(exc)
                },
                400,
            )


        updated_at = _ppt_now()


        db.execute(
            """
            UPDATE presentation_user_templates
            SET
                title=?,
                description=?,
                updated_at=?
            WHERE id=?
              AND user_id=?
            """,
            (
                title,
                description,
                updated_at,
                template_id,
                user_id,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "template": {
                "id":
                    template_id,

                "title":
                    title,

                "description":
                    description,

                "updated_at":
                    updated_at,
            }
        },
    )


@app.delete(
    "/api/presentation/templates/{template_id}"
)
def presentation_user_template_delete(
    template_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    with _ppt_db_connect() as db:

        cursor = db.execute(
            """
            DELETE FROM presentation_user_templates
            WHERE id=?
              AND user_id=?
            """,
            (
                template_id,
                str(
                    user["id"]
                ),
            ),
        )


    if cursor.rowcount != 1:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "template tidak ditemukan"
            },
            404,
        )


    return _ppt_project_response(
        request,
        {
            "ok":
                True
        },
    )


# END BOTCONNECTOR_PRESENTATION_USER_TEMPLATES_V1



# ============================================================
# BOTCONNECTOR_PRESENTATION_TEMPLATE_FAVORITES_V1
#
# Account-bound favorites for:
# - built-in templates
# - user-created My Templates
#
# Independent from presentation_user_templates so P2.7C folders
# can evolve separately later.
# ============================================================


_PPT_TEMPLATE_FAVORITE_KINDS = {
    "builtin",
    "user",
}


_PPT_BUILTIN_TEMPLATE_IDS = frozenset(
    {
        "business-overview",
        "pitch-deck",
        "company-profile",
        "project-proposal",
        "sales-presentation",
        "monthly-report",
        "education-lesson",
        "portfolio",
    }
)


def _ppt_template_favorites_db_init():

    with _ppt_db_connect() as db:

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_template_favorites (
                user_id TEXT NOT NULL,
                template_kind TEXT NOT NULL,
                template_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    user_id,
                    template_kind,
                    template_key
                )
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_template_favorites_user_created
            ON presentation_template_favorites(
                user_id,
                created_at DESC
            )
            """
        )


def _ppt_template_favorite_identity(
    kind,
    key,
):

    kind = str(
        kind
        or ""
    ).strip().lower()

    key = str(
        key
        or ""
    ).strip()


    if (
        kind
        not in _PPT_TEMPLATE_FAVORITE_KINDS
    ):

        raise ValueError(
            "template kind tidak valid"
        )


    if (
        not key
        or len(key) > 180
    ):

        raise ValueError(
            "template key tidak valid"
        )


    return (
        kind,
        key,
    )


def _ppt_template_favorite_target_exists(
    db,
    user_id,
    kind,
    key,
):

    if kind == "builtin":

        return (
            key
            in _PPT_BUILTIN_TEMPLATE_IDS
        )


    row = db.execute(
        """
        SELECT id
        FROM presentation_user_templates
        WHERE id=?
          AND user_id=?
        """,
        (
            key,
            user_id,
        ),
    ).fetchone()


    return (
        row
        is not None
    )


_ppt_template_favorites_db_init()


@app.get(
    "/api/presentation/template-favorites"
)
def presentation_template_favorites_list(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        rows = db.execute(
            """
            SELECT
                template_kind,
                template_key,
                created_at
            FROM presentation_template_favorites
            WHERE user_id=?
            ORDER BY created_at DESC
            """,
            (
                user_id,
            ),
        ).fetchall()


    return _ppt_project_response(
        request,
        {
            "favorites": [
                {
                    "kind":
                        row["template_kind"],

                    "key":
                        row["template_key"],

                    "created_at":
                        row["created_at"],
                }
                for row in rows
            ]
        },
    )


@app.post(
    "/api/presentation/template-favorites"
)
async def presentation_template_favorite_create(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        kind, key = (
            _ppt_template_favorite_identity(
                body.get("kind"),
                body.get("key"),
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    now = _ppt_now()


    with _ppt_db_connect() as db:

        if not _ppt_template_favorite_target_exists(
            db,
            user_id,
            kind,
            key,
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "template tidak ditemukan"
                },
                404,
            )


        db.execute(
            """
            INSERT OR IGNORE INTO
            presentation_template_favorites(
                user_id,
                template_kind,
                template_key,
                created_at
            )
            VALUES(
                ?,?,?,?
            )
            """,
            (
                user_id,
                kind,
                key,
                now,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "favorite": {
                "kind":
                    kind,

                "key":
                    key,

                "created_at":
                    now,
            }
        },
        201,
    )


@app.delete(
    "/api/presentation/template-favorites/{kind}/{template_key}"
)
def presentation_template_favorite_delete(
    kind: str,
    template_key: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        kind, template_key = (
            _ppt_template_favorite_identity(
                kind,
                template_key,
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    with _ppt_db_connect() as db:

        db.execute(
            """
            DELETE FROM
            presentation_template_favorites
            WHERE user_id=?
              AND template_kind=?
              AND template_key=?
            """,
            (
                str(
                    user["id"]
                ),
                kind,
                template_key,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "ok":
                True,

            "kind":
                kind,

            "key":
                template_key,
        },
    )


# END BOTCONNECTOR_PRESENTATION_TEMPLATE_FAVORITES_V1



# ============================================================
# BOTCONNECTOR_PRESENTATION_TEMPLATE_FOLDERS_V1
#
# Flat, account-bound template organization.
#
# A template may belong to multiple folders.
#
# Deleting:
# - membership => does not delete template
# - folder     => does not delete template
#
# Supported targets:
# - builtin template
# - user My Template
# ============================================================


_PPT_TEMPLATE_FOLDER_MAX_PER_USER = 50
_PPT_TEMPLATE_FOLDER_NAME_MAX = 80


def _ppt_template_folders_db_init():

    with _ppt_db_connect() as db:

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_template_folders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_template_folders_user_updated
            ON presentation_template_folders(
                user_id,
                updated_at DESC
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS
            presentation_template_folder_items (
                folder_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                template_kind TEXT NOT NULL,
                template_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    folder_id,
                    user_id,
                    template_kind,
                    template_key
                )
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_template_folder_items_user_folder
            ON presentation_template_folder_items(
                user_id,
                folder_id,
                created_at DESC
            )
            """
        )

        db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_presentation_template_folder_items_user_template
            ON presentation_template_folder_items(
                user_id,
                template_kind,
                template_key
            )
            """
        )


def _ppt_template_folder_name(
    value,
):

    name = str(
        value
        if value is not None
        else ""
    ).strip()


    if not name:

        raise ValueError(
            "nama folder diperlukan"
        )


    if (
        len(name)
        > _PPT_TEMPLATE_FOLDER_NAME_MAX
    ):

        raise ValueError(
            "nama folder terlalu panjang"
        )


    return name


def _ppt_template_folder_row(
    db,
    user_id,
    folder_id,
):

    return db.execute(
        """
        SELECT
            id,
            user_id,
            name,
            created_at,
            updated_at
        FROM presentation_template_folders
        WHERE id=?
          AND user_id=?
        """,
        (
            folder_id,
            user_id,
        ),
    ).fetchone()


def _ppt_template_folder_duplicate(
    db,
    user_id,
    name,
    exclude_id=None,
):

    if exclude_id:

        return db.execute(
            """
            SELECT id
            FROM presentation_template_folders
            WHERE user_id=?
              AND lower(name)=lower(?)
              AND id<>?
            LIMIT 1
            """,
            (
                user_id,
                name,
                exclude_id,
            ),
        ).fetchone()


    return db.execute(
        """
        SELECT id
        FROM presentation_template_folders
        WHERE user_id=?
          AND lower(name)=lower(?)
        LIMIT 1
        """,
        (
            user_id,
            name,
        ),
    ).fetchone()


_ppt_template_folders_db_init()


@app.get(
    "/api/presentation/template-folders"
)
def presentation_template_folders_list(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        folders = db.execute(
            """
            SELECT
                f.id,
                f.name,
                f.created_at,
                f.updated_at,
                COUNT(i.template_key) AS item_count
            FROM presentation_template_folders AS f

            LEFT JOIN
            presentation_template_folder_items AS i
              ON i.folder_id=f.id
             AND i.user_id=f.user_id

            WHERE f.user_id=?

            GROUP BY
                f.id,
                f.name,
                f.created_at,
                f.updated_at

            ORDER BY
                lower(f.name) ASC,
                f.created_at ASC
            """,
            (
                user_id,
            ),
        ).fetchall()


        items = db.execute(
            """
            SELECT
                folder_id,
                template_kind,
                template_key,
                created_at
            FROM presentation_template_folder_items
            WHERE user_id=?
            ORDER BY created_at ASC
            """,
            (
                user_id,
            ),
        ).fetchall()


    return _ppt_project_response(
        request,
        {
            "folders": [
                {
                    "id":
                        row["id"],

                    "name":
                        row["name"],

                    "item_count":
                        int(
                            row["item_count"]
                            or 0
                        ),

                    "created_at":
                        row["created_at"],

                    "updated_at":
                        row["updated_at"],
                }
                for row in folders
            ],

            "memberships": [
                {
                    "folder_id":
                        row["folder_id"],

                    "kind":
                        row["template_kind"],

                    "key":
                        row["template_key"],

                    "created_at":
                        row["created_at"],
                }
                for row in items
            ],
        },
    )


@app.post(
    "/api/presentation/template-folders"
)
async def presentation_template_folder_create(
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        name = _ppt_template_folder_name(
            body.get(
                "name"
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        count = db.execute(
            """
            SELECT COUNT(*) AS n
            FROM presentation_template_folders
            WHERE user_id=?
            """,
            (
                user_id,
            ),
        ).fetchone()["n"]


        if (
            count
            >= _PPT_TEMPLATE_FOLDER_MAX_PER_USER
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "batas folder tercapai"
                },
                409,
            )


        if _ppt_template_folder_duplicate(
            db,
            user_id,
            name,
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "nama folder sudah digunakan"
                },
                409,
            )


        folder_id = str(
            _ppt_uuid.uuid4()
        )

        now = _ppt_now()


        db.execute(
            """
            INSERT INTO
            presentation_template_folders(
                id,
                user_id,
                name,
                created_at,
                updated_at
            )
            VALUES(
                ?,?,?,?,?
            )
            """,
            (
                folder_id,
                user_id,
                name,
                now,
                now,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "folder": {
                "id":
                    folder_id,

                "name":
                    name,

                "item_count":
                    0,

                "created_at":
                    now,

                "updated_at":
                    now,
            }
        },
        201,
    )


@app.put(
    "/api/presentation/template-folders/{folder_id}"
)
async def presentation_template_folder_update(
    folder_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        name = _ppt_template_folder_name(
            body.get(
                "name"
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        current = _ppt_template_folder_row(
            db,
            user_id,
            folder_id,
        )


        if current is None:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "folder tidak ditemukan"
                },
                404,
            )


        if _ppt_template_folder_duplicate(
            db,
            user_id,
            name,
            exclude_id=folder_id,
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "nama folder sudah digunakan"
                },
                409,
            )


        updated_at = _ppt_now()


        db.execute(
            """
            UPDATE presentation_template_folders
            SET
                name=?,
                updated_at=?
            WHERE id=?
              AND user_id=?
            """,
            (
                name,
                updated_at,
                folder_id,
                user_id,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "folder": {
                "id":
                    folder_id,

                "name":
                    name,

                "updated_at":
                    updated_at,
            }
        },
    )


@app.delete(
    "/api/presentation/template-folders/{folder_id}"
)
def presentation_template_folder_delete(
    folder_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        current = _ppt_template_folder_row(
            db,
            user_id,
            folder_id,
        )


        if current is None:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "folder tidak ditemukan"
                },
                404,
            )


        db.execute(
            """
            DELETE FROM
            presentation_template_folder_items
            WHERE folder_id=?
              AND user_id=?
            """,
            (
                folder_id,
                user_id,
            ),
        )


        db.execute(
            """
            DELETE FROM
            presentation_template_folders
            WHERE id=?
              AND user_id=?
            """,
            (
                folder_id,
                user_id,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "ok":
                True,

            "id":
                folder_id,
        },
    )


@app.post(
    "/api/presentation/template-folders/{folder_id}/items"
)
async def presentation_template_folder_item_add(
    folder_id: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        body = await request.json()

    except Exception:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    if not isinstance(
        body,
        dict,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "JSON tidak valid"
            },
            400,
        )


    try:

        kind, key = (
            _ppt_template_favorite_identity(
                body.get(
                    "kind"
                ),
                body.get(
                    "key"
                ),
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        folder = _ppt_template_folder_row(
            db,
            user_id,
            folder_id,
        )


        if folder is None:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "folder tidak ditemukan"
                },
                404,
            )


        if not _ppt_template_favorite_target_exists(
            db,
            user_id,
            kind,
            key,
        ):

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "template tidak ditemukan"
                },
                404,
            )


        now = _ppt_now()


        db.execute(
            """
            INSERT OR IGNORE INTO
            presentation_template_folder_items(
                folder_id,
                user_id,
                template_kind,
                template_key,
                created_at
            )
            VALUES(
                ?,?,?,?,?
            )
            """,
            (
                folder_id,
                user_id,
                kind,
                key,
                now,
            ),
        )


        db.execute(
            """
            UPDATE presentation_template_folders
            SET updated_at=?
            WHERE id=?
              AND user_id=?
            """,
            (
                now,
                folder_id,
                user_id,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "item": {
                "folder_id":
                    folder_id,

                "kind":
                    kind,

                "key":
                    key,

                "created_at":
                    now,
            }
        },
        201,
    )


@app.delete(
    "/api/presentation/template-folders/{folder_id}/items/{kind}/{template_key}"
)
def presentation_template_folder_item_remove(
    folder_id: str,
    kind: str,
    template_key: str,
    request: Request,
):

    if not _ppt_project_origin_ok(
        request,
        mutation=True,
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "origin tidak diizinkan"
            },
            403,
        )


    user = _ppt_project_user(
        request
    )


    if user is None:

        return _ppt_project_response(
            request,
            {
                "detail":
                    "login diperlukan"
            },
            401,
        )


    if not _ppt_csrf_valid(
        request
    ):

        return _ppt_project_response(
            request,
            {
                "detail":
                    "CSRF tidak valid"
            },
            403,
        )


    try:

        kind, template_key = (
            _ppt_template_favorite_identity(
                kind,
                template_key,
            )
        )

    except ValueError as exc:

        return _ppt_project_response(
            request,
            {
                "detail":
                    str(exc)
            },
            400,
        )


    user_id = str(
        user["id"]
    )


    with _ppt_db_connect() as db:

        folder = _ppt_template_folder_row(
            db,
            user_id,
            folder_id,
        )


        if folder is None:

            return _ppt_project_response(
                request,
                {
                    "detail":
                        "folder tidak ditemukan"
                },
                404,
            )


        db.execute(
            """
            DELETE FROM
            presentation_template_folder_items
            WHERE folder_id=?
              AND user_id=?
              AND template_kind=?
              AND template_key=?
            """,
            (
                folder_id,
                user_id,
                kind,
                template_key,
            ),
        )


        now = _ppt_now()


        db.execute(
            """
            UPDATE presentation_template_folders
            SET updated_at=?
            WHERE id=?
              AND user_id=?
            """,
            (
                now,
                folder_id,
                user_id,
            ),
        )


    return _ppt_project_response(
        request,
        {
            "ok":
                True,

            "folder_id":
                folder_id,

            "kind":
                kind,

            "key":
                template_key,
        },
    )


# END BOTCONNECTOR_PRESENTATION_TEMPLATE_FOLDERS_V1
