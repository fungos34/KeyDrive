import sys
from pathlib import Path

import requests

# Add project root to path for core imports
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.limits import Limits

    REQUEST_TIMEOUT = Limits.TIMEOUT_SHORT
except ImportError:
    REQUEST_TIMEOUT = 10

URL = "http://localhost:5000/api/verify-challenge"
SERVER_ENDPOINT = "http://localhost:5000"

if len(sys.argv) != 3:
    print("Usage: python challenge_verification.py <challenge_id> <client_hash>")
    sys.exit(1)

challenge_id = sys.argv[1]
client_hash = sys.argv[2]

payload = {"challenge_id": challenge_id, "client_hash": client_hash, "server_endpoint": SERVER_ENDPOINT}

response = requests.post(URL, json=payload, timeout=REQUEST_TIMEOUT)

print(response.text)
