import os
import sys
import unittest
from flask import session

# Add system root to path
sys.path.append(os.getcwd())

from production_launcher import bootstrap
from api.app import create_app

class TestAuthenticationNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrator = bootstrap()
        cls.app = create_app(cls.orchestrator)
        cls.app.config['TESTING'] = True
        cls.app.config['SECRET_KEY'] = 'test-secret'
        cls.client = cls.app.test_client()
        
        # Read from the actual loaded variables in the module
        from api.routes.dashboard_routes import DASHBOARD_USER, DASHBOARD_PASSWORD
        cls.username = DASHBOARD_USER
        cls.password = DASHBOARD_PASSWORD

    def test_standard_admin_login(self):
        """Test login using ADMIN_USERNAME and ADMIN_PASSWORD."""
        response = self.client.post("/login", data={
            "username": self.username,
            "password": self.password
        }, follow_redirects=False)
        
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dashboard")
        
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("authenticated"))
            self.assertEqual(sess.get("username"), self.username)

    def test_invalid_login(self):
        """Test login with incorrect credentials."""
        response = self.client.post("/login", data={
            "username": "wronguser",
            "password": "wrongpassword"
        }, follow_redirects=True)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid credentials", response.data.decode('utf-8'))

if __name__ == '__main__':
    unittest.main()
