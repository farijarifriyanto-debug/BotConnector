"""
BotConnector Production Flask Application
Handles support ticket creation, management, strict authorization, and security.txt.
Extended with admin panel, legal pages, and support sub-pages.
"""
from __future__ import annotations

import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from support import (
    SupportTicketManager, TicketCategory, TicketStatus, TicketPriority,
    validate_ticket_data, get_security_txt_content,
    create_ticket, get_user_tickets, get_ticket, get_ticket_messages,
    MAILBOX_PROVISIONING_REQUIRED, is_mail_configured,
    get_all_tickets, update_ticket_status, get_ticket_stats,
    send_user_acknowledgement, send_admin_notification, process_email_outbox
)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'botconnector-support-secret-v1')

# Rate Limiter - use in-memory storage for testing (Redis not available in test env)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"]
)
limiter.init_app(app)

_ticket_mgr = SupportTicketManager()

def _attempt_ticket_notifications(ticket_id):
    """Attempt to send admin notification and user acknowledgement after ticket creation."""
    if not ticket_id:
        return
    try:
        ticket = _ticket_mgr.get_ticket(ticket_id)
        if ticket:
            send_admin_notification(ticket)
            send_user_acknowledgement(ticket)
    except Exception:
        pass

# Category mapping helper for query parameters
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

# Admin authentication
def require_admin(f):
    """Decorator to require admin authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page."""
    if request.method == 'POST':
        password = request.form.get('password', '')
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        if admin_password and password == admin_password:
            session['is_admin'] = True
            next_url = request.args.get('next') or url_for('admin_support')
            return redirect(next_url)
        return render_template('admin_login.html', error='Kata sandi salah')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    """Admin logout."""
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

