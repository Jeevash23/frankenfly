"""Exercise a running local deployment, including the proxied WebSocket."""
import argparse
import json
import time
from urllib.parse import urlparse
import httpx
from websockets.sync.client import connect

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
args = parser.parse_args()
assert urlparse(args.url).hostname in {"localhost", "127.0.0.1"}, "Local probes only"
with httpx.Client(base_url=args.url, timeout=10) as client:
    health = client.get("/api/health").raise_for_status().json()
    for _ in range(600):
        state = client.get("/api/status").raise_for_status().json()
        if state["status"] != "initializing":
            break
        time.sleep(.1)
    assert state["status"] == "paused", state["error"]
    assert "DigitalFly" in client.get("/").raise_for_status().text
    assert client.get("/api/not-real").status_code == 404
    with connect(args.url.replace("http://", "ws://") + "/api/ws", origin=args.url, max_queue=1) as ws:
        message = json.loads(ws.recv(timeout=10))
        assert message["instance_id"] == health["instance_id"]
    stepped = client.post("/api/step", json={}).raise_for_status().json()
    assert stepped["sample"]["step"] == state["sample"]["step"] + 1
    assert stepped["rendering"]
    assert client.get("/api/frame").raise_for_status().content[:2] == b"\xff\xd8"
    client.post("/api/reset", json=state["config"]).raise_for_status()
    print(json.dumps({"url": args.url, "ui": True, "http_commands": True, "websocket": True,
                      "real_physics_step": True, "rendering": True, "api_fallback_404": True,
                      "same_instance": True, "final_status": "paused"}, indent=2))
