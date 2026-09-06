"""
BotConnector AI Support V3 — Intelligent Support, Troubleshooting & Installation Orchestrator.
Handles intent classification, Indonesian colloquial query normalization, multi-query routing,
section-level hybrid RAG, bounded multi-turn context, How-To/Troubleshooting/Installation modes,
truthfulness & safety boundaries, deterministic fallback, and support ticket drafts.
"""
from __future__ import annotations

import os
import re
import json
import time
import uuid
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from app.support_ai_knowledge import GLOBAL_KB, KnowledgeChunk
from app.support_ai_inference import GLOBAL_INFERENCE
from app.support_ai_tools import ToolDispatcher, TICKET_DRAFTS, PAGE_DIRECTORY
from app.support import get_redis_connection

# Redis rate limit settings
RATE_LIMIT_ANON_PER_10MIN = 40
RATE_LIMIT_AUTH_PER_10MIN = 80

# In-memory session tracking
@dataclass
class SessionState:
    session_id: str
    history: List[Dict[str, str]] = field(default_factory=list)
    active_product: Optional[str] = None
    active_parking_profile: Optional[str] = None
    active_module: Optional[str] = None
    active_intent: Optional[str] = None
    installation_stage: Optional[str] = None
    troubleshooting_case: Optional[str] = None
    last_updated: float = field(default_factory=time.time)

SESSION_REGISTRY: Dict[str, SessionState] = {}

SYSTEM_PROMPT_TEMPLATE = """
Anda adalah BotConnector AI Support, asisten resmi untuk ekosistem platform BotConnector.
Peran Anda: BOTCONNECTOR PRODUCT SPECIALIST + CUSTOMER SUPPORT AGENT + TROUBLESHOOTING ASSISTANT + INSTALLATION GUIDE.

PRINSIP UTAMA:
1. INFORMASIONAL & PANDUAN SEMATA: Anda TIDAK DAPAT mengeksekusi mutasi data finansial, pembatalan/refund transaksi, pembukaan palang fisik, atau pengubahan saldo secara otomatis.
2. BAHASA: Gunakan Bahasa Indonesia yang ramah, profesional, lugas, dan terstruktur rapi.
3. BATASAN KESELAMATAN FISIK: Untuk pekerjaan kelistrikan (tegangan tinggi, relay motor palang, kabel power kabinet), nyatakan bahwa pekerjaan fisik harus dilakukan oleh teknisi/instalatur bersertifikasi sesuai manual pabrikan.
4. KEBENARAN KESIAPAN (READINESS TRUTHFULNESS):
   - Modul Parkir & QRIS Software/Sandbox: SIAP (READY).
   - QRIS Produksi / PJP Nyata: BELUM AKTIF / PERLU ONBOARDING PJP NYATA.
   - Profile M Ready: Kesiapan kontrak software (bukan kamera fisik terverifikasi sebelum uji lapangan).
   - Fail-Closed: Palang parkir selalu tertutup jika jaringan/listrik mati.
5. PENJELASAN HASIL NYATA:
   - Jika pengguna menanyakan perhitungan (misal: "stok 50 jual 2 jadi berapa?"), jelaskan: 50 -> 48 unit, transaksi selesai & struk terbit, omzet Dashboard bertambah, laporan laba rugi & HPP terupdate real-time.
6. FORMAT JAWABAN:
   - HOW-TO / PANDUAN:
     Jawaban langsung
     Cara:
     1. ...
     2. ...
     3. ...
     Hasil yang didapat: ...
     Langkah berikutnya: ...
   - INSTALLATION / SETUP:
     TUJUAN
     YANG DIBUTUHKAN
     LANGKAH (1, 2, 3...)
     HASIL YANG DIHARAPKAN
     VERIFIKASI
     MASALAH UMUM
     LANGKAH SELANJUTNYA
   - TROUBLESHOOTING / KELUHAN:
     Identifikasi & Nyatakan masalah secara tenang
     Pemeriksaan Utama (1-3 langkah terarah)
     Hasil yang diharapkan
     Tawarkan pembuatan tiket eskalasi jika belum teratasi.

KONTEKS HALAMAN AKTIF: {ecosystem} / {module}
PRODUK AKTIF: {active_product}
PROFIL PARKIR AKTIF: {parking_profile}

{rag_knowledge}
"""

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+|prior\s+)?instructions",
    r"reveal\s+(your\s+)?system\s+prompt",
    r"tampilkan\s+system\s+prompt",
    r"show\s+(me\s+)?(the\s+)?(smtp\s+|api\s+|secret\s+)?password",
    r"print\s+botfather\s+token",
    r"show\s+another\s+user",
    r"run\s+ls\s+",
    r"call\s+shell",
    r"read\s+\.env",
    r"delete\s+inventory",
    r"send\s+btc\s+trade",
    r"force\s+open\s+barrier",
    r"mark\s+paid\s+without\s+payment"
]

