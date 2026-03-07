import os
import json
import requests
import datetime
from dotenv import load_dotenv

def test_resend():
    load_dotenv()
    api_key = os.getenv("RESEND_API_KEY")
    
    if not api_key:
        print(json.dumps({
            "status": "failure",
            "error": "RESEND_API_KEY missing",
            "timestamp": datetime.datetime.now().isoformat()
        }))
        return

    # Masked prefix
    print(f"RESEND_API_KEY prefix: {api_key[:6]}...")

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "from": "Infra Test <onboarding@resend.dev>",
        "to": ["thiagocassabsound@gmail.com"],
        "subject": "Infra Test — Resend Validation",
        "html": "<strong>Resend Infra Test Successful</strong>"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        result = {
            "status": "success" if response.status_code in [200, 201, 202] else "failure",
            "http_status": response.status_code,
            "response": response.json() if response.text else "No response body",
            "timestamp": datetime.datetime.now().isoformat()
        }
        print(json.dumps(result, indent=2))

    except requests.exceptions.Timeout:
        print(json.dumps({"status": "failure", "error": "Timeout", "timestamp": datetime.datetime.now().isoformat()}))
    except requests.exceptions.ConnectionError:
        print(json.dumps({"status": "failure", "error": "ConnectionError", "timestamp": datetime.datetime.now().isoformat()}))
    except Exception as e:
        print(json.dumps({"status": "failure", "error": str(e), "timestamp": datetime.datetime.now().isoformat()}))

if __name__ == "__main__":
    test_resend()
