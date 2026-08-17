import urllib.request
import json

url = 'http://127.0.0.1:8000/api/v1/auth/login'
headers = {'Content-Type': 'application/json'}
data = {'email': 'citizen@example.com', 'password': 'password123'}

req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
try:
    with urllib.request.urlopen(req) as response:
        print(f"Login success: {response.read().decode('utf-8')}")
except Exception as e:
    print(f"Login failed: {e}")
