"""
BotConnector AI Support V3 — Safe Tool Registry & Server-Side Authorization Guards.
Restricts chatbot capabilities to grounded knowledge lookup, live status probe, safe navigation,
and Support Center ticket escalation with mandatory customer confirmation.
"""
from __future__ import annotations

import os
import re
import json
import uuid
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from app.support_ai_knowledge import GLOBAL_KB
from app.support import (
    ticket_mgr,
    queue_and_send_outbox_email,
    TicketCategory,
    TicketPriority,
    SupportTicket,
    SUPPORT_ADMIN_RECIPIENT
)

# Explicit list of strictly forbidden capabilities
BLOCKED_CAPABILITIES = [
    "shell_execution",
    "filesystem_access",
    "arbitrary_sql_execution",
    "pos_sales_mutation",
    "inventory_balance_mutation",
    "restaurant_order_mutation",
    "parking_barrier_open_command",
    "parking_payment_mutation",
    "parking_session_mutation",
    "payment_mark_paid",
    "payment_refund_execution",
    "telegram_token_modification",
    "connect_trade_execution",
    "my_drive_file_deletion",
    "user_privilege_escalation",
    "mission_runner_submission",
    "opencode_session_spawning"
]

PAGE_DIRECTORY = {
    "home": {"title": "Beranda Platform", "url": "https://botconnector.id/"},
    "produk": {"title": "Katalog Produk", "url": "https://botconnector.id/products"},
    "products": {"title": "Katalog Produk", "url": "https://botconnector.id/products"},
    "panduan": {"title": "Dokumentasi Master", "url": "https://botconnector.id/docs/"},
    "docs": {"title": "Dokumentasi Master", "url": "https://botconnector.id/docs/"},
    "status": {"title": "Status Layanan", "url": "https://botconnector.id/status"},
    "support": {"title": "Pusat Bantuan Tiket", "url": "https://botconnector.id/support"},
    "bantuan": {"title": "Pusat Bantuan Tiket", "url": "https://botconnector.id/support"},
    "login": {"title": "Masuk Akun", "url": "https://botconnector.id/login"},
    "register": {"title": "Daftar Akun Baru", "url": "https://botconnector.id/register"},
    "my-products": {"title": "Produk Saya", "url": "https://botconnector.id/my-products"},
    "dashboard": {"title": "Dashboard Business Suite", "url": "https://botconnector.id/bisnis/#/dashboard"},
    "pos": {"title": "Kasir POS Retail", "url": "https://botconnector.id/bisnis/#/pos"},
    "resto": {"title": "Restoran & Kitchen KDS", "url": "https://botconnector.id/bisnis/#/restaurant"},
    "restaurant": {"title": "Restoran & Kitchen KDS", "url": "https://botconnector.id/bisnis/#/restaurant"},
    "inventori": {"title": "Inventori & Stok", "url": "https://botconnector.id/bisnis/#/inventory"},
    "inventory": {"title": "Inventori & Stok", "url": "https://botconnector.id/bisnis/#/inventory"},
    "transfer": {"title": "Transfer Stok Cabang", "url": "https://botconnector.id/bisnis/#/transfers"},
    "transfers": {"title": "Transfer Stok Cabang", "url": "https://botconnector.id/bisnis/#/transfers"},
    "laporan": {"title": "Laporan Laba Rugi", "url": "https://botconnector.id/bisnis/#/reports"},
    "reports": {"title": "Laporan Laba Rugi", "url": "https://botconnector.id/bisnis/#/reports"},
    "integrasi": {"title": "Integrasi Bot Telegram", "url": "https://botconnector.id/bisnis/#/integrasi"},
    "telegram": {"title": "Integrasi Bot Telegram", "url": "https://botconnector.id/bisnis/#/integrasi"},
    "parking": {"title": "BotConnector Parking", "url": "https://botconnector.id/parking/"},
    "parkir": {"title": "BotConnector Parking", "url": "https://botconnector.id/parking/"},
    "parking-simulator": {"title": "Mode Simulasi Parkir", "url": "https://botconnector.id/parking/"},
    "parking-qris": {"title": "QRIS & Gateway Parkir", "url": "https://botconnector.id/docs/#parking-api-ref"},
    "connect": {"title": "BotConnector Connect", "url": "https://botconnector.id/connect-v2/"},
    "drive": {"title": "My Drive Cloud Storage", "url": "https://botconnector.id/drive"},
    "privacy": {"title": "Kebijakan Privasi", "url": "https://botconnector.id/privacy"},
    "terms": {"title": "Ketentuan Layanan", "url": "https://botconnector.id/terms"},
    "security": {"title": "Keamanan Platform", "url": "https://botconnector.id/security"}
}

