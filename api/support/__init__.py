"""
BotConnector Support Center V1 API
Handles support ticket creation, management, and routing.
"""
import os
import uuid
import re
import smtplib
import ssl
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import json
import hashlib
import secrets
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Database imports (assuming existing DB structure)
import sqlite3
from contextlib import contextmanager

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
    sender_type: str  # 'customer' or 'admin'
    sender_id: Optional[str]
    message: str
    created_at: str

@dataclass
class SupportTicketEvent:
    id: str
    ticket_id: str
    event_type: str
    event_data: Dict[str, Any]
    performed_by: Optional[str]
    created_at: str

class TicketCategory(Enum):
    GENERAL = "GENERAL"
    ACCOUNT_LOGIN = "ACCOUNT_LOGIN"
    BUSINESS_SUITE = "BUSINESS_SUITE"
    CONNECT = "CONNECT"
    MY_DRIVE = "MY_DRIVE"
    TELEGRAM = "TELEGRAM"
    PRIVACY_REQUEST = "PRIVACY_REQUEST"
    SECURITY_REPORT = "SECURITY_REPORT"
    OTHER = "OTHER"

class TicketStatus(Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_USER = "WAITING_USER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class TicketPriority(Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"

class SupportTicketManager:
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'support.db')
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS support_ticket (
                id TEXT PRIMARY KEY,
                public_reference TEXT UNIQUE NOT NULL,
                user_id TEXT,
                requester_name TEXT NOT NULL,
                requester_email TEXT NOT NULL,
                category TEXT NOT NULL,
                product_context TEXT,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT,
                assigned_to TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS support_ticket_message (
                id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                sender_id TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES support_ticket(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS support_ticket_event (
                id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                performed_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES support_ticket(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS support_email_outbox (
                id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (ticket_id) REFERENCES support_ticket(id)
            )
        ''')
        conn.commit()
        conn.close()

    @contextmanager
    def get_connection(self):
        if not os.path.exists(self.db_path):
            self._init_db()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def generate_public_reference(self) -> str:
        """Generate a non-sequential, non-guessable public reference."""
        while True:
            chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            reference = ''.join(secrets.choice(chars) for _ in range(11))
            formatted_ref = f"BCS-{reference[:4]}-{reference[4:8]}"

            with self.get_connection() as conn:
                existing = conn.execute(
                    "SELECT id FROM support_ticket WHERE public_reference = ?",
                    (formatted_ref,)
                ).fetchone()
                if not existing:
                    return formatted_ref

    def create_ticket(self, ticket_data: Dict[str, Any], user_id: Optional[str] = None) -> str:
        """Create a new support ticket."""
        ticket_id = str(uuid.uuid4())
        public_reference = self.generate_public_reference()
        now = datetime.utcnow().isoformat()

        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO support_ticket (
                    id, public_reference, user_id, requester_name, requester_email,
                    category, product_context, subject, status, priority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id, public_reference, user_id,
                    ticket_data['requester_name'], ticket_data['requester_email'],
                    ticket_data['category'], ticket_data.get('product_context'),
                    ticket_data['subject'], TicketStatus.OPEN.value,
                    ticket_data.get('priority', TicketPriority.NORMAL.value),
                    now, now
                )
            )

            # Create initial message
            message_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO support_ticket_message (
                    id, ticket_id, sender_type, sender_id, message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id, ticket_id, 'customer', user_id,
                    ticket_data['message'], now
                )
            )

            # Record creation event
            event_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO support_ticket_event (
                    id, ticket_id, event_type, event_data, performed_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, ticket_id, 'ticket_created',
                    json.dumps({'category': ticket_data['category']}),
                    user_id, now
                )
            )

        return ticket_id

    def get_ticket(self, ticket_id: str) -> Optional[SupportTicket]:
        """Get a ticket by internal ID."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM support_ticket WHERE id = ?",
                (ticket_id,)
            ).fetchone()

            if row:
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
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    resolved_at=row['resolved_at'],
                    assigned_to=row['assigned_to']
                )
        return None

    def get_ticket_by_reference(self, public_reference: str) -> Optional[SupportTicket]:
        """Get a ticket by public reference (safe version)."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM support_ticket WHERE public_reference = ?",
                (public_reference,)
            ).fetchone()

            if row:
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
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    resolved_at=row['resolved_at'],
                    assigned_to=row['assigned_to']
                )
        return None

    def get_user_tickets(self, user_id: str) -> List[SupportTicket]:
        """Get all tickets for a specific user."""
        tickets = []
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM support_ticket WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()

            for row in rows:
                tickets.append(SupportTicket(
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
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    resolved_at=row['resolved_at'],
                    assigned_to=row['assigned_to']
                ))
        return tickets

# Global instance
_ticket_manager = SupportTicketManager()

# Express.js-style API functions for route.py
def create_ticket(request_data, user_id=None):
    """Create a new support ticket."""
    try:
        ticket_id = _ticket_manager.create_ticket(request_data, user_id)

        ticket = _ticket_manager.get_ticket(ticket_id)

        return {
            'success': True,
            'ticket': {
                'id': ticket.id,
                'public_reference': ticket.public_reference,
                'status': ticket.status,
                'category': ticket.category,
                'subject': ticket.subject,
                'created_at': ticket.created_at
            },
            'message': 'Permintaan Anda telah diterima. Simpan nomor referensi ini untuk referensi.',
            'reference': ticket.public_reference
        }
    except Exception as e:
        return {
            'success': False,
            'message': 'Maaf, terjadi kesalahan saat memproses permintaan Anda: ' + str(e)
        }

def get_ticket(request_data, user_id=None):
    """Get ticket by reference (public) or internal ID (authenticated)."""
    try:
        public_reference = request_data.get('reference') or request_data.get('public_reference')

        if not public_reference:
            return {
                'success': False,
                'message': 'Nomor referensi diperlukan'
            }

        ticket = _ticket_manager.get_ticket_by_reference(public_reference)

        if not ticket:
            return {
                'success': False,
                'message': 'Tiket tidak ditemukan'
            }

        # Check authorization - ticket must belong to user if user is authenticated
        if user_id and ticket.user_id != user_id:
            return {
                'success': False,
                'message': 'Anda tidak memiliki akses ke tiket ini'
            }

        # Get messages for the ticket
        messages = get_ticket_messages(ticket.id)

        return {
            'success': True,
            'ticket': {
                'id': ticket.id,
                'public_reference': ticket.public_reference,
                'requester_name': ticket.requester_name,
                'requester_email': ticket.requester_email,
                'category': ticket.category,
                'product_context': ticket.product_context,
                'subject': ticket.subject,
                'message': 'Kirim pesan ke administrator untuk membantu Anda.',
                'status': ticket.status,
                'priority': ticket.priority,
                'created_at': ticket.created_at,
                'updated_at': ticket.updated_at,
                'messages': [
                    {
                        'id': msg.id,
                        'sender_type': msg.sender_type,
                        'sender_id': msg.sender_id,
                        'message': msg.message,
                        'created_at': msg.created_at
                    }
                    for msg in messages
                ]
            }
        }
    except Exception as e:
        return {
            'success': False,
            'message': 'Maaf, terjadi kesalahan: ' + str(e)
        }

def get_user_tickets(user_id):
    """Get all tickets for the authenticated user."""
    try:
        tickets = _ticket_manager.get_user_tickets(user_id)

        return {
            'success': True,
            'tickets': [
                {
                    'id': ticket.id,
                    'public_reference': ticket.public_reference,
                    'category': ticket.category,
                    'subject': ticket.subject,
                    'status': ticket.status,
                    'priority': ticket.priority,
                    'created_at': ticket.created_at,
                    'updated_at': ticket.updated_at
                }
                for ticket in tickets
            ],
            'total': len(tickets)
        }
    except Exception as e:
        return {
            'success': False,
            'message': 'Maaf, terjadi kesalahan: ' + str(e)
        }

def validate_ticket_data(data):
    """Validate ticket form data."""
    errors = []

    # Honeypot validation
    if data.get('website', '').strip() or data.get('url', '').strip():
        errors.append('Bot submission detected')
        return errors

    if not data.get('requester_name', '').strip():
        errors.append('Nama diperlukan')

    email = data.get('requester_email', '').strip()
    if not email:
        errors.append('Email diperlukan')
    elif not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        errors.append('Format email tidak valid')

    if not data.get('category'):
        errors.append('Kategori diperlukan')

    if not data.get('subject', '').strip():
        errors.append('Subjek diperlukan')

    message = data.get('message', '').strip()
    if not message:
        errors.append('Pesan diperlukan')
    elif len(message) > 10000:
        errors.append('Pesan terlalu panjang (maksimal 10.000 karakter)')

    return errors

# Additional helper functions

def get_ticket_messages(ticket_id):
    """Get all messages for a ticket."""
    with _ticket_manager.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM support_ticket_message WHERE ticket_id = ? ORDER BY created_at",
            (ticket_id,)
        ).fetchall()

        messages = []
        for row in rows:
            messages.append(SupportTicketMessage(
                id=row['id'],
                ticket_id=row['ticket_id'],
                sender_type=row['sender_type'],
                sender_id=row['sender_id'],
                message=row['message'],
                created_at=row['created_at']
            ))
        return messages

def add_ticket_message(ticket_id, sender_type, sender_id, message):
    """Add a message to a ticket."""
    message_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with _ticket_manager.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO support_ticket_message (
                id, ticket_id, sender_type, sender_id, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_id, ticket_id, sender_type, sender_id,
                message, now
            )
        )

        # Record event
        event_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO support_ticket_event (
                id, ticket_id, event_type, event_data, performed_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, ticket_id, 'message_added',
                json.dumps({'sender_type': sender_type}),
                sender_id, now
            )
        )

# Email notification functions

MAIL_CONFIG = {
    'host': os.environ.get('SMTP_HOST', ''),
    'port': int(os.environ.get('SMTP_PORT', '587')),
    'username': os.environ.get('SMTP_USERNAME', ''),
    'password': os.environ.get('SMTP_PASSWORD', ''),
    'from_email': os.environ.get('SMTP_FROM_EMAIL', 'noreply@botconnector.id'),
    'from_name': os.environ.get('SMTP_FROM_NAME', 'BotConnector Support'),
    'use_tls': os.environ.get('SMTP_USE_TLS', 'true').lower() == 'true',
}

MAILBOX_PROVISIONING_REQUIRED = not all([
    MAIL_CONFIG['host'],
    MAIL_CONFIG['username'],
    MAIL_CONFIG['password'],
    MAIL_CONFIG['from_email']
])

def is_mail_configured() -> bool:
    """Check if mail is properly configured."""
    return not MAILBOX_PROVISIONING_REQUIRED

def add_to_email_outbox(ticket_id, recipient_email, subject, body):
    """Add email to outbox for sending."""
    email_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with _ticket_manager.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO support_email_outbox (
                id, ticket_id, recipient_email, subject, body, sent_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                email_id, ticket_id, recipient_email, subject, body, None
            )
        )

def mark_email_sent(email_id):
    """Mark an email as sent."""
    now = datetime.utcnow().isoformat()

    with _ticket_manager.get_connection() as conn:
        conn.execute(
            "UPDATE support_email_outbox SET sent_at = ? WHERE id = ?",
            (now, email_id)
        )

def send_email(recipient_email: str, subject: str, body: str, reply_to: Optional[str] = None) -> bool:
    """Send email using configured SMTP. Returns True on success."""
    if MAILBOX_PROVISIONING_REQUIRED:
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = f"{MAIL_CONFIG['from_name']} <{MAIL_CONFIG['from_email']}>"
        msg['To'] = recipient_email
        msg['Subject'] = subject

        if reply_to:
            msg['Reply-To'] = reply_to

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        context = ssl.create_default_context()

        with smtplib.SMTP(MAIL_CONFIG['host'], MAIL_CONFIG['port']) as server:
            if MAIL_CONFIG['use_tls']:
                server.starttls(context=context)
            server.login(MAIL_CONFIG['username'], MAIL_CONFIG['password'])
            server.send_message(msg)

        return True
    except Exception:
        return False

def send_user_acknowledgement(ticket) -> bool:
    """Send acknowledgement email to ticket requester."""
    if MAILBOX_PROVISIONING_REQUIRED:
        return False

    subject = f"[BotConnector Support] {ticket.public_reference} — Permintaan diterima"
    body = f"""Halo {ticket.requester_name},

Permintaan Anda telah diterima oleh tim BotConnector.

Nomor Referensi: {ticket.public_reference}
Subjek: {ticket.subject}
Kategori: {ticket.category}

Kami akan meninjau permintaan Anda dan membalas secepatnya.
Anda dapat merujuk ke nomor referensi di atas untuk komunikasi lebih lanjut.

Lihat tiket: https://botconnector.id/support

---
Ini adalah pesan otomatis dari BotConnector Support Center.
Mohon tidak membalas email ini secara langsung.
"""

    return send_email(ticket.requester_email, subject, body)

def send_admin_notification(ticket) -> bool:
    """Send notification email to admin/support team."""
    if MAILBOX_PROVISIONING_REQUIRED:
        return False

    # Route to appropriate mailbox based on category
    routing = {
        'GENERAL': 'support@botconnector.id',
        'ACCOUNT_LOGIN': 'support@botconnector.id',
        'BUSINESS_SUITE': 'support@botconnector.id',
        'CONNECT': 'support@botconnector.id',
        'MY_DRIVE': 'support@botconnector.id',
        'TELEGRAM': 'support@botconnector.id',
        'PRIVACY_REQUEST': 'privacy@botconnector.id',
        'SECURITY_REPORT': 'security@botconnector.id',
        'OTHER': 'support@botconnector.id'
    }

    recipient = routing.get(ticket.category, 'support@botconnector.id')

    # Get the ticket message (first message from customer)
    messages = get_ticket_messages(ticket.id)
    ticket_message = messages[0].message if messages else ""

    # Header injection guard: strip CR/LF from message content
    safe_message = ticket_message.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')

    subject = f"[BotConnector Support] {ticket.public_reference} — {ticket.subject}"
    body = f"""
Ticket Reference: {ticket.public_reference}
Category: {ticket.category}
Subject: {ticket.subject}
Requester: {ticket.requester_name} <{ticket.requester_email}>
Product Context: {ticket.product_context or 'N/A'}
User ID: {ticket.user_id or 'N/A (public submission)'}

Message:
{safe_message}

---
This is an automated message from BotConnector Support Center.
"""

    # Use requester email as Reply-To if safe
    reply_to = ticket.requester_email if ticket.requester_email else None

    return send_email(recipient, subject, body, reply_to=reply_to)

def process_email_outbox() -> Dict[str, int]:
    """Process pending emails in outbox. Returns dict with sent/failed counts."""
    sent = 0
    failed = 0

    with _ticket_manager.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM support_email_outbox WHERE sent_at IS NULL"
        ).fetchall()

        for row in rows:
            email_id = row['id']
            recipient = row['recipient_email']
            subject = row['subject']
            body = row['body']

            success = send_email(recipient, subject, body)

            if success:
                mark_email_sent(email_id)
                sent += 1

                # Record event
                conn.execute(
                    """
                    INSERT INTO support_ticket_event (
                        id, ticket_id, event_type, event_data, performed_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), row['ticket_id'], 'notification_sent',
                        json.dumps({'recipient': recipient}), 'system', datetime.utcnow().isoformat()
                    )
                )
            else:
                failed += 1

                # Record event
                conn.execute(
                    """
                    INSERT INTO support_ticket_event (
                        id, ticket_id, event_type, event_data, performed_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), row['ticket_id'], 'notification_failed',
                        json.dumps({'recipient': recipient, 'error': 'SMTP error'}), 'system', datetime.utcnow().isoformat()
                    )
                )

    return {'sent': sent, 'failed': failed}

# Admin support functions

def get_all_tickets(status: Optional[str] = None, category: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[SupportTicket]:
    """Get all tickets for admin view with optional filters."""
    tickets = []
    query = "SELECT * FROM support_ticket WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)
    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _ticket_manager.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

        for row in rows:
            tickets.append(SupportTicket(
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
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                resolved_at=row['resolved_at'],
                assigned_to=row['assigned_to']
            ))
    return tickets

def update_ticket_status(ticket_id: str, new_status: str, performed_by: Optional[str] = None) -> bool:
    """Update ticket status (admin only)."""
    valid_statuses = [s.value for s in TicketStatus]
    if new_status not in valid_statuses:
        return False

    now = datetime.utcnow().isoformat()
    resolved_at = now if new_status in ['RESOLVED', 'CLOSED'] else None

    with _ticket_manager.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE support_ticket SET status = ?, updated_at = ?, resolved_at = ? WHERE id = ?",
            (new_status, now, resolved_at, ticket_id)
        )

        if cursor.rowcount > 0:
            # Record event
            conn.execute(
                """
                INSERT INTO support_ticket_event (
                    id, ticket_id, event_type, event_data, performed_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()), ticket_id, 'status_changed',
                    json.dumps({'new_status': new_status}), performed_by, now
                )
            )
            return True
    return False

def get_ticket_stats() -> Dict[str, int]:
    """Get ticket statistics for admin dashboard."""
    with _ticket_manager.get_connection() as conn:
        stats = {}
        stats['total'] = conn.execute("SELECT COUNT(*) FROM support_ticket").fetchone()[0]
        stats['open'] = conn.execute("SELECT COUNT(*) FROM support_ticket WHERE status = 'OPEN'").fetchone()[0]
        stats['in_progress'] = conn.execute("SELECT COUNT(*) FROM support_ticket WHERE status = 'IN_PROGRESS'").fetchone()[0]
        stats['waiting_user'] = conn.execute("SELECT COUNT(*) FROM support_ticket WHERE status = 'WAITING_USER'").fetchone()[0]
        stats['resolved'] = conn.execute("SELECT COUNT(*) FROM support_ticket WHERE status = 'RESOLVED'").fetchone()[0]
        stats['closed'] = conn.execute("SELECT COUNT(*) FROM support_ticket WHERE status = 'CLOSED'").fetchone()[0]

        # Category breakdown
        cat_rows = conn.execute("SELECT category, COUNT(*) as cnt FROM support_ticket GROUP BY category").fetchall()
        stats['by_category'] = {row[0]: row[1] for row in cat_rows}

        return stats

# Security.txt module

def get_security_txt_content() -> str:
    """Generate security.txt content dynamically."""
    from datetime import datetime, timedelta
    expires = (datetime.utcnow() + timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')

    lines = [
        "Contact: https://botconnector.id/support?category=security",
        f"Expires: {expires}",
        "Canonical: https://botconnector.id/.well-known/security.txt",
        "Policy: https://botconnector.id/security",
        "Preferred-Languages: id, en"
    ]

    return "\n".join(lines) + "\n"

def security_txt_handler(request):
    """Handler for /.well-known/security.txt endpoint."""
    headers = {
        'Content-Type': 'text/plain; charset=utf-8'
    }

    return {
        'status': 200,
        'headers': headers,
        'body': get_security_txt_content()
    }

# Backward compatibility
SECURITY_TXT_CONTENT = get_security_txt_content()

# Export the main classes and functions
__all__ = [
    'SupportTicketManager',
    'SupportTicket',
    'SupportTicketMessage',
    'SupportTicketEvent',
    'TicketCategory',
    'TicketStatus',
    'TicketPriority',
    'create_ticket',
    'get_ticket',
    'get_user_tickets',
    'validate_ticket_data',
    'register_routes',
    'MAIL_CONFIG',
    'MAILBOX_PROVISIONING_REQUIRED',
    'is_mail_configured',
    'send_email',
    'send_user_acknowledgement',
    'send_admin_notification',
    'process_email_outbox',
    'get_all_tickets',
    'update_ticket_status',
    'get_ticket_stats',
    'add_ticket_message',
    'SECURITY_TXT_CONTENT',
    'security_txt_handler',
    'get_security_txt_content'
]