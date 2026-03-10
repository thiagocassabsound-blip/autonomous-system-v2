import traceback
from api.app import create_app
from core.orchestrator import Orchestrator
from core.event_bus import EventBus
from infrastructure.db import EventLogPersistence

try:
    event_bus = EventBus(EventLogPersistence("test_events.json"))
    orchestrator = Orchestrator(event_bus, None)
    app = create_app(orchestrator)
    app.config['TESTING'] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = "admin"

    print("Testing /dashboard route...")
    response = client.get('/dashboard')
    print(f"Status Code: {response.status_code}")
    if response.status_code == 500:
        print("ERROR 500 DETECTED. The error is likely in the terminal output from Flask.")
    else:
        print("Response successful locally. The issue might be specific to data or environment.")

except Exception as e:
    print("Crash during setup or execution:")
    traceback.print_exc()
