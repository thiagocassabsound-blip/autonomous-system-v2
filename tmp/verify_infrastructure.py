import requests
import json
import sys

BASE_URL = "http://localhost:8080"

endpoints = [
    "/",
    "/health",
    "/system/state",
    "/runtime-status"
]

def test_endpoints():
    print(f"Testing endpoints at {BASE_URL}...")
    all_passed = True
    for endpoint in endpoints:
        url = f"{BASE_URL}{endpoint}"
        try:
            response = requests.get(url, timeout=5)
            print(f"GET {url} -> Status: {response.status_code}")
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"  Response: {json.dumps(data, indent=2)[:200]}...")
                except:
                    print(f"  Response (Text): {response.text[:100]}...")
            else:
                print(f"  FAILED: Unexpected status code")
                all_passed = False
        except Exception as e:
            print(f"  ERROR connecting to {url}: {e}")
            all_passed = False
    
    if all_passed:
        print("\nAll core infrastructure endpoints are responding.")
    else:
        print("\nSome endpoints failed or were unreachable. Ensure the server is running.")

if __name__ == "__main__":
    test_endpoints()