@app.route('/support', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def support_page():
    """
    Public support page.
    - Anonymous and authenticated users can create tickets.
    - Authenticated users can view their ticket history.
    - Preselects category if ?category=... is passed in URL.
    """
    user_id = session.get('user_id')
    user_name = session.get('user_name', '')
    user_email = session.get('user_email', user_id if (user_id and '@' in user_id) else '')

    if request.method == 'POST':
        # Form submission or JSON
        data = request.get_json(silent=True) or request.form.to_dict()

        # Validation & Honeypot
        errors = validate_ticket_data(data)
        if errors:
            # Honeypot should return 403
            if any('Bot submission detected' in e for e in errors):
                return jsonify({'success': False, 'message': 'Permintaan ditolak'}), 403
            return jsonify({'success': False, 'message': 'Data tidak valid: ' + ', '.join(errors), 'errors': errors}), 400

        result = create_ticket(data, user_id=user_id)
        if result.get('success'):
            ticket_id = result.get('ticket', {}).get('id')
            if ticket_id:
                ticket = _ticket_mgr.get_ticket(ticket_id)
                if ticket:
                    send_admin_notification(ticket)
                    send_user_acknowledgement(ticket)
        return jsonify(result), (200 if result.get('success') else 400)

    # GET Request
    raw_category = (request.args.get('category') or '').strip().lower()
    selected_category = CATEGORY_PARAM_MAP.get(raw_category, 'GENERAL') if raw_category else 'GENERAL'

    categories = [c.value for c in TicketCategory]
    user_tickets = _ticket_mgr.get_user_tickets(user_id) if user_id else []

    return render_template(
        'support.html',
        categories=categories,
        tickets=user_tickets,
        is_logged_in=bool(user_id),
        user_email=user_email,
        user_name=user_name,
        selected_category=selected_category
    )

@app.route('/support/tickets', methods=['GET'])
def support_ticket_history():
    """
    Authenticated Ticket History.
    Anonymous: 401 Unauthorized (Enumeration Denied).
    Authenticated: Returns only own tickets.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Autentikasi diperlukan'}), 401

    result = get_user_tickets(user_id)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result), 200

@app.route('/support/ticket/<public_reference>', methods=['GET'])
def support_ticket_detail(public_reference):
    """
    Ticket Detail Lookup.
    - Anonymous: DENIED (401) — Public reference is not a bearer credential!
    - User A accessing User B: DENIED (403 Forbidden).
    - User A accessing User A: ALLOWED (200 OK).
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Autentikasi diperlukan untuk melihat detail tiket'}), 401

    ticket = _ticket_mgr.get_ticket_by_reference(public_reference)
    if not ticket:
        return jsonify({'success': False, 'message': 'Tiket tidak ditemukan'}), 404

    if ticket.user_id != user_id:
        return jsonify({'success': False, 'message': 'Akses ditolak: Anda bukan pemilik tiket ini'}), 403

    messages = get_ticket_messages(ticket.id)
    return jsonify({
        'success': True,
        'ticket': {
            'id': ticket.id,
            'public_reference': ticket.public_reference,
            'requester_name': ticket.requester_name,
            'requester_email': ticket.requester_email,
            'category': ticket.category,
            'product_context': ticket.product_context,
            'subject': ticket.subject,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at,
            'updated_at': ticket.updated_at,
            'resolved_at': ticket.resolved_at,
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
    }), 200

@app.route('/api/support/tickets', methods=['POST'])
@limiter.limit("10 per minute")
def api_create_ticket():
    """API endpoint to create ticket."""
    data = request.get_json(silent=True) or request.form.to_dict()
    user_id = session.get('user_id')
    result = create_ticket(data, user_id=user_id)
    if result.get('success'):
        _attempt_ticket_notifications(result.get('ticket', {}).get('id'))
    return jsonify(result), (200 if result.get('success') else 400)

@app.route('/api/support/tickets', methods=['GET'])
def api_get_tickets():
    """
    API list tickets.
    - Anonymous: 401 Unauthorized (No public enumeration).
    - Authenticated: Returns only own tickets.
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Autentikasi diperlukan'}), 401
    return jsonify(get_user_tickets(user_id)), 200

@app.route('/api/support/tickets/<identifier>', methods=['GET'])
def api_get_single_ticket(identifier):
    """API get single ticket with strict authorization."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Autentikasi diperlukan'}), 401

    ticket = _ticket_mgr.get_ticket_by_reference(identifier)
    if not ticket:
        ticket = _ticket_mgr.get_ticket(identifier)
    if not ticket:
        return jsonify({'success': False, 'message': 'Tiket tidak ditemukan'}), 404

    if ticket.user_id != user_id:
        return jsonify({'success': False, 'message': 'Anda tidak memiliki akses ke tiket ini'}), 403

    messages = get_ticket_messages(ticket.id)
    return jsonify({
        'success': True,
        'ticket': {
            'id': ticket.id,
            'public_reference': ticket.public_reference,
            'requester_name': ticket.requester_name,
            'requester_email': ticket.requester_email,
            'category': ticket.category,
            'product_context': ticket.product_context,
            'subject': ticket.subject,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at,
            'updated_at': ticket.updated_at,
            'resolved_at': ticket.resolved_at,
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
    }), 200

@app.route('/.well-known/security.txt', methods=['GET'])
def well_known_security_txt():
    """RFC3339 security.txt with future expiration."""
    content = get_security_txt_content()
    return Response(content, status=200, content_type='text/plain; charset=utf-8')

# Privacy Request Page
@app.route('/support/privacy', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def support_privacy():
    """Privacy request intake page and form handler."""
    user_id = session.get('user_id')
    user_name = session.get('user_name', '')
    user_email = session.get('user_email', user_id if (user_id and '@' in user_id) else '')

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form.to_dict()
        data['category'] = TicketCategory.PRIVACY_REQUEST.value
        data['product_context'] = data.get('product_context', 'Privacy')

        errors = validate_ticket_data(data)
        if errors:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Data tidak valid: ' + ', '.join(errors), 'errors': errors}), 400
            return render_template('privacy_request.html', error_message=', '.join(errors), form_data=data), 400

        result = create_ticket(data, user_id=user_id)
        if request.is_json:
            if result.get('success'):
                _attempt_ticket_notifications(result.get('ticket', {}).get('id'))
            return jsonify(result), (200 if result.get('success') else 400)
        if result.get('success'):
            _attempt_ticket_notifications(result.get('ticket', {}).get('id'))
        return render_template('privacy_request.html', success_message=result.get('message'), public_reference=result.get('reference'))

    return render_template('privacy_request.html', user_email=user_email, user_name=user_name)

# Security Report Page
@app.route('/support/security-report', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def support_security_report():
    """Security report intake page and form handler."""
    user_id = session.get('user_id')
    user_name = session.get('user_name', '')
    user_email = session.get('user_email', user_id if (user_id and '@' in user_id) else '')

    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form.to_dict()
        data['category'] = TicketCategory.SECURITY_REPORT.value
        data['product_context'] = data.get('product_context', 'Security')

        # Map security form fields
        if 'affected_service' in data:
            data['subject'] = f"Security: {data['affected_service']}"
        if 'description' in data:
            data['message'] = data['description']

        errors = validate_ticket_data(data)
        if errors:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Data tidak valid: ' + ', '.join(errors), 'errors': errors}), 400
            return render_template('security_report.html', error_message=', '.join(errors), form_data=data), 400

        result = create_ticket(data, user_id=user_id)
        if request.is_json:
            if result.get('success'):
                _attempt_ticket_notifications(result.get('ticket', {}).get('id'))
            return jsonify(result), (200 if result.get('success') else 400)
        if result.get('success'):
            _attempt_ticket_notifications(result.get('ticket', {}).get('id'))
        return render_template('security_report.html', success_message=result.get('message'), public_reference=result.get('reference'))

    return render_template('security_report.html', user_email=user_email, user_name=user_name)

# Admin Support Panel Routes
@app.route('/panel/support')
@require_admin
def admin_support():
    """Admin support ticket dashboard."""
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    tickets = get_all_tickets(
        status=status_filter if status_filter else None,
        category=category_filter if category_filter else None,
        limit=per_page,
        offset=offset
    )
    stats = get_ticket_stats()

    return render_template('admin_support.html',
                           tickets=tickets,
                           stats=stats,
                           status_filter=status_filter,
                           category_filter=category_filter,
                           categories=[c.value for c in TicketCategory],
                           statuses=[s.value for s in TicketStatus],
                           page=page,
                           mailbox_provisioning_required=MAILBOX_PROVISIONING_REQUIRED)

@app.route('/panel/support/ticket/<ticket_id>')
@require_admin
def admin_ticket_detail(ticket_id):
    """Admin ticket detail view."""
    ticket = _ticket_mgr.get_ticket(ticket_id)
    if not ticket:
        ticket = _ticket_mgr.get_ticket_by_reference(ticket_id)
    if not ticket:
        return "Ticket not found", 404

    messages = get_ticket_messages(ticket.id)
    events = []
    try:
        with _ticket_mgr.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM support_ticket_event WHERE ticket_id = ? ORDER BY created_at", (ticket.id,))
                rows = cur.fetchall()
                for row in rows:
                    events.append({
                        'id': row['id'],
                        'event_type': row['event_type'],
                        'event_data': row['event_data'],
                        'performed_by': row['performed_by'],
                        'created_at': row['created_at']
                    })
    except Exception:
        pass

    return render_template('admin_ticket_detail.html',
                           ticket=ticket,
                           messages=messages,
                           events=events,
                           statuses=[s.value for s in TicketStatus],
                           mailbox_provisioning_required=MAILBOX_PROVISIONING_REQUIRED)

@app.route('/panel/support/ticket/<ticket_id>/status', methods=['POST'])
@require_admin
def admin_update_ticket_status(ticket_id):
    """Update ticket status (admin)."""
    new_status = request.form.get('status', '').strip()
    if not new_status:
        return jsonify({'success': False, 'message': 'Status diperlukan'}), 400

    success = update_ticket_status(ticket_id, new_status, performed_by='admin')
    if success:
        return jsonify({'success': True, 'message': 'Status diperbarui'})
    return jsonify({'success': False, 'message': 'Gagal memperbarui status'}), 400

@app.route('/panel/support/process-emails', methods=['POST'])
@require_admin
def admin_process_emails():
    """Process pending emails in outbox."""
    result = process_email_outbox()
    return jsonify({'success': True, **result})

# Legal Pages with updated contact sections
@app.route('/privacy')
def privacy_page():
    """Privacy policy page."""
    return render_template('privacy.html', mailbox_provisioning_required=MAILBOX_PROVISIONING_REQUIRED)

@app.route('/terms')
def terms_page():
    """Terms of service page."""
    return render_template('terms.html', mailbox_provisioning_required=MAILBOX_PROVISIONING_REQUIRED)

@app.route('/security')
def security_page():
    """Security page."""
    return render_template('security.html', mailbox_provisioning_required=MAILBOX_PROVISIONING_REQUIRED)

# Homepage route (for regression testing)
@app.route('/')
def homepage():
    """Homepage."""
    return render_template('index.html')

# Health check
@app.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'botconnector-support'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '9000'))
    app.run(host='0.0.0.0', port=port, debug=False)