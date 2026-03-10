import os
import sys
import unittest
from flask import session

# Add system root to path
sys.path.append(os.getcwd())

from production_launcher import bootstrap
from api.app import create_app

class TestLoginAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrator = bootstrap()
        cls.app = create_app(cls.orchestrator)
        cls.app.config['TESTING'] = True
        cls.app.config['SECRET_KEY'] = 'test-secret'
        cls.client = cls.app.test_client()
        
        # Access the variables directly from the module
        import api.routes.dashboard_routes as dr
        cls.username = dr.DASHBOARD_USER
        cls.password = dr.DASHBOARD_PASSWORD

    def test_simulated_login(self):
        """Simulate a login with actual environment credentials."""
        print(f"\n--- START TRACE TEST ---")
        print(f"Internal Module State: '{self.username}' / [Len: {len(self.password)}]")
        
        response = self.client.post("/login", data={
            "username": self.username,
            "password": self.password
        }, follow_redirects=False)
        
        print(f"Status: {response.status_code}")
        print(f"Location: {response.headers.get('Location')}")
        
    def test_case_sensitive_login(self):
        """Test if 'ThiagoCassab' matches 'thiagocassab'."""
        print(f"\n--- CASE SENSITIVITY TEST ---")
        username_mixed = "ThiagoCassab"
        response = self.client.post("/login", data={
            "username": username_mixed,
            "password": self.password
        }, follow_redirects=False)
        
        print(f"Testing Username: '{username_mixed}'")
        print(f"Status: {response.status_code}")
        
        # If it's a 200, it means it failed (re-rendered login)
        if response.status_code == 200:
            print("RESULT: FAILURE ❌ (Username is case-sensitive)")
        else:
            print("RESULT: SUCCESS ✅")
        print(f"--- END CASE SENSITIVITY TEST ---")
