from app import app

def test_comprehensive():
    """Comprehensive test of support center functionality"""
    with app.test_client() as client:
        print("=== COMPREHENSIVE SUPPORT CENTER TEST ===\n")

        # Test 1: GET /support page
        print("1. Testing GET /support...")
        response = client.get('/support')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("   ✓ GET /support returns 200")

        # Test 2: GET /support/tickets without login (should require auth)
        print("\n2. Testing GET /support/tickets without login...")
        response = client.get('/support/tickets')
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("   ✓ GET /support/tickets correctly requires login (401)")

        # Test 3: POST /support - General ticket
        print("\n3. Testing POST /support - General ticket...")
        form_data = {
            'requester_name': 'John Doe',
            'requester_email': 'john@example.com',
            'category': 'GENERAL',
            'subject': 'General Inquiry',
            'message': 'This is a general question about BotConnector services.',
            'product_context': 'General'
        }
        response = client.post('/support', data=form_data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == True, f"Expected success=True, got {data}"
        assert 'reference' in data, "Response should include ticket reference"
        general_ticket_ref = data['reference']
        print(f"   ✓ General ticket created successfully: {general_ticket_ref}")

        # Test 4: POST /support - Privacy request
        print("\n4. Testing POST /support - Privacy request...")
        form_data = {
            'requester_name': 'Jane Smith',
            'requester_email': 'jane@example.com',
            'category': 'PRIVACY_REQUEST',
            'subject': 'Data Access Request',
            'message': 'I would like to request access to my personal data.',
            'product_context': 'Privacy'
        }
        response = client.post('/support', data=form_data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == True, f"Expected success=True, got {data}"
        assert 'reference' in data, "Response should include ticket reference"
        privacy_ticket_ref = data['reference']
        print(f"   ✓ Privacy ticket created successfully: {privacy_ticket_ref}")

        # Test 5: POST /support - Security report
        print("\n5. Testing POST /support - Security report...")
        form_data = {
            'requester_name': 'Security Researcher',
            'requester_email': 'security@example.com',
            'category': 'SECURITY_REPORT',
            'subject': 'Potential Security Issue',
            'message': 'I found a potential security vulnerability in the login system.',
            'product_context': 'Security'
        }
        response = client.post('/support', data=form_data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == True, f"Expected success=True, got {data}"
        assert 'reference' in data, "Response should include ticket reference"
        security_ticket_ref = data['reference']
        print(f"   ✓ Security ticket created successfully: {security_ticket_ref}")

        # Test 6: Test ticket retrieval by reference (public access - should require auth)
        print("\n6. Testing public ticket retrieval by reference...")
        response = client.get(f'/support/ticket/{general_ticket_ref}')
        assert response.status_code == 401, f"Expected 401 for unauthenticated access, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == False, "Expected failure for unauthenticated access"
        print(f"   ✓ Public ticket retrieval correctly requires authentication (401)")

        # Test 7: Test security.txt endpoint
        print("\n7. Testing GET /.well-known/security.txt...")
        response = client.get('/.well-known/security.txt')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.headers['Content-Type'] == 'text/plain; charset=utf-8', "Incorrect Content-Type"
        content = response.get_data(as_text=True)
        assert 'Contact:' in content, "Missing Contact field"
        assert 'Expires:' in content, "Missing Expires field"
        assert 'https://botconnector.id/support?category=security' in content, "Incorrect Contact URL"
        print("   ✓ Security.txt endpoint working correctly")

        # Test 8: Test form validation - missing required fields
        print("\n8. Testing form validation...")
        form_data = {
            'requester_name': '',  # Missing required field
            'requester_email': 'test@example.com',
            'category': 'GENERAL',
            'subject': 'Test Subject',
            'message': 'Test message',
            'product_context': 'Test Product'
        }
        response = client.post('/support', data=form_data)
        assert response.status_code == 400, f"Expected 400 for validation error, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == False, "Expected success=False for validation error"
        assert 'Nama diperlukan' in data['message'] or 'required' in data['message'].lower(), "Should indicate name is required"
        print("   ✓ Form validation working correctly")

        # Test 9: Test abuse protection - honeypot
        print("\n9. Testing abuse protection (honeypot)...")
        form_data = {
            'requester_name': 'Test User',
            'requester_email': 'test@example.com',
            'category': 'GENERAL',
            'subject': 'Test Subject',
            'message': 'Test message',
            'product_context': 'Test Product',
            'url': 'http://example.com'  # Honeypot field filled
        }
        response = client.post('/support', data=form_data)
        # Should be rejected as potential bot
        assert response.status_code == 403, f"Expected 403 for honeypot, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == False, "Expected success=False for honeypot"
        print("   ✓ Abuse protection (honeypot) working correctly")

        print("\n=== ALL TESTS PASSED ===")

if __name__ == '__main__':
    test_comprehensive()
