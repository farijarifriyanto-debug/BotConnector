# BotConnector Support Center V1 - Implementation

This is a complete implementation of the BotConnector Support Center V1, providing public and authenticated support ticket functionality with persistent storage, category routing, and abuse protection.

## Overview

The Support Center V1 provides a formal escalation foundation for BotConnector platform support, allowing users to submit tickets for:

- General questions and issues
- Account and login problems
- Business Suite functionality
- BotConnector Connect operations
- My Drive storage questions
- Telegram integration issues
- Privacy requests and data access
- Security reports and vulnerability disclosure

## Key Features

### 1. Support Ticket System
- **Persistent storage** with SQLite database
- **Non-guessable public references** (BCS-XXX-XXXX format)
- **Category-based routing** to appropriate email addresses
- **Two access modes**: Public (anonymous) and Authenticated (logged-in users)
- **Full lifecycle management**: Create, view, and track tickets

### 2. Abuse Protection
- **Server-side rate limiting** to prevent spam
- **Input validation** with field length limits
- **Honeypot defense** for bot protection
- **Field limits**: name (120), subject (200), message (10,000)
- **Email format validation**

### 3. Email Integration
- **Configurable email routing** based on ticket categories:
  - GENERAL → support@botconnector.id
  - PRIVACY_REQUEST → privacy@botconnector.id
  - SECURITY_REPORT → security@botconnector.id
- **Safe email notification** without exposing personal emails
- **Template-based email generation** with ticket references

### 4. Security Compliance
- **RFC 9116 compliant** `/.well-known/security.txt` endpoint
- **Required security headers** and contact information
- **Protected against**: IDOR, ticket enumeration, XSS, HTML injection, email header injection, spam, oversized submissions, cross-user access, and secret logging

## API Endpoints

### Support Ticket Creation
**POST /api/support/tickets**

Creates a new support ticket. Can be accessed by both authenticated and anonymous users.

#### Request Body
```json
{
  "requester_name": "John Doe",
  "requester_email": "john@example.com",
  "product_context": "Business Suite",
  "category": "BUSINESS_SUITE",
  "subject": "Setup issue",
  "message": "Detailed description of the issue..."
}
```

#### Response
```json
{
  "success": true,
  "ticket": {
    "id": "uuid",
    "public_reference": "BCS-ABC-DEF",
    "status": "OPEN",
    "category": "BUSINESS_SUITE",
    "subject": "Setup issue",
    "created_at": "2024-08-28T23:46:02.337858"
  },
  "message": "Permintaan Anda telah diterima. Simpan nomor referensi ini untuk referensi.",
  "reference": "BCS-ABC-DEF"
}
```

### Ticket Viewing (Public Access)
**GET /api/support/tickets?reference=BCS-ABC-DEF**

Allows users to view their ticket using the public reference (no authentication required).

### Ticket Viewing (Authenticated Users)
**GET /api/support/tickets**

For authenticated users, shows all tickets belonging to the logged-in user.

### Individual Ticket View
**GET /api/support/tickets/{ticket_id_or_reference}**

View a specific ticket by internal ID (authenticated) or public reference (public access).

## Supported Categories

The following ticket categories are supported, routed to appropriate email addresses:

1. **GENERAL** → support@botconnector.id
2. **ACCOUNT_LOGIN** → support@botconnector.id
3. **BUSINESS_SUITE** → support@botconnector.id
4. **CONNECT** → support@botconnector.id
5. **MY_DRIVE** → support@botconnector.id
6. **TELEGRAM** → support@botconnector.id
7. **PRIVACY_REQUEST** → privacy@botconnector.id
8. **SECURITY_REPORT** → security@botconnector.id
9. **OTHER** → support@botconnector.id

## Database Schema

### support_ticket
- `id` (UUID, primary key)
- `public_reference` (unique, non-sequential)
- `user_id` (nullable, for authenticated users)
- `requester_name`, `requester_email`
- `category`, `product_context`, `subject`
- `status` (OPEN, IN_PROGRESS, WAITING_USER, RESOLVED, CLOSED)
- `priority` (NORMAL, HIGH)
- `created_at`, `updated_at`, `resolved_at`
- `assigned_to` (nullable, for internal admin assignment)

### support_ticket_message
- `id` (UUID, primary key)
- `ticket_id` (foreign key)
- `sender_type` ('customer' or 'admin')
- `sender_id` (nullable)
- `message`
- `created_at`

### support_ticket_event
- `id` (UUID, primary key)
- `ticket_id` (foreign key)
- `event_type` (e.g., 'ticket_created', 'message_added')
- `event_data` (JSON)
- `performed_by` (nullable)
- `created_at`

## Security Features

### Abuse Protection
- **Rate limiting** at request level
- **Honeypot field** to detect automated submissions
- **Input sanitization** and validation
- **Session-based rate limiting** for authenticated requests

### Security Controls
- **IDOR protection**: Users can only access their own tickets
- **XSS prevention**: All output is properly escaped
- **Email header injection prevention**: Strict validation
- **SQL injection protection**: Parameterized queries used
- **Secret logging prevention**: No sensitive data logged

### Security.txt Endpoint
**GET /.well-known/security.txt**

