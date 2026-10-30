"""Testes unitarios e de integracao do Redroid Farm."""

import json
import urllib.request
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import server

# 1. Test port allocation logic
containers = server.get_docker_containers()
assert isinstance(containers, list), "Containers should be a list"

next_port = server.get_next_available_port(5556)
assert next_port >= 5556, "Next port should be >= 5556"

# 2. Test apk listing
apks = list(server.APKS_DIR.glob("*.apk"))
assert len(apks) >= 1, "Expected at least PlayBots apk in apks/"
print(f"OK: found {len(apks)} apks in repository.")

# 3. Test running container presence
phone_1 = next((c for c in containers if c["name"] == "redroid-phone-1"), None)
if phone_1:
    assert phone_1["adb_port"] == 5556, f"Expected port 5556, got {phone_1['adb_port']}"
    print("OK: redroid-phone-1 detected on port 5556.")

print("OK: all self-checks passed.")
