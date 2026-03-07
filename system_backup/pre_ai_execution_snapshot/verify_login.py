import sys
import threading
import time
import urllib.request
import urllib.parse
from werkzeug.serving import make_server

from production_launcher import app, orchestrator_instance

class ServerThread(threading.Thread):
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.server = make_server('127.0.0.1', 8080, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        print('Starting server...')
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()

def verify():
    base_url = "http://127.0.0.1:8080"
    
    import requests
    session = requests.Session()
    session.headers.update({"User-Agent": "TestClient"})

    # Wait for server to be ready
    for _ in range(30):
        try:
            res = session.get(base_url + '/')
            if res.status_code == 200:
                print("[PASS] System reachable")
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    else:
        print("[FAIL] Server failed to start on time")
        sys.exit(1)

    # 1. Test GET /login
    res = session.get(f"{base_url}/login")
    if res.status_code == 200 and "Autonomous System" in res.text:
        print("[PASS] GET /login loaded correctly, Jinja output success")
    else:
        print(f"[FAIL] GET /login returned {res.status_code}")
        print("Response Snippet:", res.text[:200])
        sys.exit(1)

    # 2. Test POST /login (Authentication)
    res = session.post(f"{base_url}/login", data={"username": "admin", "password": "admin"}, allow_redirects=False)
    if res.status_code == 302 and "/dashboard" in res.headers.get("Location", ""):
        print("[PASS] POST /login authenticated and redirected to /dashboard")
    else:
        print(f"[FAIL] POST /login authentication failed. Status: {res.status_code}, Headers: {res.headers}")
        sys.exit(1)

    # 3. Test GET /dashboard (with session)
    res = session.get(f"{base_url}/dashboard")
    if res.status_code == 200 and "Dashboard" in res.text:
        print("[PASS] GET /dashboard loaded successfully after login")
    else:
        print(f"[FAIL] GET /dashboard returned {res.status_code}")
        print("Response Snippet:", res.text[:200])
        sys.exit(1)

    # 4. Test logout
    res = session.get(f"{base_url}/logout", allow_redirects=False)
    if res.status_code == 302 and "/login" in res.headers.get("Location", ""):
        print("[PASS] GET /logout works correctly")
    else:
        print(f"[FAIL] GET /logout failed. Status: {res.status_code}")
        sys.exit(1)

    print("ALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    server = ServerThread(app)
    server.start()
    time.sleep(1)
    try:
        verify()
    finally:
        server.shutdown()
        server.join()
