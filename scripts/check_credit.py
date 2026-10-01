import sys
import json
import urllib.request
import urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import OPENROUTER_API_KEY

req = urllib.request.Request(
    "https://openrouter.ai/api/v1/key",
    headers={
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "User-Agent": "Mozilla/5.0",
    },
)

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())["data"]
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
    sys.exit(1)

limit = data.get("limit")
remaining = data.get("limit_remaining")

print(f"Key label: {data.get('label')}")
print(f"Total usage (all time): ${data.get('usage', 0):.4f}")
print(f"Usage today:            ${data.get('usage_daily', 0):.4f}")
print(f"Usage this month:       ${data.get('usage_monthly', 0):.4f}")
print()

if limit is None:
    print("No per-key spending cap set - this only means the key itself has")
    print("no configured limit, NOT that your account balance is unlimited.")
    print("Check your actual account balance at https://openrouter.ai/credits")
else:
    print(f"Per-key spending cap: ${limit:.4f}")
    print(f"Remaining on this key: ${remaining:.4f}")