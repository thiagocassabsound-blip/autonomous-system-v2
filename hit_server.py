import requests

url = "http://localhost:8080/login"
data = {
    "username": "thiagocassab",
    "password": "admin123"
}

print(f"POSTing to {url}...")
try:
    response = requests.post(url, data=data, allow_redirects=False)
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {response.headers}")
    print(f"Content: {response.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
