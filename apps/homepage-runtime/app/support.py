"""
BotConnector Support Center V1 Engine (Platform Integration)
PostgreSQL persistence, Redis-backed rate limiting, secure authorization, outbox, and security.txt.
Routes admin notifications to SUPPORT_ADMIN_RECIPIENT (admin@botconnector.id).
"""
from __future__ import annotations

import os
import re
import uuid
import json
import secrets
import smtplib
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
import redis

# Configuration & Constants
SUPPORT_ADMIN_RECIPIENT = os.environ.get("SUPPORT_ADMIN_RECIPIENT", "admin@botconnector.id").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.hostinger.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "admin@botconnector.id").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "admin@botconnector.id").strip()
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "BOTCONNECTOR").strip()
SMTP_SSL = os.environ.get("SMTP_SSL", "true").lower() in ("true", "1", "yes")

# Enums
class TicketCategory(str, Enum):
    GENERAL = "GENERAL"
    ACCOUNT_LOGIN = "ACCOUNT_LOGIN"
    BUSINESS_SUITE = "BUSINESS_SUITE"
    PARKING = "PARKING"
    CONNECT = "CONNECT"
    MY_DRIVE = "MY_DRIVE"
    TELEGRAM = "TELEGRAM"
    PRIVACY_REQUEST = "PRIVACY_REQUEST"
    SECURITY_REPORT = "SECURITY_REPORT"
    OTHER = "OTHER"

class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_USER = "WAITING_USER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class TicketPriority(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"

@dataclass
class SupportTicket:
    id: str
    public_reference: str
    user_id: Optional[str]
    requester_name: str
    requester_email: str
    category: str
    product_context: Optional[str]
    subject: str
    status: str
    priority: str
    created_at: str
    updated_at: str
    resolved_at: Optional[str]
    assigned_to: Optional[str]

@dataclass
class SupportTicketMessage:
    id: str
    ticket_id: str
    sender_type: str
    sender_id: Optional[str]
    message: str
    created_at: str

# ----------------- DB & REDIS CONNECTION HELPERS -----------------

def _read_pg_password() -> str:
    """Resolve the DB password from a protected file or env var. No default."""
    password_file = os.environ.get("POSTGRES_PASSWORD_FILE", "").strip()
    if password_file:
        return open(password_file, "r", encoding="utf-8").read().strip()
    password = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if password:
        return password
    raise RuntimeError(
        "No PostgreSQL credential configured: set POSTGRES_PASSWORD_FILE "
        "(preferred) or POSTGRES_PASSWORD."
    )


def get_pg_credentials() -> dict:
    """Retrieve PostgreSQL connection parameters securely."""
    pg_host = os.environ.get("POSTGRES_HOST", "").strip()
    if not pg_host:
        pg_host = "botconnector-core-postgres"

    pg_port = int(os.environ.get("POSTGRES_PORT", "5432"))
    pg_db = os.environ.get("POSTGRES_DB", "botconnector")
    pg_user = os.environ.get("POSTGRES_USER", "botconnector_app")
    pg_password = _read_pg_password()

    return {
        "host": pg_host,
        "port": pg_port,
        "dbname": pg_db,
        "user": pg_user,
        "password": pg_password
    }

def _read_redis_password() -> str:
    """Resolve the Redis password from a protected file or env var. No default."""
    password_file = os.environ.get("REDIS_PASSWORD_FILE", "").strip()
    if password_file:
        return open(password_file, "r", encoding="utf-8").read().strip()
    password = os.environ.get("REDIS_PASSWORD", "").strip()
    if password:
        return password
    raise RuntimeError(
        "No Redis credential configured: set REDIS_PASSWORD_FILE "
        "(preferred) or REDIS_PASSWORD."
    )


def get_redis_connection() -> Optional[redis.Redis]:
    """Retrieve authenticated Redis client with fallback."""
    try:
        redis_host = os.environ.get("REDIS_HOST", "botconnector-core-redis").strip()
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        redis_password = _read_redis_password()

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password if redis_password else None,
            socket_timeout=2.0,
            decode_responses=True
        )
        r.ping()
        return r
    except Exception:
        return None

