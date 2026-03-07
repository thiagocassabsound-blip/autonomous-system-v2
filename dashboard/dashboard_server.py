import sys
import os
import json
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from dashboard.dashboard_api import DashboardAPI
from infra.observability.async_worker import AsyncLogWorker
from core.event_bus import EventBus
from datetime import datetime, timezone

FRONTEND_DIR = os.path.join(BASE_DIR, "dashboard", "frontend")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
RUNTIME_LOG_FILE = os.path.join(LOGS_DIR, "runtime_events.log")

# We create an isolated EventBus instance here strictly to PUBLISH intents
# Since it's pub/sub and persists to ledger, the Orchestrator (in main process)
# will pick it up or we can just append it directly to the bus mechanics if shared.
# To be perfectly safe, the dashboard emits events that get persisted to the ledger, 
# then the main Orchestrator processes them on the next load.
# For runtime sharing, let's keep it simple: it logs the intent event natively.

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    pass

class DashboardRequestHandler(SimpleHTTPRequestHandler):
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*') # Allow local testing
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def log_dashboard_event(self, event_type, details):
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "product_id": "DASHBOARD",
                "payload": details
            }
            AsyncLogWorker().push(RUNTIME_LOG_FILE, entry)
        except Exception:
            pass

    def do_GET(self):
        req_path = self.path.split('?')[0].rstrip('/')
        if req_path.startswith("/api/dashboard"):
            self.log_dashboard_event("dashboard_api_request", {"endpoint": req_path})
            
            response_data = {}
            if req_path == "/api/dashboard/system_overview":
                response_data = DashboardAPI.get_system_overview()
            elif req_path == "/api/dashboard/radar":
                response_data = DashboardAPI.get_radar()
            elif req_path == "/api/dashboard/products":
                response_data = DashboardAPI.get_products()
            elif req_path == "/api/dashboard/landings":
                response_data = DashboardAPI.get_landings()
            elif req_path == "/api/dashboard/traffic":
                response_data = DashboardAPI.get_traffic()
            elif req_path == "/api/dashboard/revenue":
                response_data = DashboardAPI.get_revenue()
            elif req_path == "/api/dashboard/intelligence":
                response_data = DashboardAPI.get_intelligence()
            elif req_path == "/api/dashboard/health":
                response_data = DashboardAPI.get_health()
            elif req_path == "/api/dashboard/evolution":
                response_data = DashboardAPI.get_evolution()
            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": f"endpoint not found: {req_path}"}).encode())
                return
                
            self._set_headers(200)
            self.wfile.write(json.dumps(response_data).encode())
        else:
            # Fallback to static files
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/dashboard/intent":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                intent_payload = json.loads(post_data)
                
                # We emit an intent event to the formal log!
                # Since the dashboard runs isolated from main orchestrator loop, 
                # we record it passively to the runtime event log, 
                # or pass it to an active EventBus queue if available. 
                # For this implementation, we just stream it to observability safely.
                # (A real system might write this to EventBus ledger so Orchestrator picks it up)
                
                # 1. Log to Observability
                self.log_dashboard_event("dashboard_intent_event", intent_payload)
                
                # 2. To officially place into event bus, we'd need EventBus persistence.
                eb = EventBus()
                eb.emit(
                    intent_payload.get("event") or "dashboard_intent_event", 
                    intent_payload.get("data", {})
                )

                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "intent_routed", "action": "emitted to EventBus"}).encode())
            
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self._set_headers(404)

def run_server(port=8130):
    os.makedirs(FRONTEND_DIR, exist_ok=True)
    server_address = ('', port)
    httpd = ThreadedHTTPServer(server_address, DashboardRequestHandler)
    print(f"[*] Dashboard UI/API Server running isolated on port {port}...")
    
    # Log startup
    try:
        AsyncLogWorker().push(RUNTIME_LOG_FILE, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "dashboard_loaded",
            "product_id": "DASHBOARD",
            "payload": {"port": port}
        })
    except Exception: pass
    
    httpd.serve_forever()

if __name__ == "__main__":
    run_server()
