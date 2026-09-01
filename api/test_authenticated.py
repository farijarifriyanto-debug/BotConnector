from app import app
import os

def test_authenticated_access():
    """Test authenticated access to support tickets"""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'support', 'data', 'support.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    with app.test_client() as client:
        print("=== AUTHENTICATED ACCESS TEST ===\n")

        # Simulate login for user 1 by setting session BEFORE creating tickets
        print("1. Setting up user sessions and creating tickets...")

        # Login as user 1
        with client.session_transaction() as sess:
            sess['user_id'] = 'user1@example.com'

        # Create ticket for user 1 (while logged in)
        form_data_user1 = {
            'requester_name': 'User One',
            'requester_email': 'user1@example.com',
            'category': 'GENERAL',
            'subject': 'User 1 General Question',
            'message': 'This is a question from user 1.',
            'product_context': 'General'
        }
        response = client.post('/support', data=form_data_user1)
        assert response.status_code == 200
        user1_ticket_ref = response.get_json()['reference']
        print(f"   ✓ User 1 ticket created: {user1_ticket_ref}")

        # Login as user 2
        with client.session_transaction() as sess:
            sess['user_id'] = 'user2@example.com'

        # Create ticket for user 2 (while logged in)
        form_data_user2 = {
            'requester_name': 'User Two',
            'requester_email': 'user2@example.com',
            'category': 'SECURITY_REPORT',
            'subject': 'User 2 Security Concern',
            'message': 'This is a security concern from user 2.',
            'product_context': 'Security'
        }
        response = client.post('/support', data=form_data_user2)
        assert response.status_code == 200
        user2_ticket_ref = response.get_json()['reference']
        print(f"   ✓ User 2 ticket created: {user2_ticket_ref}")

        # Test user 1 accessing their tickets
        print("\n2. Testing authenticated access for User 1...")
        # Re-establish user 1 session
        with client.session_transaction() as sess:
            sess['user_id'] = 'user1@example.com'

        response = client.get('/support/tickets')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert len(data['tickets']) == 1, f"Expected 1 ticket for user 1, got {len(data['tickets'])}"
        ticket_ref = data['tickets'][0]['public_reference']
        assert ticket_ref == user1_ticket_ref, f"Expected user 1's ticket ref, got {ticket_ref}"
        print(f"   ✓ User 1 can see their own ticket: {ticket_ref}")
        print(f"   ✓ User 1 cannot see user 2's ticket (correctly hidden)")

        # Try to access user 2's ticket directly by reference - should be denied
        print("\n3. Testing cross-user ticket access prevention...")
        response = client.get(f'/support/ticket/{user2_ticket_ref}')
        # Should be 403 Forbidden because user 1 is trying to access user 2's ticket
        assert response.status_code == 403, f"Expected 403 for cross-user access, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == False
        print("   ✓ Cross-user ticket access correctly prevented (403 Forbidden)")

        # Now test as user 2
        print("\n4. Testing authenticated access for User 2...")
        # Re-establish user 2 session
        with client.session_transaction() as sess:
            sess['user_id'] = 'user2@example.com'

        # Get user 2's tickets - should see their own ticket
        response = client.get('/support/tickets')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert len(data['tickets']) == 1, f"Expected 1 ticket for user 2, got {len(data['tickets'])}"
        ticket_ref = data['tickets'][0]['public_reference']
        assert ticket_ref == user2_ticket_ref, f"Expected user 2's ticket ref, got {ticket_ref}"
        print(f"   ✓ User 2 can see their own ticket: {ticket_ref}")
        print(f"   ✓ User 2 cannot see user 1's ticket (correctly hidden)")

        # Try to access user 1's ticket directly by reference - should be denied
        response = client.get(f'/support/ticket/{user1_ticket_ref}')
        assert response.status_code == 403, f"Expected 403 for cross-user access, got {response.status_code}"
        data = response.get_json()
        assert data['success'] == False
        print("   ✓ Cross-user ticket access correctly prevented (403 Forbidden)")

        print("\n=== ALL AUTHENTICATED TESTS PASSED ===")

if __name__ == '__main__':
    test_authenticated_access()
