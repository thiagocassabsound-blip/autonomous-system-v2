import os
import sys
import unittest
from flask import session

# Add system root to path
sys.path.append(os.getcwd())

from production_launcher import bootstrap
from api.app import create_app

class TestDashboardRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orchestrator = bootstrap()
        cls.app = create_app(cls.orchestrator)
        cls.app.config['TESTING'] = True
        cls.app.config['SECRET_KEY'] = 'test-secret'
    def setUp(self):
        self.client = self.app.test_client()

    def login(self):
        """Helper to simulate login."""
        with self.client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

    def test_routes_exist(self):
        self.login()
        routes = [
            '/dashboard',
            '/dashboard/radar',
            '/dashboard/opportunities',
            '/dashboard/products',
            '/dashboard/analytics',
            '/dashboard/settings'
        ]
        
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, f"Route {route} failed")
                # Check for section markers or specific content
                html = response.data.decode('utf-8')
                self.assertIn('Autonomous System', html)
                self.assertIn('nav-bar', html)
                
                if route == '/dashboard':
                    self.assertIn('System Status Overview', html)
                elif route == '/dashboard/radar':
                    self.assertIn('Full Radar History', html)
                elif route == '/dashboard/opportunities':
                    self.assertIn('Strategic Opportunities', html)
                elif route == '/dashboard/products':
                    self.assertIn('All Products', html)

    def test_unauthenticated_redirect(self):
        routes = ['/dashboard', '/dashboard/radar']
        for route in routes:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.location)

if __name__ == '__main__':
    unittest.main()
