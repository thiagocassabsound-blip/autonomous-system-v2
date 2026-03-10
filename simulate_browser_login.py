import os
import sys
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_URL = "http://localhost:8080" # Assuming the system is running locally for the trace
LOGIN_URL = f"{BASE_URL}/login"

# Standard credentials from .env
username = os.getenv("ADMIN_USERNAME")
password = os.getenv("ADMIN_PASSWORD")

print(f"--- SIMULATING BROWSER LOGIN ---")
print(f"Target: {LOGIN_URL}")
print(f"Username: {username}")
print(f"Password Length: {len(password) if password else 0}")

# Browser-identical form submission (application/x-www-form-urlencoded)
payload = {
    "username": username,
    "password": password
}

try:
    # We use a session to track cookies (if needed later)
    session = requests.Session()
    response = session.post(LOGIN_URL, data=payload, allow_redirects=False)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response Location: {response.headers.get('Location')}")
    print(f"Cookies: {session.cookies.get_dict()}")
    
    if response.status_code == 302 and "/dashboard" in response.headers.get('Location', ''):
        print("RESULT: SUCCESS ✅")
    else:
        print("RESULT: FAILURE ❌")
        
except Exception as e:
    print(f"ERROR: {e}")
