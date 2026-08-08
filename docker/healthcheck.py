import json
import sys
import urllib.request


try:
    with urllib.request.urlopen(
        "http://127.0.0.1:18793/api/health",
        timeout=3,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
        raise SystemExit(0 if response.status == 200 and payload.get("ok") is True else 1)
except Exception:
    raise SystemExit(1)