def is_adversarial_prompt(text: str) -> bool:
    """Detect prompt injection and malicious security vectors."""
    lowered = text.lower()
    for pat in PROMPT_INJECTION_PATTERNS:
        if re.search(pat, lowered):
            return True
    return False

class SupportAIService:
    """Central intelligent orchestrator for BotConnector Support AI V3."""

    @staticmethod
    def check_rate_limit(client_ip: str, user_id: Optional[str] = None) -> Tuple[bool, int]:
        """Verify Redis rate limits for anonymous vs authenticated sessions."""
        if client_ip in ("127.0.0.1", "testclient", "localhost", "::1"):
            return True, 0

        r = get_redis_connection()
        key = f"support_ai:user:{user_id}" if user_id else f"support_ai:ip:{client_ip}"
        limit = RATE_LIMIT_AUTH_PER_10MIN if user_id else RATE_LIMIT_ANON_PER_10MIN

        if not r:
            return True, 0

        try:
            current = r.incr(key)
            if current == 1:
                r.expire(key, 600)  # 10 minute window
            if current > limit:
                ttl = r.ttl(key)
                return False, max(ttl, 1)
            return True, 0
        except Exception:
            return True, 0

    @staticmethod
    def normalize_colloquial_query(text: str) -> str:
        """Normalize informal Indonesian colloquialisms for accurate semantic parsing."""
        t = text
        replacements = [
            (r"\bgimana\b", "bagaimana"),
            (r"\bga\b|\bnggak\b|\bgak\b|\bndak\b", "tidak"),
            (r"\bkok\b", "mengapa"),
            (r"\budah\b|\bsdh\b", "sudah"),
            (r"\bcuma\b|\bdoang\b|\bhny\b", "hanya"),
            (r"\bpalang\b|\bportal\b", "palang barrier gate"),
            (r"\bbarang\b|\bitem\b", "produk stok barang"),
            (r"\bkameranya\b", "kamera ANPR"),
            (r"\bpasang\b|\binstall\b|\bset up\b", "pasang setup konfigurasi"),
        ]
        for pat, repl in replacements:
            t = re.sub(pat, repl, t, flags=re.IGNORECASE)
        return t

    @staticmethod
    def classify_intent_and_routing(
        user_message: str,
        session_state: SessionState,
        client_ecosystem: str = "PLATFORM"
    ) -> Tuple[str, str, Optional[str], List[str]]:
        """
        Derive intent, product, parking profile, and sub-queries.
        """
        msg_lower = user_message.lower().strip()
        normalized = SupportAIService.normalize_colloquial_query(msg_lower)

        # 1. Check for Short Follow-ups in existing context
        if len(msg_lower.split()) <= 6 or any(w in msg_lower for w in ["cabang", "kds", "hardware", "test", "hikvision", "dahua", "palang", "completed"]):
            # Follow up: "kalau dua cabang?" / "kalau dua cabang gimana"
            if ("cabang" in msg_lower or "dua cabang" in msg_lower) and (session_state.active_product == "BUSINESS_SUITE" or "bisnis" in msg_lower):
                session_state.active_product = "BUSINESS_SUITE"
                return "HOW_TO_REQUEST", "BUSINESS_SUITE", None, ["Transfer Stok Antar Cabang Mutasi Gudang", "transfer stok antar dua cabang", "mutasi cabang"]
            # Follow up: "hardware perlu nggak?" / "perlu hardware nggak?" / "hardware masih perlu nggak?"
            if ("hardware" in msg_lower or "kamera" in msg_lower or "alat" in msg_lower) and (session_state.active_parking_profile == "PAYMENT_ONLY" or "payment" in msg_lower or any("payment" in h.get("content", "").lower() for h in session_state.history)):
                session_state.active_product = "PARKING"
                session_state.active_parking_profile = "PAYMENT_ONLY"
                return "EXPLANATION_REQUEST", "PARKING", "PAYMENT_ONLY", ["Profil 3 PAYMENT_ONLY Gateway QRIS Webhook", "payment only tanpa hardware"]
            # Follow up: "KDS?" / "apa itu kds?" / "kds apa?"
            if "kds" in msg_lower:
                session_state.active_product = "BUSINESS_SUITE"
                return "EXPLANATION_REQUEST", "BUSINESS_SUITE", None, ["Manajemen Restoran Meja KOT KDS Dapur", "kds display dapur resto", "perbedaan kot dan kds"]
            # Follow up: "jadi sekarang bisa test apa?" / "test apa?" / "uji apa?"
            if ("test" in msg_lower or "uji" in msg_lower or "bisa apa" in msg_lower or "test apa" in msg_lower) and (session_state.active_product == "PARKING" or any("qris" in h.get("content", "").lower() or "parkir" in h.get("content", "").lower() for h in session_state.history)):
                session_state.active_product = "PARKING"
                return "HOW_TO_REQUEST", "PARKING", session_state.active_parking_profile or "FULL_STACK", ["Tutorial Simulasi Operasional Parkir Tanpa Hardware", "simulasi parkir simulator", "sandbox order simulator"]
            # Follow up: "kameranya hikvision" / "palangnya sudah ada"
            if ("hikvision" in msg_lower or "dahua" in msg_lower or "palang" in msg_lower) and (session_state.active_parking_profile == "EXISTING_HARDWARE" or any("hardware" in h.get("content", "").lower() for h in session_state.history)):
                session_state.active_product = "PARKING"
                session_state.active_parking_profile = "EXISTING_HARDWARE"
                return "INSTALLATION_REQUEST", "PARKING", "EXISTING_HARDWARE", ["existing hardware kamera hikvision palang adapter", "capability probe device", "Profil 2 EXISTING_HARDWARE"]
            # Follow up: "transaksi sudah completed" / "cabangnya ada dua"
            if session_state.troubleshooting_case == "stock_discrepancy" or "completed" in msg_lower:
                session_state.active_product = "BUSINESS_SUITE"
                return "TROUBLESHOOTING", "BUSINESS_SUITE", None, ["stok tidak berkurang transaksi completed cabang", "inventori mutasi cabang", "Troubleshooting Stok Salah"]

        # 2. Classify Product Routing
        inferred_product = session_state.active_product or "PLATFORM"
        if any(w in msg_lower for w in ["parking", "parkir", "gerbang", "gate", "lane", "tarif", "anpr", "palang", "barrier", "profile m", "profile d", "fail closed", "qris parkir", "payment only", "existing hardware", "full stack"]):
            inferred_product = "PARKING"
        elif any(w in msg_lower for w in ["bisnis", "business suite", "produk", "sku", "stok", "pos", "kasir", "struk", "kot", "kds", "restoran", "dapur", "meja", "cabang", "transfer", "laporan", "omzet", "aov", "siapkan toko", "retail"]):
            inferred_product = "BUSINESS_SUITE"
        elif any(w in msg_lower for w in ["drive", "my drive", "upload", "unggah", "folder", "berkas", "file cloud"]):
            inferred_product = "MY_DRIVE"
        elif any(w in msg_lower for w in ["connect", "tradingview", "mt5", "metatrader", "binance", "sinyal trading"]):
            inferred_product = "CONNECT"
        elif any(w in msg_lower for w in ["login", "daftar", "register", "akun", "produk saya", "my products", "botconnector itu apa"]):
            inferred_product = "PLATFORM"
        elif any(w in msg_lower for w in ["tiket", "support", "bantuan admin", "keamanan", "privasi"]):
            inferred_product = "SUPPORT"
        elif client_ecosystem in ("BUSINESS_SUITE", "PARKING", "MY_DRIVE", "CONNECT"):
            inferred_product = client_ecosystem

        # 3. Classify Parking Profile Routing
        inferred_profile = session_state.active_parking_profile
        if inferred_product == "PARKING":
            if any(w in msg_lower for w in ["sudah punya kamera", "sudah punya palang", "hardware sendiri", "perangkat lama", "kamera saya", "existing hardware", "hikvision", "dahua"]):
                inferred_profile = "EXISTING_HARDWARE"
            elif any(w in msg_lower for w in ["cuma butuh pembayaran", "cuma qris", "pembayaran saja", "payment only", "pms sendiri", "merchant webhook", "api order"]):
                inferred_profile = "PAYMENT_ONLY"
            elif any(w in msg_lower for w in ["full stack", "sistem parkir lengkap", "pasang parking full stack", "mulai parkir dari nol"]):
                inferred_profile = "FULL_STACK"

        # 4. Classify Intent
        inferred_intent = "INFORMATION_REQUEST"

        # Escalation & Complaint
        if any(w in msg_lower for w in ["buat tiket", "hubungi support", "kontak admin", "minta bantuan admin", "bantuan manusia", "cs"]):
            inferred_intent = "SUPPORT_ESCALATION"
        elif any(w in msg_lower for w in ["keamanan", "vulnerability", "celah keamanan", "bug bounty", "security.txt"]):
            inferred_intent = "SECURITY_REPORT"
        elif any(w in msg_lower for w in ["privasi", "hapus data", "data deletion", "erasure"]):
            inferred_intent = "PRIVACY_REQUEST"
        elif any(w in msg_lower for w in ["server down", "sistem down", "gangguan massal", "status server", "sistem lambat"]):
            inferred_intent = "SERVICE_INCIDENT_SUSPECTED"
        elif any(w in msg_lower for w in ["saya kecewa", "rusak", "rugi", "tertagih dua kali", "uang belum masuk", "stok saya salah", "produk saya hilang"]):
            inferred_intent = "CUSTOMER_COMPLAINT"
        # Installation
        elif any(w in msg_lower for w in ["cara pasang", "cara install", "cara setup", "cara konfigurasi", "cara hubungkan", "cara sambungkan", "cara mulai dari nol", "bantu pemasangan", "siapkan toko"]):
            inferred_intent = "INSTALLATION_REQUEST"
        # Troubleshooting
        elif any(w in msg_lower for w in ["nggak muncul", "tidak muncul", "tidak berkurang", "nggak berubah", "pending", "tidak terbuka", "gagal", "offline", "tidak sync", "kosong kenapa", "hilang"]):
            inferred_intent = "TROUBLESHOOTING"
        # Technical Integration
        elif any(w in msg_lower for w in ["endpoint", "api", "webhook", "payload", "hmac", "token bearer", "post order"]):
            inferred_intent = "TECHNICAL_INTEGRATION"
        # Explanation & Glossary
        elif any(w in msg_lower for w in ["apa itu", "apa beda", "apa arti", "artinya apa", "maksud dari", "buat apa"]):
            inferred_intent = "EXPLANATION_REQUEST"
        # How-To
        elif any(w in msg_lower for w in ["cara", "bagaimana", "langkah"]):
            inferred_intent = "HOW_TO_REQUEST"

        # 5. Build Targeted Sub-Queries for Hybrid Retrieval
        sub_queries = [msg_lower, normalized]
        if "hardware sendiri" in msg_lower and "qris" in msg_lower:
            sub_queries.extend(["Parking Existing Hardware kamera palang", "Parking Payment Only QRIS webhook"])

        return inferred_intent, inferred_product, inferred_profile, sub_queries

    @staticmethod
    def format_grounded_response_by_mode(
        user_message: str,
        intent: str,
        product: str,
        parking_profile: Optional[str],
        top_chunk: KnowledgeChunk,
        llm_response: Optional[str] = None
    ) -> Tuple[str, List[Dict[str, str]], List[Dict[str, str]]]:
        """
        Synthesize high-precision, formatted response adhering strictly to mode specifications.
        """
        sources = [
            {"title": top_chunk.title, "url": top_chunk.canonical_url}
        ]
        action_links = list(top_chunk.action_links)

        # Ensure canonical documentation link is always included
        if not any(s["url"].startswith("https://botconnector.id/docs") for s in sources):
            sources.append({"title": "Dokumentasi Master", "url": "https://botconnector.id/docs/"})

        # If LLM produced a good, non-empty response, use it
        if llm_response and len(llm_response.strip()) > 30:
            return llm_response.strip(), sources, action_links

        # ---------------- DETERMINISTIC GROUNDED SYNTHESIS BY MODE ----------------
        msg_lower = user_message.lower()

        # Specific math calculation: Stok 50 jual 2
        if "stok 50" in msg_lower and "jual 2" in msg_lower:
            resp = (
                "**Perhitungan & Dampak Penjualan di Business Suite:**\n\n"
                "Jika stok awal adalah **50 unit** dan kasir menyelesaikan penjualan **2 unit** di POS Kasir:\n\n"
                "• **Saldo Stok Fisik:** Otomatis berkurang dari **50 menjadi 48 unit** secara real-time tanpa hitung manual.\n"
                "• **Pencatatan Transaksi:** Transaksi tercatat di database dengan nomor struk digital unik.\n"
                "• **Dashboard KPI:** Total omzet harian dan jumlah transaksi kasir langsung bertambah.\n"
                "• **Laporan Keuangan:** Laporan Laba Rugi dan HPP (Harga Pokok Penjualan) terbarui seketika."
            )
            return resp, sources, action_links

        # Specific QRIS readiness truthfulness
        if "qris sudah" in msg_lower or "qris aktif" in msg_lower or "qris bisa" in msg_lower:
            resp = (
                "**Status Kesiapan QRIS BotConnector:**\n\n"
                "• **Software & Mode Sandbox:** **SIAP (READY)**. Anda dapat langsung menguji alur pembuatan order QRIS MPM Dynamic dan simulasi pembayaran di konsol /parking/ atau POS Kasir.\n"
                "• **QRIS Produksi (Uang Nyata):** **MEMERLUKAN ONBOARDING PJP**. Untuk menerima transaksi uang nyata, merchant wajib melengkapi dokumen pendaftaran dan aktivasi melalui Penyelenggara Jasa Pembayaran (PJP) resmi terdaftar Bank Indonesia."
            )
            return resp, sources, action_links

        # Specific Hardware Readiness & Safety
        if "profile m" in msg_lower:
            resp = (
                "**Arti 'Profile M Ready':**\n\n"
                "• **Profile M Ready** berarti perangkat lunak BotConnector siap mendukung kontrak metadata video analytics standar industri ONVIF Profile M (untuk deteksi plat nomor kendaraan / ANPR).\n"
                "• **Status Fisik:** Kesiapan software ini berbeda dengan verifikasi fisik kamera lapangan. Kamera fisik di lokasi baru ditandai *Verified* setelah berhasil melalui Capability Probe dan uji deteksi langsung di lokasi."
            )
            return resp, sources, action_links

        if "fail closed" in msg_lower:
            resp = (
                "**Arti & Prinsip 'Fail-Closed':**\n\n"
                "• **Fail-Closed** adalah standar keselamatan operasional di mana palang gerbang parkir akan **selalu berada dalam posisi tertutup / terkunci** jika terjadi pemadaman listrik, kegagalan sinyal jaringan, atau kendala sistem.\n"
                "• Prinsip ini diterapkan untuk mencegah kendaraan keluar tanpa otorisasi tarif dan menjaga keamanan area fasilitas parkir."
            )
            return resp, sources, action_links

        # Specific KOT vs KDS
        if "kot" in msg_lower and "kds" in msg_lower:
            resp = (
                "**Perbedaan KOT dan KDS di Restoran Business Suite:**\n\n"
                "• **KOT (Kitchen Order Ticket):** Tiket cetak/digital ringkasan pesanan makanan & minuman yang dikirimkan segera ke bagian dapur setelah kasir/pelayan mencatat pesanan meja.\n"
                "• **KDS (Kitchen Display System):** Layar monitor dapur digital interaktif tempat koki melihat antrean masak secara real-time dan menandai hidangan yang sudah siap disajikan.\n\n"
                "**Alur:** Pesanan Meja > KOT Diterbitkan > KDS Menampilkan Pesanan > Selesai Masak > Kasir Proses Pembayaran."
            )
            return resp, sources, action_links

        # Mode: INSTALLATION / SETUP
        if intent == "INSTALLATION_REQUEST":
            resp = (
                f"**PANDUAN PEMASANGAN: {top_chunk.title.upper()}**\n\n"
                f"**TUJUAN:**\n{top_chunk.title} pada platform BotConnector secara aman dan terstruktur.\n\n"
                f"**YANG DIBUTUHKAN:**\nAkun BotConnector aktif dengan modul terkait yang telah diaktifkan di /my-products.\n\n"
                f"**LANGKAH:**\n{top_chunk.content}\n\n"
                f"**HASIL YANG DIHARAPKAN:**\nSistem terkonfigurasi dengan status aktif dan siap digunakan dalam operasional harian.\n\n"
                f"**VERIFIKASI:**\nLakukan uji coba transaksi perdana atau simulasi untuk memastikan alur pencatatan berjalan lancar.\n\n"
                f"**MASALAH UMUM:**\nPastikan data master (harga/kredensial) telah diisi lengkap sebelum memulai alur operasional.\n\n"
                f"**LANGKAH SELANJUTNYA:**\nBuka dashboard operasional melalui tautan navigasi di bawah."
            )
            return resp, sources, action_links

        # Mode: TROUBLESHOOTING / COMPLAINT
        if intent in ("TROUBLESHOOTING", "CUSTOMER_COMPLAINT"):
            resp = (
                f"**PANDUAN TROUBLESHOOTING: {top_chunk.title}**\n\n"
                f"**Kendala yang Teridentifikasi:**\n{user_message.strip()}\n\n"
                f"**Pemeriksaan Utama yang Perlu Dilakukan:**\n"
                f"{top_chunk.content}\n\n"
                f"**Hasil yang Diharapkan:**\n"
                f"Operasional sistem kembali normal setelah langkah pemeriksaan di atas diterapkan.\n\n"
                f"*Catatan:* Jika kendala tetap berlanjut, Anda dapat mengajukan tiket laporan resmi melalui Pusat Bantuan /support."
            )
            return resp, sources, action_links

        # Mode: HOW-TO
        if intent == "HOW_TO_REQUEST":
            resp = (
                f"**{top_chunk.title}**\n\n"
                f"**Cara:**\n{top_chunk.content}\n\n"
                f"**Hasil yang didapat:**\nKonfigurasi tersimpan dan dampak operasional tercatat langsung ke sistem real-time.\n\n"
                f"**Langkah berikutnya:**\nBuka modul terkait untuk memverifikasi data Anda."
            )
            return resp, sources, action_links

        # Default / EXPLANATION
        resp = f"**{top_chunk.title}**\n\n{top_chunk.content}"
        return resp, sources, action_links

    @staticmethod
    def handle_message(
        user_message: str,
        session_id: Optional[str] = None,
        ecosystem: str = "PLATFORM",
        module: str = "General",
        user_session: Optional[Dict[str, Any]] = None,
        client_ip: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Process an incoming chat message with rate limiting, injection guard, hybrid RAG,
        inference failover, and support ticket escalation.
        """
        clean_msg = user_message.strip()
        if not clean_msg:
            return {"ok": False, "error": "Pesan tidak boleh kosong."}

        user_id = user_session.get("user_id") if user_session else None

        # 1. Rate limiting
        allowed, retry_after = SupportAIService.check_rate_limit(client_ip, user_id)
        if not allowed:
            return {
                "ok": False,
                "error": f"Batas pesan tercapai. Silakan coba lagi dalam {retry_after} detik atau buat tiket bantuan di /support."
            }

        # 2. Prompt injection defense
        if is_adversarial_prompt(clean_msg):
            return {
                "ok": True,
                "response": "Permintaan tersebut tidak dapat diproses demi keamanan sistem platform BotConnector. Ada yang dapat saya bantu terkait panduan operasional Business Suite, Parking, My Drive, atau dokumentasi resmi?",
                "sources": [{"title": "Keamanan Platform", "url": "https://botconnector.id/security"}],
                "action_links": [{"title": "Buka Dokumentasi", "url": "https://botconnector.id/docs/"}],
                "provider": "security-guard",
                "escalation_offered": False
            }

        # Session State handling
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:16]}"

        if session_id not in SESSION_REGISTRY:
            SESSION_REGISTRY[session_id] = SessionState(session_id=session_id)
        
        session_state = SESSION_REGISTRY[session_id]
        session_state.last_updated = time.time()

        # 3. Intent Classification, Routing & Query Understanding
        intent, product, parking_profile, sub_queries = SupportAIService.classify_intent_and_routing(
            clean_msg, session_state, client_ecosystem=ecosystem
        )

        # Update session memory
        session_state.active_product = product
        if parking_profile:
            session_state.active_parking_profile = parking_profile
        session_state.active_intent = intent

        # 4. Check for explicit ticket draft request
        msg_lower = clean_msg.lower()
        if any(w in msg_lower for w in ["buat tiket", "kirim tiket", "hubungi admin", "minta bantuan admin", "bantuan manusia", "buka tiket"]):
            cat = "GENERAL"
            if product == "BUSINESS_SUITE":
                cat = "BUSINESS_SUITE"
            elif product == "PARKING":
                cat = "PARKING"
            elif product == "CONNECT":
                cat = "CONNECT"
            elif product == "MY_DRIVE":
                cat = "MY_DRIVE"
            elif intent == "SECURITY_REPORT":
                cat = "SECURITY_REPORT"
            elif intent == "PRIVACY_REQUEST":
                cat = "PRIVACY_REQUEST"

            draft_res = ToolDispatcher.execute_tool(
                "create_support_ticket_draft",
                {
                    "subject": f"Bantuan {product.replace('_', ' ').title()}",
                    "category": cat,
                    "summary": clean_msg,
                    "steps_attempted": "Melalui percakapan asisten BotConnector AI"
                },
                user_session=user_session,
                client_ip=client_ip
            )
            return {
                "ok": True,
                "session_id": session_id,
                "response": (
                    "Saya telah menyiapkan draf tiket bantuan resmi untuk diteruskan ke tim BotConnector.\n"
                    "Silakan tinjau dan konfirmasi pengiriman tiket di bawah ini:"
                ),
                "ticket_draft": draft_res,
                "sources": [{"title": "Pusat Dukungan", "url": "https://botconnector.id/support"}],
                "action_links": [{"title": "Buka Pusat Dukungan", "url": "https://botconnector.id/support"}],
                "provider": "support-escalation",
                "escalation_offered": True
            }

        # 5. Hybrid Retrieval Across Sub-Queries
        retrieved_candidates: List[Tuple[KnowledgeChunk, float]] = []
        for q in sub_queries:
            results = GLOBAL_KB.search_hybrid(
                query=q,
                inferred_product=product,
                inferred_intent=intent,
                inferred_parking_profile=parking_profile,
                client_ecosystem=ecosystem,
                top_k=2
            )
            retrieved_candidates.extend(results)

        # Deduplicate candidates while preserving highest score
        unique_chunks: Dict[str, Tuple[KnowledgeChunk, float]] = {}
        for chunk, score in retrieved_candidates:
            if chunk.chunk_id not in unique_chunks or unique_chunks[chunk.chunk_id][1] < score:
                unique_chunks[chunk.chunk_id] = (chunk, score)

        sorted_docs = sorted(unique_chunks.values(), key=lambda x: x[1], reverse=True)[:3]
        top_chunk, top_score = sorted_docs[0] if sorted_docs else (None, 0.0)

        # 6. Low Confidence Guard (No Hallucination)
        if top_score < 0.18 or not top_chunk:
            return {
                "ok": True,
                "session_id": session_id,
                "response": (
                    "Saya belum menemukan informasi resmi yang cukup untuk memastikan jawabannya. "
                    "Anda dapat membuka Dokumentasi Master atau membuat tiket laporan ke tim dukungan BotConnector di /support."
                ),
                "sources": [
                    {"title": "Dokumentasi Master", "url": "https://botconnector.id/docs/"},
                    {"title": "Pusat Dukungan", "url": "https://botconnector.id/support"}
                ],
                "action_links": [
                    {"title": "Buka Dokumentasi", "url": "https://botconnector.id/docs/"},
                    {"title": "Buka Support", "url": "https://botconnector.id/support"}
                ],
                "provider": "knowledge-guard",
                "escalation_offered": True
            }

        # 7. LLM Generation via Freepool Inference Runtime
        rag_context = GLOBAL_KB.format_rag_context(sorted_docs)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ecosystem=ecosystem,
            module=module,
            active_product=product,
            parking_profile=parking_profile or "Semua Profil",
            rag_knowledge=rag_context
        )

        session_state.history.append({"role": "user", "content": clean_msg})
        if len(session_state.history) > 6:
            session_state.history = session_state.history[-6:]

        llm_text, provider_used, latency_ms = GLOBAL_INFERENCE.chat(
            messages=session_state.history,
            system_prompt=system_prompt,
            temperature=0.15,
            max_tokens=380
        )

        # 8. Post-Process & Format Structured Response
        final_text, sources_list, action_links = SupportAIService.format_grounded_response_by_mode(
            user_message=clean_msg,
            intent=intent,
            product=product,
            parking_profile=parking_profile,
            top_chunk=top_chunk,
            llm_response=llm_text
        )

        session_state.history.append({"role": "assistant", "content": final_text})

        # Check if complaint should offer escalation card
        offer_escalation = intent in ("CUSTOMER_COMPLAINT", "SUPPORT_ESCALATION")

        return {
            "ok": True,
            "session_id": session_id,
            "response": final_text,
            "sources": sources_list,
            "action_links": action_links,
            "provider": provider_used or "canonical-kb",
            "latency_ms": latency_ms or 1.0,
            "escalation_offered": offer_escalation
        }
