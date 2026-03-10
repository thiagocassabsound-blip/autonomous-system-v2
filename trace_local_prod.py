import requests

url = "http://localhost:8080/login"
payload = {
    "username": "thiagocassab",
    "password": "admin123"
}

print(f"--- LOCAL PRODUCTION TRACE ---")
try:
    response = requests.post(url, data=payload, allow_redirects=False, timeout=5)
    print(f"STATUS: {response.status_code}")
    print(f"LOCATION: {response.headers.get('Location')}")
    if response.status_code == 302:
        print("RESULT: SUCCESS ✅")
    else:
        print("RESULT: FAILURE ❌")
except Exception as e:
    print(f"ERROR: {e}")
