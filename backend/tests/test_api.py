import time
from fastapi.testclient import TestClient
import pytest
from digitalfly.api.models import RunConfig
from digitalfly.main import create_app, extra_origins


@pytest.fixture
def client(tmp_path, monkeypatch):
    # API test exports belong to the test directory, never the user's run library.
    monkeypatch.setattr('digitalfly.simulation.experiment.ROOT', tmp_path)
    monkeypatch.setattr('digitalfly.main.ROOT', tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client
    assert not app.state.worker.thread.is_alive()


def test_pause_step_run_reset(client):
    initial = client.get("/api/status").json()
    time.sleep(.04)
    assert client.get("/api/status").json()["sample"]["t"] == 0
    stepped = client.post("/api/step", json={}).json()
    assert stepped["sample"]["t"] == .01 and stepped["status"] == "paused"
    assert client.post("/api/run", json={}).status_code == 200
    assert client.post("/api/step", json={}).status_code == 409
    time.sleep(.2)
    paused = client.post("/api/pause", json={}).json()
    time.sleep(.05)
    assert client.get("/api/status").json()["sample"] == paused["sample"]
    assert client.get("/api/status").json()["wall_s"] == paused["wall_s"]
    reset = client.post("/api/reset", json=RunConfig(engine="toy").model_dump()).json()
    assert reset["sample"] == initial["sample"]
    assert reset["run_id"] != initial["run_id"]


def test_input_validation_and_local_boundary(client):
    assert client.post("/api/stimulus", json={"x": 999}).status_code == 422
    assert client.post("/api/stimulus", content='{"x":NaN}', headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/interventions", json={"silence": "invented"}).status_code == 422
    assert client.post("/api/run", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/run", content="{}").status_code == 415
    assert client.get("/api/run").status_code in [404, 405]
    assert client.get("/api/not-real").status_code == 404
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/exports/not-a-run.zip").status_code == 404


def test_allowed_origins_extend_origin_host_and_csp_together(tmp_path, monkeypatch):
    monkeypatch.setattr('digitalfly.main.ROOT', tmp_path)
    monkeypatch.setenv("DIGITALFLY_ALLOWED_ORIGINS", " http://localhost:9000, https://Workstation.lan:8443/ ")
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        for origin in ["http://localhost:9000", "https://workstation.lan:8443", "http://127.0.0.1:8000"]:
            assert client.post("/api/pause", json={}, headers={"Origin": origin}).status_code == 200, origin
        assert client.post("/api/pause", json={}, headers={"Origin": "http://localhost:9001"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "workstation.lan:8443"}).status_code == 200
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
        csp = client.get("/api/health").headers["Content-Security-Policy"]
        assert "connect-src 'self' ws://127.0.0.1:* ws://localhost:* ws://localhost:9000 wss://workstation.lan:8443;" in csp
    monkeypatch.delenv("DIGITALFLY_ALLOWED_ORIGINS")
    assert extra_origins(None) == [] and extra_origins("") == []
    for bad in ["localhost:9000", "http://localhost:9000/app", "http://[::1]:8000", "ftp://localhost", "*"]:
        with pytest.raises(ValueError, match="DIGITALFLY_ALLOWED_ORIGINS"):
            extra_origins(bad)


def test_multi_subscriber_reconnect_one_worker(client):
    headers = {"Origin": "http://127.0.0.1:8000"}
    with client.websocket_connect("ws://127.0.0.1:8000/api/ws", headers=headers) as first:
        a = first.receive_json()
        with client.websocket_connect("ws://127.0.0.1:8000/api/ws", headers=headers) as second:
            b = second.receive_json()
            assert a["instance_id"] == b["instance_id"]
            assert b["subscribers"] == 2
            client.post("/api/step", json={})
            for _ in range(10):
                b = second.receive_json()
                if b["sample"]["step"] == 1:
                    break
            assert b["sample"]["step"] == 1
    with client.websocket_connect("ws://127.0.0.1:8000/api/ws", headers=headers) as third:
        c = third.receive_json()
        assert c["instance_id"] == a["instance_id"]
        assert c["sample"]["step"] == 1
    time.sleep(.02)
    assert client.get("/api/status").json()["subscribers"] == 0
    assert client.app.state.worker.commands.maxsize == 64


def test_forbidden_websocket_origin(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:8000/api/ws", headers={"Origin": "http://evil.example"}):
            pass


def test_export_and_intervention_commands(client):
    client.post("/api/stimulus", json={"x": -8, "y": 3, "intensity": .5})
    state = client.post("/api/interventions", json={"zero_left": True, "silence": "descending"}).json()
    assert state["sample"]["sensors"]["left"] == 0
    assert state["sample"]["motor"] == [0, 0]
    assert state["events"][-1]["step"] == 0
    data = client.post("/api/export", json={}).json()
    download = client.get(data["download_url"])
    assert download.status_code == 200 and download.content[:2] == b"PK"


def test_numerical_failure_is_controlled(client):
    def fail(motor):
        raise FloatingPointError("injected numerical failure")
    client.app.state.worker.experiment.body.advance = fail
    assert client.post("/api/step", json={}).status_code == 500
    state = client.get("/api/status").json()
    assert state["status"] == "error" and "injected" in state["error"]
    assert client.post("/api/run", json={}).status_code == 409


@pytest.mark.flygym
@pytest.mark.render
def test_flygym_graphics_owned_by_worker():
    app = create_app(render=True)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # A cold Matplotlib font cache alone can take ~20 s on a fresh checkout.
        assert app.state.worker.ready.wait(90)
        state = client.get("/api/status").json()
        assert state["status"] == "paused", state["error"]
        assert state["rendering"], state["render_error"]
        assert client.get("/api/frame").content[:2] == b"\xff\xd8"
        assert client.post("/api/step", json={}).json()["sample"]["step"] == 1
    assert not app.state.worker.thread.is_alive()