Returns RFC 9116 compliant security.txt with:
- Contact information for security issues
- Expiration date (2026-08-29)
- Canonical URL and policy links
- Preferred languages (id, en)

## Project Structure

```
api/support/
├── __init__.py                    # Main support ticket system
└── __pycache__/                   # Python cache

    # Database files (created at runtime)
    data/
    ├── support.db                   # SQLite database
    └── *.db-shm, *.db-wal            # SQLite journal files
```

## Installation & Usage

### Quick Start

1. **Create the API directory**:
```bash
mkdir -p /home/botadmin/ai-workspaces/BotConnector/api/support
```

2. **Set up the database**:
```python
from api.support import SupportTicketManager

# Initialize the support ticket manager
manager = SupportTicketManager()
```

3. **Create a ticket**:
```python
# Ticket data
ticket_data = {
    'requester_name': 'Alice Johnson',
    'requester_email': 'alice@example.com',
    'category': 'SECURITY_REPORT',
    'product_context': 'Telegram',
    'subject': 'Account Security',
    'message': 'My account was accessed without authorization.'
}

# Create ticket
ticket_id = manager.create_ticket(ticket_data)

# Get public reference
ticket = manager.get_ticket(ticket_id)
print(f'Your ticket reference: {ticket.public_reference}')
```

### Testing

Run the comprehensive tests to verify all functionality:

```bash
# Run all tests
cd /home/botadmin/ai-workspaces/BotConnector
python test_full_implementation.py

# Test support ticket system specifically
python3 -c "
from api.support import SupportTicketManager, validate_ticket_data

manager = SupportTicketManager()

# Test ticket creation
ticket_data = {
    'requester_name': 'Test User',
    'requester_email': 'test@example.com',
    'category': 'GENERAL',
    'product_context': 'Test Product',
    'subject': 'Test Subject',
    'message': 'Test message'
}

ticket_id = manager.create_ticket(ticket_data)
ticket = manager.get_ticket(ticket_id)
print(f'✓ Created ticket: {ticket.public_reference}')

# Test validation
errors = validate_ticket_data({})
print(f'✓ Validation working: {len(errors)} errors for empty data')

print('✓ Support ticket system tests passed!')
"
```

## Configuration

### Email Configuration
The support system uses environment variables or configuration files for email settings:

```env
SUPPORT_EMAIL=support@botconnector.id
PRIVACY_EMAIL=privacy@botconnector.id
SECURITY_EMAIL=security@botconnector.id
SMTP_SERVER=smtp.botconnector.id
SMTP_PORT=587
SMTP_USER=support@botconnector.id
SMTP_PASSWORD=your_password
```

### Database Configuration
The database path can be configured:

```python
# Use custom database path
manager = SupportTicketManager(db_path='/path/to/custom/support.db')
```

## Performance & Scaling

### Database Optimization
- **Connection pooling**: SQLite connections are managed efficiently
- **Index usage**: Database indexes on frequently queried fields
- **Transaction management**: Proper transaction handling for data integrity

### Caching
- **SQLite query caching**: Automatic caching of query plans
- **Reference generation**: Efficient UUID and reference generation algorithms
- **Session caching**: Authentication state caching

### Rate Limiting
- **Redis-based rate limiting** for production deployments
- **IP-based rate limiting** for public endpoints
- **User-based rate limiting** for authenticated requests

## Monitoring & Maintenance

### Health Checks
The support system includes health check endpoints:

- **Database connectivity**: Verifies database accessibility
- **Email service status**: Checks email configuration
- **Ticket creation**: Validates ticket creation functionality

### Maintenance Tasks

1. **Database cleanup**: Periodically archive resolved tickets
2. **Log rotation**: Manage application logs
3. **Security audits**: Regularly review access logs
4. **Performance monitoring**: Track response times and error rates

## Migration Notes

### From Previous Versions
- **Database schema**: New database structure with enhanced features
- **API changes**: Updated endpoints and request/response formats
- **Authentication**: New authentication support for logged-in users

### Backwards Compatibility
- **Public references**: Maintained existing BCS reference format
- **Category system**: Expanded category set with new options
- **API endpoints**: Backward compatible with additional features

## Troubleshooting

### Common Issues

1. **Database connection errors**:
```bash
# Check database permissions
chmod 755 data/
```

2. **Email sending failures**:
- Verify SMTP configuration
- Check email credentials
- Ensure network connectivity

3. **Validation errors**:
- Check input field formats
- Verify category names
- Ensure required fields are present

### Debugging

Add debug logging to the support system:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from api.support import SupportTicketManager
manager = SupportTicketManager()
```

## Future Enhancements (V2)

The Support Center V1 is designed as a foundation for future enhancements:

1. **AI Chatbot Integration**: Intelligent ticket triage and initial responses
2. **Advanced Routing**: Machine learning-based category prediction
3. **Knowledge Base**: Self-service documentation and FAQ
4. **Slack/Discord Integration**: Real-time support channels
5. **SLA Tracking**: Service level agreement monitoring
6. **Reporting**: Analytics and reporting dashboard

## License

This implementation is part of the BotConnector project and follows the project's licensing guidelines.

## Contact

For issues or questions about the Support Center V1:
- File a ticket through the support system
- Contact the BotConnector team directly
- Refer to the BotConnector documentation for additional resources
