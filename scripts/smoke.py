"""Read-only rollout verification; optional version as second argument."""
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")


def get(path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        assert response.status == 200
        return json.load(response)


assert get("/health/live") == {"status": "ok"}
assert get("/health/ready") == {"status": "ready"}
if len(sys.argv) > 2:
    assert get("/version")["version"] == sys.argv[2], "Wrong release deployed"
print("PASS: liveness, database readiness, and requested version")
