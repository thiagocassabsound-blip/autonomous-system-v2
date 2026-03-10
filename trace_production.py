import requests
import json

url = "https://app.fastoolhub.com/login"
payload = {
    "username": "thiagocassab",
    "password": "admin123"
}

print(f"--- PRODUCTION TRACE START ---")
print(f"Target: {url}")
print(f"Payload: {json.dumps(payload)}")

try:
    # Disable redirects to capture 302
    response = requests.post(url, data=payload, allow_redirects=False, timeout=10)
    
    print(f"STATUS_CODE: {response.status_code}")
    print(f"REDIRECT_LOCATION: {response.headers.get('Location')}")
    print(f"SET_COOKIE: {response.headers.get('Set-Cookie')}")
    
    print(f"\n--- RESPONSE HEADERS ---")
    for k, v in response.headers.items():
        print(f"{k}: {v}")
        
    if response.status_code == 302 and "/dashboard" in response.headers.get('Location', ''):
        print("\nRESULT: SUCCESS ✅")
    else:
        print("\nRESULT: FAILURE ❌")
        
except Exception as e:
    print(f"ERROR: {e}")

print(f"--- PRODUCTION TRACE END ---")
