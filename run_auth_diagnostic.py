import os
import sys
import unittest
from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.getcwd())

# Ensure env is loaded
load_dotenv(override=True)

from production_launcher import bootstrap
from api.app import create_app

class TestAuthDiagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to ensure the module sees the LATEST env
        from importlib import reload
        import api.routes.dashboard_routes
        reload(api.routes.dashboard_routes)
        
        cls.orchestrator = bootstrap()
        cls.app = create_app(cls.orchestrator)
        cls.app.config['TESTING'] = True
        cls.app.config['SECRET_KEY'] = 'test-secret'
        cls.client = cls.app.test_client()

    def test_internal_login_trace(self):
        """Perform a simulated login and capture stdout trace."""
        print(f"\n--- PERFORMING INTERNAL LOGIN TRACE ---")
        
        # User requested credentials
        test_username = "thiagocassab"
        test_password = "admin123"
        
        print(f"Targeting: /login with {test_username} / [Len: {len(test_password)}]")
        
        response = self.client.post("/login", data={
            "username": test_username,
            "password": test_password
        }, follow_redirects=False)
        
        print(f"Status: {response.status_code}")
        print(f"Location: {response.headers.get('Location')}")
        
        if response.status_code == 302 and "/dashboard" in response.headers.get('Location', ''):
            print("FINAL RESULT: SUCCESS ✅")
        else:
            print("FINAL RESULT: FAILURE ❌")
        
        print(f"----------------------------------------")

if __name__ == '__main__':
    unittest.main()