def check_redis_rate_limit(client_ip: str, action: str = "create_ticket", limit: int = 20, window_seconds: int = 60) -> bool:
    """Redis-backed rate limiting per IP. Returns True if allowed, False if exceeded."""
    r = get_redis_connection()
    if not r:
        return True # fail open if redis is unreachable
    try:
        key = f"support_limiter:{action}:{client_ip}"
        current = r.incr(key)
        if current == 1:
            r.expire(key, window_seconds)
        return current <= limit
    except Exception:
        return True

# ----------------- SUPPORT TICKET MANAGER (POSTGRES) -----------------

class SupportTicketManager:
    """Platform Support Ticket Manager backed by PostgreSQL."""
    
    @contextmanager
    def get_connection(self):
        creds = get_pg_credentials()
        conn = psycopg.connect(
            host=creds["host"],
            port=creds["port"],
            dbname=creds["dbname"],
            user=creds["user"],
            password=creds["password"],
            row_factory=dict_row
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def generate_public_reference(self) -> str:
        """Generate a cryptographically secure, non-sequential public reference (e.g. BCS-XDJ-R1FG6Z85GL)."""
        chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        while True:
            part1 = ''.join(secrets.choice(chars) for _ in range(3))
            part2 = ''.join(secrets.choice(chars) for _ in range(10))
            ref = f"BCS-{part1}-{part2}"
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM support_ticket WHERE public_reference = %s", (ref,))
                    if not cur.fetchone():
                        return ref

    def create_ticket(self, ticket_data: Dict[str, Any], user_id: Optional[str] = None) -> tuple[str, str]:
        ticket_id = str(uuid.uuid4())
        public_reference = self.generate_public_reference()
        now = datetime.now(timezone.utc)
        
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # 3. Persist Ticket First
                cur.execute(
                    """
                    INSERT INTO support_ticket (
                        id, public_reference, user_id, requester_name, requester_email,
                        category, product_context, subject, status, priority,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        ticket_id, public_reference, user_id,
                        ticket_data['requester_name'].strip(),
                        ticket_data['requester_email'].strip().lower(),
                        ticket_data['category'],
                        ticket_data.get('product_context', ''),
                        ticket_data['subject'].strip(),
                        TicketStatus.OPEN.value,
                        ticket_data.get('priority', TicketPriority.NORMAL.value),
                        now, now
                    )
                )
                
                # 4. Persist Initial Message
                message_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO support_ticket_message (
                        id, ticket_id, sender_type, sender_id, message, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id, ticket_id, 'customer', user_id,
                        ticket_data['message'].strip(), now
                    )
                )
                
                # 4b. Persist Ticket Created Event
                event_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO support_ticket_event (
                        id, ticket_id, event_type, event_data, performed_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_id, ticket_id, 'ticket_created',
                        json.dumps({
                            'category': ticket_data['category'],
                            'requester_email': ticket_data['requester_email'],
                            'is_authenticated': bool(user_id)
                        }),
                        user_id or 'anonymous', now
                    )
                )
        
        return ticket_id, public_reference

    def get_ticket(self, ticket_id: str) -> Optional[SupportTicket]:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM support_ticket WHERE id = %s", (ticket_id,))
                row = cur.fetchone()
                if row:
                    return self._row_to_ticket(row)
        return None

    def get_ticket_by_reference(self, public_reference: str) -> Optional[SupportTicket]:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM support_ticket WHERE public_reference = %s", (public_reference,))
                row = cur.fetchone()
                if row:
                    return self._row_to_ticket(row)
        return None

    def get_user_tickets(self, user_id: str) -> List[SupportTicket]:
        tickets = []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM support_ticket WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
                rows = cur.fetchall()
                for row in rows:
                    tickets.append(self._row_to_ticket(row))
        return tickets

    def get_ticket_messages(self, ticket_id: str) -> List[SupportTicketMessage]:
        messages = []
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM support_ticket_message WHERE ticket_id = %s ORDER BY created_at ASC", (ticket_id,))
                rows = cur.fetchall()
                for row in rows:
                    created_at_str = row['created_at'].isoformat() if hasattr(row['created_at'], 'isoformat') else str(row['created_at'])
                    messages.append(SupportTicketMessage(
                        id=row['id'],
                        ticket_id=row['ticket_id'],
                        sender_type=row['sender_type'],
                        sender_id=row['sender_id'],
                        message=row['message'],
                        created_at=created_at_str
                    ))
        return messages

    def _row_to_ticket(self, row: dict) -> SupportTicket:
        created_at_str = row['created_at'].isoformat() if hasattr(row['created_at'], 'isoformat') else str(row['created_at'])
        updated_at_str = row['updated_at'].isoformat() if hasattr(row['updated_at'], 'isoformat') else str(row['updated_at'])
        resolved_at_str = row['resolved_at'].isoformat() if (row['resolved_at'] and hasattr(row['resolved_at'], 'isoformat')) else (str(row['resolved_at']) if row['resolved_at'] else None)
        
        return SupportTicket(
            id=row['id'],
            public_reference=row['public_reference'],
            user_id=row['user_id'],
            requester_name=row['requester_name'],
            requester_email=row['requester_email'],
            category=row['category'],
            product_context=row['product_context'],
            subject=row['subject'],
            status=row['status'],
            priority=row['priority'],
            created_at=created_at_str,
            updated_at=updated_at_str,
            resolved_at=resolved_at_str,
            assigned_to=row['assigned_to']
        )

# Global Instance
ticket_mgr = SupportTicketManager()

# ----------------- VALIDATION -----------------

def validate_ticket_data(data: dict) -> list[str]:
    errors = []
    
    # Honeypot validation
    if data.get('website', '').strip() or data.get('url', '').strip():
        errors.append('Bot submission detected')
        return errors
        
    name = (data.get('requester_name') or '').strip()
    if not name:
        errors.append('Nama lengkap diperlukan')
    elif len(name) > 120:
        errors.append('Nama terlalu panjang (maksimal 120 karakter)')
        
    email = (data.get('requester_email') or '').strip()
    if not email:
        errors.append('Email diperlukan')
    elif len(email) > 254:
        errors.append('Email terlalu panjang (maksimal 254 karakter)')
    elif not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
        errors.append('Format email tidak valid')
        
    category = (data.get('category') or '').strip().upper()
    valid_cats = [c.value for c in TicketCategory]
    if not category or category not in valid_cats:
        errors.append(f'Kategori tidak valid. Pilih dari: {", ".join(valid_cats)}')
        
    subject = (data.get('subject') or '').strip()
    if not subject:
        errors.append('Subjek diperlukan')
    elif len(subject) > 200:
        errors.append('Subjek terlalu panjang (maksimal 200 karakter)')
    elif '\r' in subject or '\n' in subject:
        errors.append('Subjek tidak boleh mengandung baris baru (header injection guard)')
        
    message = (data.get('message') or '').strip()
    if not message:
        errors.append('Pesan diperlukan')
    elif len(message) > 10000:
        errors.append('Pesan terlalu panjang (maksimal 10.000 karakter)')
        
    product_context = (data.get('product_context') or '').strip()
    if len(product_context) > 120:
        errors.append('Product context terlalu panjang (maksimal 120 karakter)')
        
    return errors

# ----------------- OUTBOUND EMAIL DELIVERY VIA VERIFIED TRANSPORT -----------------

def queue_and_send_outbox_email(
    ticket_id: str,
    recipient_email: str,
    subject: str,
    body: str,
    reply_to: Optional[str] = None
) -> bool:
    """
    1. Persist email row in PostgreSQL support_email_outbox table.
    2. Attempt delivery using existing verified BotConnector outbound SMTP transport.
    3. Update outbox record status to SENT or FAILED.
    4. Never raise exceptions to calling ticket workflow.
    """
    email_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # 1. Insert into PostgreSQL Outbox Table
    try:
        with ticket_mgr.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO support_email_outbox (
                        id, ticket_id, recipient_email, subject, body, reply_to, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (email_id, ticket_id, recipient_email, subject, body, reply_to, 'PENDING', now)
                )
    except Exception:
        pass

    # 2. Attempt SMTP Delivery via Verified Hostinger Transport
    try:
        msg = EmailMessage()
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg["To"] = recipient_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body)

        if SMTP_SSL:
            client = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15)
        else:
            client = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
            if os.environ.get("SMTP_STARTTLS", "false").lower() in ("true", "1"):
                client.starttls()

        try:
            client.ehlo()
            if SMTP_USERNAME:
                client.login(SMTP_USERNAME, SMTP_PASSWORD)
            client.send_message(msg)
        finally:
            try:
                client.quit()
            except Exception:
                client.close()

        # Update status to SENT
        with ticket_mgr.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE support_email_outbox 
                    SET status = 'SENT', sent_at = %s 
                    WHERE id = %s
                    """,
                    (datetime.now(timezone.utc), email_id)
                )
        return True

    except Exception as exc:
        # Record failure reason in outbox without failing ticket creation
        try:
            with ticket_mgr.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE support_email_outbox 
                        SET status = 'FAILED', error_message = %s 
                        WHERE id = %s
                        """,
                        (str(exc)[:500], email_id)
                    )
        except Exception:
            pass
        return False

def send_admin_notification(ticket: SupportTicket) -> bool:
    """
    Internal notification to BotConnector Administrator.
    Routes all categories to SUPPORT_ADMIN_RECIPIENT (admin@botconnector.id).
    Includes ticket category, public reference, requester information, and context.
    """
    recipient = SUPPORT_ADMIN_RECIPIENT
    subject = f"[BotConnector Support] [{ticket.category}] {ticket.public_reference} — {ticket.subject}"
    
    # Retrieve initial message
    messages = ticket_mgr.get_ticket_messages(ticket.id)
    msg_text = messages[0].message if messages else "(Pesan tidak ditemukan)"
    
    body = f"""Tiket Bantuan Baru Diterima di BotConnector Support Center:

Nomor Referensi: {ticket.public_reference}
Kategori: {ticket.category}
Subjek: {ticket.subject}

Pemohon: {ticket.requester_name} <{ticket.requester_email}>
User ID Akun: {ticket.user_id or 'PENGGUNA ANONIM'}
Konteks Produk / Cabang: {ticket.product_context or '-'}
Waktu Dibuat: {ticket.created_at}

--------------------------------------------------
Isi Pesan / Laporan:
--------------------------------------------------
{msg_text}

--------------------------------------------------
Tindakan:
Buka database/portal admin atau balas email ini untuk merespons pemohon.
Reply-To telah diarahkan ke {ticket.requester_email}.
"""
    return queue_and_send_outbox_email(
        ticket_id=ticket.id,
        recipient_email=recipient,
        subject=subject,
        body=body,
        reply_to=ticket.requester_email
    )

def send_user_acknowledgement(ticket: SupportTicket) -> bool:
    """
    Confirmation email sent to ticket requester.
    """
    subject = f"[BotConnector Support] {ticket.public_reference} — Permintaan diterima: {ticket.subject}"
    body = f"""Halo {ticket.requester_name},

Permintaan bantuan Anda telah berhasil diterima oleh sistem BotConnector Support.

Nomor Referensi Tiket: {ticket.public_reference}
Kategori: {ticket.category}
Subjek: {ticket.subject}

Status: OPEN
Waktu Penerimaan: {ticket.created_at}

Simpan nomor referensi di atas untuk keperluan korespondensi dengan tim kami.
Jika Anda memiliki akun terdaftar di BotConnector, Anda dapat melihat status dan riwayat tiket pada Pusat Bantuan.

---
Pusat Bantuan & Dukungan BotConnector
https://botconnector.id/support
"""
    return queue_and_send_outbox_email(
        ticket_id=ticket.id,
        recipient_email=ticket.requester_email,
        subject=subject,
        body=body,
        reply_to=None
    )

def get_security_txt_content() -> str:
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime('%Y-%m-%dT00:00:00Z')
    lines = [
        "Contact: https://botconnector.id/support?category=security",
        f"Expires: {expires}",
        "Canonical: https://botconnector.id/.well-known/security.txt",
        "Policy: https://botconnector.id/security",
        "Preferred-Languages: id, en"
    ]
    return "\n".join(lines) + "\n"
