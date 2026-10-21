"""The Python client against the real app (toy engine) served by uvicorn on a free local port, and the examples."""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
import pytest
from digitalfly.api.models import RunConfig
from digitalfly.client import Client, ClientError

ROOT = Path(__file__).resolve().parents[2]
TOY = {"engine": "toy", "neural_model": "connectome", "seed": 3, "speed": 2}


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    import uvicorn
    from digitalfly.main import create_app
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("DIGITALFLY_PORT", str(port))  # the origin the server accepts, as the launcher sets it
    for module in ("digitalfly.simulation.experiment", "digitalfly.main", "digitalfly.data.research"):
        monkeypatch.setattr(f"{module}.ROOT", tmp_path)  # exports and the run library stay in the test folder
    app = create_app(RunConfig(engine="toy"), render=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started and app.state.worker.ready.wait(10)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(30)
    assert not thread.is_alive()


def test_the_client_drives_the_live_app(app_url, tmp_path):
    fly = Client(app_url + "/")
    assert fly.health()["worker_alive"] and fly.capabilities()["recording_limit"] == 30000
    state = fly.reset(TOY)
    assert state["status"] == "paused" and state["config"]["neural_model"] == "connectome" and state["sample"]["t"] == 0
    assert fly.step(3)["sample"]["step"] == 3
    fly.stimulus(10, 5, .5)
    assert fly.status()["config"]["stimulus"] == {"x": 10, "y": 5, "intensity": .5}
    fly.interventions(silence_dna02="left")
    fly.interventions(zero_right=True)  # merged into the current interventions
    interventions = fly.status()["interventions"]
    assert interventions["silence_dna02"] == "left" and interventions["zero_right"]
    assert not fly.interventions(replace=True, zero_left=True)["interventions"]["zero_right"]
    parameters = fly.connectome_parameters(output_gain=2)["config"]["connectome_parameters"]
    assert parameters["output_gain"] == 2 and parameters["circuit"] == "fafb783-dna02"
    fly.run()
    states = list(fly.stream(3))
    assert len(states) == 3 and states[-1]["revision"] > states[0]["revision"]
    reached = fly.wait_until(lambda s: s["sample"]["t"] >= .3, timeout=30)
    assert reached["sample"]["t"] >= .3 and fly.pause()["status"] == "paused"
    with pytest.raises(TimeoutError, match="did not hold"):
        fly.wait_until(lambda s: s["status"] == "running", timeout=.3)
    saved = fly.export(share_safe=True)
    assert saved["samples"] > 30 and Path(saved["path"]).parent == tmp_path / "runs"
    page = fly.runs(limit=5)
    assert page["total"] == 1 and page["runs"][0]["key"] == Path(saved["path"]).name
    assert fly.saved_run(page["runs"][0]["key"])["key"] == page["runs"][0]["key"]
    # reset() restarts from the current configuration; settings change single values.
    again = fly.reset(seed=5, **{"connectome_parameters.dynamics": "spiking"})
    assert again["config"]["engine"] == "toy" and again["config"]["seed"] == 5
    assert again["config"]["connectome_parameters"]["dynamics"] == "spiking" and again["sample"]["t"] == 0


def test_refusals_raise_client_errors_with_the_servers_reason(app_url):
    fly = Client(app_url)
    fly.reset(TOY)
    with pytest.raises(ClientError) as refused:
        fly.stimulus(999, 0)
    assert refused.value.status == 422 and "x:" in str(refused.value) and "\n" not in str(refused.value)
    with pytest.raises(ClientError) as refused:
        fly.interventions(silence_types=["NotAType"])
    assert refused.value.status == 422 and "NotAType" in str(refused.value)
    fly.run()
    with pytest.raises(ClientError) as refused:
        fly.step()
    assert refused.value.status == 409 and "paused" in refused.value.detail
    fly.pause()
    with pytest.raises(ClientError) as refused:
        fly.saved_run("20260101T000000-00000000-000000")
    assert refused.value.status == 404
    stranger = Client(app_url)
    stranger.origin = "http://evil.example"  # the Origin header is what the server checks
    with pytest.raises(ClientError) as refused:
        stranger.run()
    assert refused.value.status == 403
    with pytest.raises(ValueError):
        Client("ws://127.0.0.1:8000")


def test_the_drive_example_runs_against_the_app(app_url):
    done = subprocess.run([sys.executable, str(ROOT / "examples/drive_app.py"), "--url", app_url, "--engine", "toy",
                           "--seconds", ".3", "--speed", "2"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert "DNa02 left silenced" in done.stdout and "Exported" in done.stdout


def test_the_batch_example_runs_offline(tmp_path):
    done = subprocess.run([sys.executable, str(ROOT / "examples/batch_seeds.py"), "--seeds", "1-2", "--duration", ".2",
                           "--out", str(tmp_path / "batch")], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    assert "| rate |" in done.stdout and (tmp_path / "batch.jsonl").read_text().count("\n") == 8
