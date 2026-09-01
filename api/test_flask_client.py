from app import app

def test_support_endpoints():
    """Test support endpoints using Flask test client"""
    with app.test_client() as client:
        # Test GET /support
        print("Testing GET /support...")
        response = client.get('/support')
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ GET /support successful")
        else:
            print("  ✗ GET /support failed")

        # Test GET /support/tickets (should require login, so expect redirect or 401)
        print("\nTesting GET /support/tickets (no login)...")
        response = client.get('/support/tickets')
        print(f"  Status: {response.status_code}")
        # This should either redirect to login or return 401 since no user is logged in
        if response.status_code in [302, 401]:
            print("  ✓ GET /support/tickets correctly requires login")
        else:
            print(f"  ? GET /support/tickets returned {response.status_code}")

        # Test POST /support (form submission)
        print("\nTesting POST /support (form submission)...")
        form_data = {
            'requester_name': 'Test User',
            'requester_email': 'test@example.com',
            'category': 'GENERAL',
            'subject': 'Test Subject',
            'message': 'Test message',
            'product_context': 'Test Product'
        }
        response = client.post('/support', data=form_data)
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ POST /support successful")
            # Try to parse JSON response
            try:
                data = response.get_json()
                if data and data.get('success'):
                    print(f"    Ticket reference: {data.get('reference', 'N/A')}")
                else:
                    print(f"    Response: {data}")
            except Exception as e:
                print(f"    Could not parse JSON response: {e}")
        else:
            print("  ✗ POST /support failed")
            try:
                error_data = response.get_json()
                print(f"    Error: {error_data}")
            except:
                print(f"    Response text: {response.get_data(as_text=True)[:100]}...")

        # Test GET /.well-known/security.txt
        print("\nTesting GET /.well-known/security.txt...")
        response = client.get('/.well-known/security.txt')
        print(f"  Status: {response.status_code}")
        if response.status_code == 200:
            print("  ✓ GET /.well-known/security.txt successful")
            content = response.get_data(as_text=True)
            if 'Contact:' in content and 'Expires:' in content:
                print("  ✓ Security.txt content appears correct")
            else:
                print("  ✗ Security.txt content missing expected fields")
        else:
            print("  ✗ GET /.well-known/security.txt failed")

if __name__ == '__main__':
    test_support_endpoints()