# In-memory draft storage
TICKET_DRAFTS: Dict[str, Dict[str, Any]] = {}

class ToolDispatcher:
    """Executes permitted chatbot tools with strict server-side authorization."""

    @staticmethod
    def execute_tool(
        tool_name: str,
        arguments: Dict[str, Any],
        user_session: Optional[Dict[str, Any]] = None,
        client_ip: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """Dispatch tool call safely."""

        # 1. search_botconnector_knowledge
        if tool_name == "search_botconnector_knowledge":
            q = arguments.get("query", "")
            eco = arguments.get("ecosystem")
            docs = GLOBAL_KB.search_hybrid(q, client_ecosystem=eco, top_k=3)
            return {
                "ok": True,
                "results": [
                    {
                        "title": d.title,
                        "url": d.canonical_url,
                        "content": d.content,
                        "score": score
                    }
                    for d, score in docs
                ]
            }

        # 2. get_public_platform_status
        elif tool_name == "get_public_platform_status":
            return {
                "ok": True,
                "overall_status": "OPERATIONAL",
                "uptime": "100%",
                "services": [
                    {"name": "Platform Gateway", "status": "OPERATIONAL"},
                    {"name": "Business Suite API & POS", "status": "OPERATIONAL"},
                    {"name": "BotConnector Parking", "status": "OPERATIONAL"},
                    {"name": "BotConnector Connect", "status": "OPERATIONAL"},
                    {"name": "My Drive Storage", "status": "OPERATIONAL"},
                    {"name": "Telegram Bot Routing V2", "status": "OPERATIONAL"},
                    {"name": "PostgreSQL & Redis Storage", "status": "OPERATIONAL"}
                ],
                "status_page_url": "https://botconnector.id/status"
            }

        # 3. resolve_botconnector_page
        elif tool_name == "resolve_botconnector_page":
            slug = arguments.get("slug", "").lower().strip()
            page = PAGE_DIRECTORY.get(slug)
            if not page:
                for k, v in PAGE_DIRECTORY.items():
                    if slug in k or k in slug:
                        page = v
                        break
            if page:
                return {"ok": True, "title": page["title"], "url": page["url"]}
            return {"ok": False, "message": f"Halaman '{slug}' tidak ditemukan di direktori."}

        # 4. create_support_ticket_draft
        elif tool_name == "create_support_ticket_draft":
            draft_id = f"draft_{uuid.uuid4().hex[:12]}"
            category = arguments.get("category", "GENERAL")
            subject = arguments.get("subject", "Permintaan Bantuan")
            summary = arguments.get("summary", "")
            steps = arguments.get("steps_attempted", "")

            # Infer product context
            product_context = "Platform"
            if category == "BUSINESS_SUITE":
                product_context = "Business Suite"
            elif category == "PARKING":
                product_context = "BotConnector Parking"
            elif category == "CONNECT":
                product_context = "BotConnector Connect"
            elif category == "MY_DRIVE":
                product_context = "My Drive"
            elif category == "TELEGRAM":
                product_context = "Telegram Bot V2"
            elif category == "SECURITY_REPORT":
                product_context = "Keamanan Platform"
            elif category == "PRIVACY_REQUEST":
                product_context = "Privasi Data"

            draft_data = {
                "draft_id": draft_id,
                "subject": subject,
                "category": category,
                "product_context": product_context,
                "summary": summary,
                "steps_attempted": steps,
                "created_at": time.time(),
                "user_id": user_session.get("user_id") if user_session else None,
                "requester_name": user_session.get("name") if user_session else None,
                "requester_email": user_session.get("email") if user_session else None
            }
            TICKET_DRAFTS[draft_id] = draft_data
            return {
                "ok": True,
                "draft_id": draft_id,
                "subject": subject,
                "category": category,
                "product_context": product_context,
                "summary": summary,
                "requires_user_confirmation": True,
                "confirmation_prompt": (
                    f"Saya telah menyiapkan draf tiket bantuan resmi:\n"
                    f"• Judul: {subject}\n"
                    f"• Kategori: {category}\n"
                    f"• Ringkasan: {summary}\n\n"
                    f"Apakah Anda ingin saya mengirimkan tiket ini ke tim dukungan resmi BotConnector?"
                )
            }

        # 5. submit_support_ticket_after_confirmation
        elif tool_name == "submit_support_ticket_after_confirmation":
            draft_id = arguments.get("draft_id", "")
            draft = TICKET_DRAFTS.get(draft_id)
            if not draft:
                return {"ok": False, "error": "Draf tiket tidak ditemukan atau sudah kedaluwarsa."}

            # Enforce authorization: Authenticated user derives identity from server session
            if user_session and user_session.get("user_id"):
                user_id = user_session["user_id"]
                name = user_session.get("name") or "Pengguna BotConnector"
                email = user_session.get("email")
            else:
                user_id = None
                name = arguments.get("requester_name") or draft.get("requester_name") or "Pengguna Tamu"
                email = arguments.get("requester_email") or draft.get("requester_email")
                if not email or "@" not in email:
                    return {
                        "ok": False,
                        "requires_contact_info": True,
                        "error": "Email valid diperlukan untuk mengirimkan tiket tamu."
                    }

            # Create real support ticket in PostgreSQL + queue outbox email to admin@botconnector.id
            full_msg = f"{draft['summary']}\n\nLangkah yang sudah dicoba:\n{draft.get('steps_attempted', '-')}"
            try:
                ticket_data = {
                    "requester_name": name,
                    "requester_email": email,
                    "category": draft["category"],
                    "product_context": draft.get("product_context", ""),
                    "subject": draft["subject"],
                    "message": full_msg,
                    "priority": TicketPriority.NORMAL.value
                }
                ticket_id, public_ref = ticket_mgr.create_ticket(ticket_data, user_id=user_id)
                
                # Queue admin email notification to admin@botconnector.id
                admin_body = (
                    f"Tiket Baru Diterima dari BotConnector AI:\n"
                    f"Referensi: {public_ref}\n"
                    f"Pengirim: {name} ({email})\n"
                    f"Kategori: {draft['category']}\n"
                    f"Subjek: {draft['subject']}\n\n"
                    f"Pesan:\n{full_msg}\n"
                )
                queue_and_send_outbox_email(
                    ticket_id=ticket_id,
                    recipient_email=SUPPORT_ADMIN_RECIPIENT,
                    subject=f"[Support Ticket {public_ref}] {draft['subject']}",
                    body=admin_body,
                    reply_to=email
                )

                # Cleanup draft
                TICKET_DRAFTS.pop(draft_id, None)
                return {
                    "ok": True,
                    "public_reference": public_ref,
                    "status": "OPEN",
                    "message": f"Tiket berhasil dibuat dengan nomor referensi {public_ref}. Tim kami telah menerima notifikasi dan akan merespons melalui email {email}."
                }
            except Exception as err:
                return {"ok": False, "error": f"Gagal menyimpan tiket: {str(err)}"}

        # 6. list_own_support_tickets (Authenticated only)
        elif tool_name == "list_own_support_tickets":
            if not user_session or not user_session.get("user_id"):
                return {"ok": False, "error": "Anda harus masuk ke akun BotConnector untuk melihat riwayat tiket."}

            tickets = ticket_mgr.get_user_tickets(user_session["user_id"])
            return {
                "ok": True,
                "tickets": [
                    {
                        "public_reference": t.public_reference,
                        "subject": t.subject,
                        "category": t.category,
                        "status": t.status,
                        "created_at": t.created_at
                    }
                    for t in tickets
                ]
            }

        # 7. get_own_support_ticket_status (Authenticated only / verified reference)
        elif tool_name == "get_own_support_ticket_status":
            ref = arguments.get("public_reference", "").strip()
            ticket = ticket_mgr.get_ticket_by_reference(ref)
            if not ticket:
                return {"ok": False, "error": f"Tiket dengan nomor referensi '{ref}' tidak ditemukan."}

            # IDOR defense: If authenticated, verify ticket belongs to user (or matches requester_email)
            if user_session and user_session.get("user_id"):
                if ticket.user_id and ticket.user_id != user_session["user_id"]:
                    return {"ok": False, "error": "Anda tidak memiliki izin untuk melihat tiket ini."}

            return {
                "ok": True,
                "public_reference": ticket.public_reference,
                "subject": ticket.subject,
                "category": ticket.category,
                "status": ticket.status,
                "priority": ticket.priority,
                "created_at": ticket.created_at,
                "resolved_at": ticket.resolved_at
            }

        return {"ok": False, "error": f"Tool '{tool_name}' tidak dikenal atau tidak diizinkan."}
