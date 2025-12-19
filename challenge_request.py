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

URL = "http://localhost:5000/api/generate-challenge"

# adjust if your endpoint expects JSON payload
payload = {}

response = requests.post(URL, json=payload, timeout=REQUEST_TIMEOUT)

print("Status:", response.status_code)
print("Headers:", response.headers)
print("Body:", response.text)
