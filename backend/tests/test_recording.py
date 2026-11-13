"""Recording limits, lean recording, provenance and the export itself (atomic, share-safe)."""
import hashlib
import json
import socket
import subprocess
import sys
import time
from importlib.util import find_spec
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import Protocol, ProtocolEvent, RunConfig, Stimulus
from digitalfly.data.research import list_runs
from digitalfly.main import create_app
from digitalfly.simulation import experiment as experiment_module
from digitalfly.simulation.engines import ROOT
from digitalfly.simulation.experiment import Experiment, RunLimit, shareable


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.ROOT", tmp_path)
    monkeypatch.setattr("digitalfly.main.ROOT", tmp_path)
    monkeypatch.setattr("digitalfly.data.research.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client
    assert not app.state.worker.thread.is_alive()


def wait_for(client, condition, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = client.get("/api/status").json()
        if condition(state):
            return state
        time.sleep(.02)
    raise AssertionError(state)


def exported(tmp_path, response):
    assert response.status_code == 200, response.text
    return json.loads((Path(response.json()["path"]) / "metadata.json").read_text())


def test_recording_limit_pauses_a_valid_run_and_export_still_works(client, tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.RECORD_LIMIT", 50)
    monkeypatch.setattr("digitalfly.simulation.worker.RECORD_LIMIT", 50)
    client.post("/api/speed", json={"speed": 2})
    assert client.post("/api/run", json={}).status_code == 200
    state = wait_for(client, lambda s: s["status"] != "running")
    assert state["status"] == "paused" and state["error"] is None
    assert state["recording_samples"] == 50 and state["sample"]["step"] == 49
    assert state["events"][-1]["kind"] == "limit" and "Recording limit" in state["events"][-1]["message"]
    step = client.post("/api/step", json={})
    assert step.status_code == 409 and "Recording limit" in step.json()["detail"]
    assert client.post("/api/run", json={}).status_code == 409
    state = client.get("/api/status").json()
    assert state["status"] == "paused" and state["error"] is None and state["events"][-1]["kind"] == "limit"
    metadata = exported(tmp_path, client.post("/api/export", json={}))
    assert metadata["status"] == "paused" and metadata["error"] is None and metadata["recorded_samples"] == 50


def test_running_into_the_limit_pauses_rather_than_fails():
    exp = Experiment(RunConfig(engine="toy"), render=False)
    try:
        exp.records.extend([exp.records[0]] * (experiment_module.RECORD_LIMIT - 1))
        exp.status = "running"
        exp.start_clock()
        with pytest.raises(RunLimit) as raised:
            exp.advance()
        exp.fail(raised.value)  # what the worker's run loop does with any exception
        assert exp.status == "paused" and exp.error is None
    finally:
        exp.close()


def test_step_after_the_protocol_ends_is_refused_and_the_run_stays_valid(client, tmp_path):
    config = RunConfig(engine="toy", speed=2, protocol=Protocol(duration_steps=5))
    client.post("/api/reset", json=config.model_dump())
    client.post("/api/run", json={})
    state = wait_for(client, lambda s: s["metrics"].get("protocol_complete"))
    events = len(state["events"])
    step = client.post("/api/step", json={})
    assert step.status_code == 409 and "Protocol finished" in step.json()["detail"]
    state = client.get("/api/status").json()
    assert state["status"] == "paused" and state["error"] is None and state["sample"]["step"] == 5
    assert len(state["events"]) == events  # no "Advanced one control interval" for a step that never ran
    assert exported(tmp_path, client.post("/api/export", json={}))["error"] is None


def test_full_input_schedule_refuses_changes_but_never_export(client, tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.EVENT_LIMIT", 3)
    for x in [1, 2, 3]:
        assert client.post("/api/stimulus", json={"x": x}).status_code == 200
        client.post("/api/step", json={})
    refused = client.post("/api/stimulus", json={"x": 9})
    assert refused.status_code == 409 and "Input schedule" in refused.json()["detail"]
    state = client.get("/api/status").json()
    assert state["status"] == "paused" and state["error"] is None and state["config"]["stimulus"]["x"] == 3
    assert [e["kind"] for e in state["events"]].count("limit") == 1
    # Bookkeeping never counts: speed, run, pause, step and export all still work.
    for speed in [.5, 1, 2]:
        assert client.post("/api/speed", json={"speed": speed}).status_code == 200
        assert client.post("/api/step", json={}).status_code == 200
    assert client.post("/api/run", json={}).status_code == 200
    assert client.post("/api/pause", json={}).status_code == 200
    first = exported(tmp_path, client.post("/api/export", json={}))
    second = exported(tmp_path, client.post("/api/export", json={}))
    assert [e["payload"]["x"] for e in first["events"] if e["kind"] == "stimulus"] == [1, 2, 3]
    assert second["events"][-1]["kind"] == "export"


def test_repeated_changes_within_one_step_merge_and_replay_identically(tmp_path):
    burst, single = Experiment(RunConfig(engine="toy"), False), Experiment(RunConfig(engine="toy"), False)
    try:
        for x in [-20, 5, 14]:  # a slider drag while paused
            burst.set_stimulus(Stimulus(x=x, y=-6))
        single.set_stimulus(Stimulus(x=14, y=-6))
        stimuli = [e for e in burst.events if e.kind == "stimulus"]
        assert len(stimuli) == 1 and stimuli[0].payload["x"] == 14 and burst.schedule_events == 1
        burst.event("speed", "Requested speed 1×", {"speed": 1})
        burst.event("speed", "Requested speed 2×", {"speed": 2})
        assert burst.events[-1].payload == {"speed": 2} and burst.events[-2].kind == "stimulus"
        for exp in [burst, single]:
            for _ in range(15):
                exp.advance()
        burst.set_stimulus(Stimulus(x=3, y=3))
        assert len([e for e in burst.events if e.kind == "stimulus"]) == 2  # a new step is a new event
        np.testing.assert_array_equal([single.sample.pose.x, single.sample.pose.y, *single.sample.rates],
                                      [burst.records[15].pose.x, burst.records[15].pose.y, *burst.records[15].rates])
    finally:
        burst.close()
        single.close()


def test_protocol_and_manual_changes_at_one_step_stay_separate():
    protocol = Protocol(duration_steps=20, events=[ProtocolEvent(step=5, stimulus=Stimulus(x=12, y=-8))])
    exp = Experiment(RunConfig(engine="toy", protocol=protocol), False)
    try:
        for _ in range(5):
            exp.advance()
        exp.set_stimulus(Stimulus(x=1, y=1))  # while paused at step 5
        exp.advance()  # applies the protocol's step-5 event
        stimuli = [(e.step, e.payload["source"]) for e in exp.events if e.kind == "stimulus"]
        assert stimuli == [(5, "manual"), (5, "protocol")] and exp.schedule_events == 1
    finally:
        exp.close()


def test_replay_accepts_an_export_with_merged_events(tmp_path):
    exp = Experiment(RunConfig(engine="toy", seed=7), False)
    try:
        for x in [-10, 4]:
            exp.set_stimulus(Stimulus(x=x, y=9))
        for _ in range(20):
            exp.advance()
        exp.set_stimulus(Stimulus(x=-5, y=-5))
        for _ in range(20):
            exp.advance()
        result = exp.export(tmp_path, share_safe=True)
    finally:
        exp.close()
    assert json.loads((Path(result["path"]) / "metadata.json").read_text())["schema_version"] == 6
    replay = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), result["path"]],
                            capture_output=True, text=True, timeout=120)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["passed"]


def test_lean_recording_has_no_sample_limit_and_the_same_metrics(monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.RECORD_LIMIT", 40)
    full = Experiment(RunConfig(engine="toy", seed=3), False)
    lean = Experiment(RunConfig(engine="toy", seed=3), False, record=False)
    try:
        for _ in range(39):
            full.advance()
            lean.advance()
        assert full.metrics == lean.metrics and full.sample == lean.sample
        assert len(full.records) == 40 and lean.records == [] and full.events[-1].kind == "limit"
        with pytest.raises(RunLimit, match="Recording limit"):
            full.advance()
        for _ in range(100):
            lean.advance()
        assert lean.status == "paused" and lean.step_index == 139 and lean.metrics["duration_s"] == 1.39
        assert len(lean.history) > 0 and lean.metrics["path_length_mm"] > full.metrics["path_length_mm"]
        lean.reset(RunConfig(engine="toy", seed=4))
        assert lean.records == [] and not lean.recording
        with pytest.raises(ValueError, match="record=False"):
            lean.export()
    finally:
        full.close()
        lean.close()


def test_export_records_dependencies_and_lock_hashes(tmp_path):
    exp = Experiment(RunConfig(engine="toy"), False)
    try:
        metadata = json.loads((Path(exp.export(tmp_path)["path"]) / "metadata.json").read_text())
    finally:
        exp.close()
    assert metadata["schema_version"] == 6 and metadata["share_safe"] is False and metadata["platform"]
    dependencies = metadata["dependencies"]
    assert {"flygym", "mujoco", "numpy", "fastapi", "pydantic", "numba", "scipy", "llvmlite", "pillow"} <= set(dependencies)
    for name in ["torch", "torchvision", "flyvis"]:
        assert (name in dependencies) == (find_spec(name) is not None)
    locks = sorted((ROOT / "backend").glob("requirements*.lock"))
    assert {"requirements.lock", "requirements-data.lock", "requirements-vision.lock"} <= {p.name for p in locks}
    assert metadata["lockfiles"] == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in locks}


def test_flyvis_runs_record_the_network_checkpoint_and_bridge(toy_brain, tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.vision.flyvis_eyes.FLYVIS_ROOT", tmp_path / "flyvis")
    checkpoint = tmp_path / "flyvis/results/flow/0000/000/best_chkpt"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"weights")
    bridge = toy_brain.with_name("toy-brain.flyvis.json")
    bridge.write_text('{"format": "digitalfly-flyvis-bridge"}')

    class FakeFlyVis:
        name = "flow/0000/000"

        def describe(self):
            return {"model": "FlyVis (Lappalainen et al. 2024)", "flyvis_version": "1.2.0", "network": self.name}

    exp = Experiment(RunConfig(engine="toy", neural_model="connectome",
                               connectome_parameters={"circuit": "toy-brain"}), False)
    try:
        assert "flyvis" not in exp.vision_provenance()
        exp.body.flyvis = FakeFlyVis()
        vision = exp.metadata()["vision"]
    finally:
        exp.close()
    assert vision["flyvis"]["flyvis_version"] == "1.2.0" and vision["flyvis"]["network"] == "flow/0000/000"
    assert vision["flyvis"]["checkpoint"] == "flow/0000/000/best_chkpt"
    assert vision["flyvis"]["checkpoint_sha256"] == hashlib.sha256(b"weights").hexdigest()
    assert vision["bridge"] == {"file": "toy-brain.flyvis.json", "sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
                                "circuit_sha256": hashlib.sha256(toy_brain.read_bytes()).hexdigest()}


def test_export_is_atomic(tmp_path, monkeypatch):
    exp = Experiment(RunConfig(engine="toy"), False)
    try:
        for _ in range(10):
            exp.advance()

        class Broken:
            def __init__(self, *args, **kwargs):
                raise OSError("No space left on device")

        with monkeypatch.context() as patch:
            patch.setattr(experiment_module.zipfile, "ZipFile", Broken)
            with pytest.raises(OSError, match="No space"):
                exp.export(tmp_path)
        assert list(tmp_path.iterdir()) == [] and list_runs(tmp_path) == []
        renames = []

        def fail_on_folder(source, target):
            renames.append(target)
            if Path(source).is_dir():
                raise OSError("interrupted")
            return experiment_module.os.rename(source, target)

        with monkeypatch.context() as patch:
            patch.setattr(experiment_module.os, "replace", fail_on_folder)
            with pytest.raises(OSError, match="interrupted"):
                exp.export(tmp_path)
        assert len(renames) == 2 and list(tmp_path.iterdir()) == []
        # A crash that kills the process leaves the hidden folder behind; it is never listed.
        leftover = tmp_path / f".tmp-{exp.run_id}-abcdef"
        leftover.mkdir()
        (leftover / "metadata.json").write_text(json.dumps(exp.metadata()))
        assert list_runs(tmp_path) == []
        result = exp.export(tmp_path)
        assert [run["key"] for run in list_runs(tmp_path)] == [Path(result["path"]).name]
        assert (tmp_path / f"{Path(result['path']).name}.zip").is_file()
    finally:
        exp.close()


def test_share_safe_export_omits_platform_paths_and_host(tmp_path):
    exp = Experiment(RunConfig(engine="toy"), False)
    host = socket.gethostname()
    try:
        exp.advance()
        exp.fail(FileNotFoundError(f"[Errno 2] No such file or directory: '{ROOT}/data/circuits/local/x.json' "
                                   f"on {host}; see /home/someone/private/notes.txt or C:\\Users\\me\\run.json"))
        normal = json.loads((Path(exp.export(tmp_path)["path"]) / "metadata.json").read_text())
        path = Path(exp.export(tmp_path, share_safe=True)["path"])
    finally:
        exp.close()
    shared = json.loads((path / "metadata.json").read_text())
    text = (path / "metadata.json").read_text()
    assert "platform" in normal and "platform" not in shared and shared["share_safe"] is True
    assert str(ROOT) not in text and "/home/someone" not in text and "C:\\\\Users" not in text
    assert shared["error"].startswith("FileNotFoundError: [Errno 2] No such file or directory: 'data/circuits/local/x.json'")
    assert "<local>/" not in shared["error"] and shared["error"].count("<local>") == 2 + (len(host) > 2)
    assert shared["events"][-1]["message"] == shared["error"]
    # Science text is untouched.
    for key in ["provenance", "neural", "units", "dependencies", "lockfiles", "initial_config", "metrics", "python"]:
        assert shared[key] == normal[key], key


@pytest.mark.parametrize("text", ["mm/s", "flow/0000/000", "https://doi.org/10.7554/eLife.102230", "1/50 s",
                                  "dv/dt = (v_rest − v + g)/tau_m", "ws://127.0.0.1:*", "right − left / 2",
                                  "FIB-25/FIB-19 medulla", "data/circuits/fafb783-dna02.json"])
def test_share_safe_keeps_ordinary_text(text):
    assert shareable({"error": text, "x": [text]}) == {"error": text, "x": [text]}


def test_share_safe_export_through_the_api(client, tmp_path):
    assert client.post("/api/export", json={"share_safe": "yes"}).status_code == 422
    assert client.post("/api/export", json={"share": True}).status_code == 422
    metadata = exported(tmp_path, client.post("/api/export", json={"share_safe": True}))
    assert metadata["share_safe"] and "platform" not in metadata
    assert "platform" in exported(tmp_path, client.post("/api/export", json={}))
