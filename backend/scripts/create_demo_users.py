
import urllib.request
import json

url = 'http://127.0.0.1:8000/api/v1/auth/register'
headers = {'Content-Type': 'application/json'}

users = [
    {'email': 'citizen@example.com', 'password': 'password123', 'role': 'CITIZEN'},
    {'email': 'authority@example.com', 'password': 'password123', 'role': 'AUTHORITY'}
]

for user in users:
    req = urllib.request.Request(url, data=json.dumps(user).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Created {user['email']}: {response.read().decode('utf-8')}")
    except Exception as e:
        print(f"Failed to create {user['email']}: {e}")
