"""The simulation worker survives failures, checks commands against what is running and publishes only changes."""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
import pytest
from fastapi.testclient import TestClient
import conftest
from conftest import write_circuit
from digitalfly import __version__
from digitalfly.api.models import BatchRequest, ConnectomeParameters, Protocol, RunConfig, reads_files_later
from digitalfly.main import create_app
from digitalfly.neural import connectome
from digitalfly.neural.connectome import bridge_path, load_circuit
from digitalfly.simulation.engines import CONTROL_DT
from digitalfly.simulation.experiment import Experiment, RECORD_LIMIT
from digitalfly.simulation.worker import SimulationWorker

ROOT = Path(__file__).resolve().parents[2]
TOY = RunConfig(engine="toy")
HALF_BLIND = {3: ("LCa", "central")}  # the right LCa is not a visual projection neuron: no right visual input
NO_SOLO = {9: ("Inh", "central")}  # the left-only Solo neuron joins Inh: the circuit has no Solo type
FLYVIS_TYPES = json.loads((ROOT / "data/circuits/fafb783-dna02.flyvis.json").read_text())["flyvis"]["types"]


def write_toy(monkeypatch, folder, name, relabel):
    """The toy circuit with some neurons given another cell type and super class."""
    rows = [list(n) for n in conftest.NEURONS]
    for i, (cell_type, super_class) in relabel.items():
        rows[i][1:3] = cell_type, super_class
    with monkeypatch.context() as m:
        m.setattr(conftest, "NEURONS", [tuple(r) for r in rows])
        return write_circuit(folder, name)


def connectome_body(circuit, **parameters):
    # A plain body: some of these circuits are invalid, so no RunConfig can be built for them here.
    return {**TOY.model_dump(), "neural_model": "connectome", "connectome_parameters": {"circuit": circuit, **parameters}}


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.neural.connectome.LOCAL_DIR", tmp_path / "local")
    monkeypatch.setattr("digitalfly.simulation.experiment.ROOT", tmp_path)
    monkeypatch.setattr("digitalfly.main.ROOT", tmp_path)
    write_circuit(tmp_path / "local")
    return tmp_path / "local"


@contextmanager
def serve(config=TOY):
    app = create_app(config, render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client
    assert not app.state.worker.thread.is_alive()


def alive(client):
    return client.get("/api/health").json()["worker_alive"]


def finished_batch(client, timeout=10):
    deadline = time.monotonic() + timeout
    while (state := client.get("/api/status").json())["batch"]["status"] in {"running", "paused"}:
        assert time.monotonic() < deadline, state["batch"]
        time.sleep(.02)
    return state


def test_a_circuit_without_visual_input_on_one_side_is_refused_and_the_worker_lives(local, monkeypatch):
    write_toy(monkeypatch, local, "half-blind", HALF_BLIND)
    with pytest.raises(ValueError, match="right side"):
        ConnectomeParameters(circuit="half-blind").check_against_circuit()
    with serve() as client:
        before = client.get("/api/status").json()
        response = client.post("/api/reset", json=connectome_body("half-blind"))
        assert response.status_code == 422 and "no visual projection neurons on the right side" in response.text
        state = client.get("/api/status").json()
        assert alive(client) and state["status"] == "paused" and state["run_id"] == before["run_id"]
        # Past validation, a circuit that cannot be built still leaves the current run as it was.
        monkeypatch.setattr(ConnectomeParameters, "check_against_circuit", lambda self, *args, **kwargs: None)
        response = client.post("/api/reset", json=connectome_body("half-blind"))
        assert response.status_code == 409 and "side" in response.json()["detail"]
        state = client.get("/api/status").json()
        assert alive(client) and state["status"] == "paused" and state["run_id"] == before["run_id"]
        assert state["config"]["neural_model"] == "engineered" and state["provenance"]["neural_model"].startswith("Six")
        assert client.post("/api/step", json={}).json()["sample"]["step"] == 1
        assert client.post("/api/reset", json=connectome_body("toy-brain")).json()["connectome"]["circuit"] == "toy-brain"


def test_an_experiment_that_cannot_start_describes_the_circuit_it_has(local, monkeypatch):
    write_toy(monkeypatch, local, "half-blind", HALF_BLIND)
    monkeypatch.setattr(ConnectomeParameters, "check_against_circuit", lambda self, *args, **kwargs: None)
    config = RunConfig(engine="toy", neural_model="connectome", connectome_parameters={"circuit": "half-blind"})
    exp = Experiment(config, render=False)
    try:
        assert exp.status == "error" and "side" in exp.error and exp.circuit.kind == "engineered"
        assert exp.provenance["neural_model"].startswith("Six") and exp.connectome_snapshot() is None
        with pytest.raises(ValueError):
            exp.reset(config)
        exp.reset(TOY)
        assert exp.status == "paused" and exp.config.neural_model == exp.circuit.kind == "engineered"
    finally:
        exp.close()


def test_a_body_that_cannot_be_built_leaves_the_run_as_it_was(monkeypatch):
    exp = Experiment(TOY, render=False)
    try:
        exp.advance()

        class Unavailable:
            def __init__(self, *args):
                raise RuntimeError("no OpenGL context")
        monkeypatch.setattr("digitalfly.simulation.experiment.FlyGymBody", Unavailable)
        with pytest.raises(RuntimeError, match="OpenGL"):
            exp.reset(RunConfig(engine="flygym", neural_model="connectome"))
        assert exp.config.engine == "toy" and exp.config.neural_model == exp.circuit.kind == "engineered"
        assert exp.status == "paused" and exp.step_index == 1 and exp.body.name == "toy"
        exp.advance()
    finally:
        exp.close()


def test_commands_check_the_loaded_circuit_after_it_is_rebuilt_on_disk(local, monkeypatch, tmp_path):
    from digitalfly.data import builds
    monkeypatch.setattr(builds, "PREPARED", tmp_path / "prepared.npz")
    builds.PREPARED.write_bytes(b"")
    path = write_toy(monkeypatch, local, "my-circuit", NO_SOLO)
    loaded = load_circuit("my-circuit").sha256
    with serve(RunConfig.model_validate(connectome_body("my-circuit"))) as client:
        state = client.get("/api/status").json()
        assert state["connectome"]["circuit_sha256"] == loaded
        assert client.get("/api/connectome/circuit").json()["sha256"] == loaded
        listed = {c["name"]: c for c in client.get("/api/connectome/circuits").json()["circuits"]}
        assert listed["my-circuit"]["sha256"] == loaded
        assert client.post("/api/interventions", json={"silence_types": ["Solo"]}).status_code == 422
        build = client.post("/api/connectome/build", json={"name": "my-circuit", "seeds": ["DNx"]})
        assert build.status_code == 409 and "uses the my-circuit circuit" in build.json()["detail"]
        # The command-line builder can still rewrite the file in place: now with a Solo type.
        path.unlink()
        write_circuit(local, "my-circuit")
        os.utime(path, ns=(time.time_ns() + 10**9,) * 2)
        response = client.post("/api/interventions", json={"silence_types": ["Solo"]})
        assert response.status_code == 422 and "Solo" in response.json()["detail"]
        assert client.get("/api/connectome/circuit").status_code == 409
        edit = client.post("/api/connectome/parameters", json={**state["config"]["connectome_parameters"], "global_gain": .002})
        assert edit.status_code == 409 and "changed since this run loaded it" in edit.json()["detail"]
        state = client.post("/api/step", json={}).json()
        assert alive(client) and state["status"] == "paused" and state["connectome"]["circuit_sha256"] == loaded
        state = client.post("/api/reset", json=state["config"]).json()
        assert state["connectome"]["circuit_sha256"] == load_circuit("my-circuit").sha256 != loaded
        state = client.post("/api/interventions", json={"silence_types": ["Solo"]}).json()
        assert state["connectome"]["silenced_neurons"] == 1 and client.get("/api/connectome/circuit").status_code == 200


def test_publishing_does_not_recheck_the_circuit_file(local, monkeypatch):
    with serve(RunConfig.model_validate(connectome_body("toy-brain"))) as client:
        path = write_toy(monkeypatch, local, "toy-brain", HALF_BLIND)  # rewritten in place, now invalid
        os.utime(path, ns=(time.time_ns() + 10**9,) * 2)
        state = client.post("/api/step", json={}).json()
        assert state["status"] == "paused" and state["sample"]["step"] == 1 and state["error"] is None


def test_a_state_that_cannot_be_published_errors_the_run_not_the_worker(monkeypatch):
    real = Experiment.connectome_snapshot
    with serve() as client:
        def broken(self):
            raise KeyError("readout")
        monkeypatch.setattr(Experiment, "connectome_snapshot", broken)
        state = client.post("/api/step", json={}).json()
        assert state["status"] == "error" and "readout" in state["error"]
        # A failing command whose state cannot be published either: still an answer, still a worker.
        assert client.post("/api/connectome/parameters", json={}).status_code == 409
        assert alive(client) and client.post("/api/run", json={}).status_code == 409
        monkeypatch.setattr(Experiment, "connectome_snapshot", real)
        state = client.post("/api/reset", json=TOY.model_dump()).json()
        assert state["status"] == "paused" and alive(client)


def test_commands_to_a_stopped_worker_fail_at_once():
    with serve() as client:
        worker = client.app.state.worker
        real, worker.thread = worker.thread, Thread(target=lambda: None)
        worker.thread.start()
        worker.thread.join()
        try:
            started = time.monotonic()
            response = client.post("/api/step", json={})
            assert response.status_code == 503 and "Restart DigitalFly" in response.json()["detail"]
            assert time.monotonic() - started < 2 and not alive(client)
        finally:
            worker.thread = real


def test_a_paused_worker_publishes_only_changes():
    worker = SimulationWorker(TOY, render=False)
    worker.start()
    try:
        assert worker.ready.wait(10)
        first = worker.get_snapshot()["revision"]
        time.sleep(1.3)  # longer than the heartbeat
        assert worker.get_snapshot()["revision"] == first
        assert worker.submit("pause").result(5)["revision"] == first  # already paused: nothing changed
        stepped = worker.submit("step").result(5)
        assert stepped["revision"] == first + 1 and stepped["sample"]["step"] == 1
    finally:
        worker.close()


def test_telemetry_sends_each_revision_once_in_the_same_encoding():
    with serve() as client:
        with client.websocket_connect("ws://127.0.0.1:8000/api/ws", headers={"Origin": "http://127.0.0.1:8000"}) as ws:
            text = ws.receive_text()
            first = json.loads(text)
            assert text == json.dumps(first, separators=(",", ":"), ensure_ascii=False) and "·" in text
            time.sleep(.35)  # paused: nothing new to send, so nothing queued
            client.post("/api/step", json={})
            following = json.loads(ws.receive_text())
            assert following["revision"] > first["revision"] and following["sample"]["step"] == 1


def test_request_validation_reads_no_circuit_file_on_the_event_loop(local, monkeypatch):
    real, on_loop = connectome.load_circuit, []

    def recording(*args, **kwargs):
        on_loop.append(reads_files_later())
        return real(*args, **kwargs)
    monkeypatch.setattr(connectome, "load_circuit", recording)
    with serve() as client:
        body = connectome_body("toy-brain")
        assert client.post("/api/reset", json=body).status_code == 200
        batch = {"config": {**body, "protocol": {"duration_steps": 5}}, "seeds": [1],
                 "conditions": ["control", "cell_type_off"], "cell_type": "Inh", "max_speed": True}
        assert client.post("/api/batch/start", json=batch).status_code == 200
        assert finished_batch(client)["batch"]["status"] == "completed"
        assert on_loop and not any(on_loop)
        # The worker's own validation still answers 422.
        unknown = client.post("/api/reset", json=connectome_body("toy-brain", input_types=["Nope"]))
        assert unknown.status_code == 422 and "Nope" in unknown.text
        assert client.post("/api/batch/start", json={**batch, "cell_type": "Nope"}).status_code == 422


def test_comparisons_restore_the_workbench_and_can_run_unpaced(local):
    with serve(RunConfig.model_validate(connectome_body("toy-brain"))) as client:
        workbench = client.post("/api/interventions", json={"silence_types": ["Inh"]}).json()
        batch = {"config": {**workbench["config"], "protocol": {"duration_steps": 50}}, "seeds": [1, 2],
                 "conditions": ["control", "engineered_model"], "max_speed": True}
        started = time.monotonic()
        assert client.post("/api/batch/start", json=batch).status_code == 200
        state = finished_batch(client)
        # 200 control intervals paced at the default 0.25× would take 8 s.
        assert state["batch"]["status"] == "completed" and time.monotonic() - started < 6
        assert len(state["batch"]["results"]) == 4 and state["batch"]["results"][-1]["condition"] == "engineered_model"
        # A fresh run of the workbench configuration, starting with the interventions it had.
        assert state["config"] == {**workbench["config"], "initial_interventions": workbench["interventions"]}
        assert state["interventions"]["silence_types"] == ["Inh"]
        assert state["sample"]["step"] == 0 and state["events"][-1]["kind"] == "batch_complete"
        # Paced comparisons take speed changes; cancelling saves the unfinished trial and restores the workbench.
        paced = {**batch, "config": {**batch["config"], "protocol": {"duration_steps": 3000}},
                 "seeds": [3], "conditions": ["engineered_model"], "max_speed": False}
        assert client.post("/api/batch/start", json=paced).status_code == 200
        assert client.post("/api/speed", json={"speed": 2}).status_code == 200
        assert client.post("/api/stimulus", json={"x": 0}).status_code == 409
        time.sleep(.1)
        state = client.post("/api/batch/cancel", json={}).json()
        assert state["batch"]["status"] == "cancelled" and state["batch"]["partial"]["partial"]
        assert state["config"]["neural_model"] == "connectome" and state["interventions"]["silence_types"] == ["Inh"]
        assert state["status"] == "paused" and state["sample"]["step"] == 0
        saved = json.loads((Path(state["batch"]["partial"]["path"]) / "metadata.json").read_text())
        assert saved["trial"]["partial"] and saved["final_config"]["speed"] == 2
        assert saved["initial_config"]["neural_model"] == "engineered" and not saved["metrics"]["protocol_complete"]


def test_every_trial_config_is_validated_and_flyvis_excludes_the_engineered_model(monkeypatch):
    monkeypatch.setattr("digitalfly.vision.flyvis_eyes.available", lambda *args: (True, ""))
    config = RunConfig(neural_model="connectome", sensor_model="flyvis", protocol=Protocol(duration_steps=5))
    with pytest.raises(ValueError, match="cannot be compared"):
        BatchRequest(config=config, conditions=["control", "engineered_model"])
    unchecked = BatchRequest.model_construct(config=config, conditions=["engineered_model"], seeds=[1], cell_type=None)
    with pytest.raises(ValueError, match="Select the connectome model"):
        SimulationWorker._trial_config(unchecked, "engineered_model", 1)
    trial = SimulationWorker._trial_config(unchecked, "dna02_left_off", 7)
    assert trial.seed == 7 and trial.initial_interventions.silence_dna02 == "left" and trial.sensor_model == "flyvis"


def write_bridge(data, neurons):
    path = bridge_path(data)
    path.write_text(json.dumps({
        "format": "digitalfly-flyvis-bridge", "version": 1, "circuit": data.key, "circuit_sha256": data.sha256,
        "flyvis": {"release": "1.2.0", "types": FLYVIS_TYPES}, "neurons": neurons,
        "entries": {"neuron": list(range(len(neurons))), "type": [5] * len(neurons), "eye": [0] * len(neurons),
                    "weight": [1.0] * len(neurons)}}))
    os.utime(path, ns=(time.time_ns() + len(neurons) * 10**9,) * 2)  # a fresh cache entry per bridge


def test_flyvis_eyes_need_bridge_input_on_both_sides(local, monkeypatch):
    data = load_circuit("toy-brain")
    write_bridge(data, [2, 3])  # both LCa
    ConnectomeParameters(circuit="toy-brain").check_against_circuit(flyvis=True)
    with pytest.raises(ValueError, match="no left input"):
        ConnectomeParameters(circuit="toy-brain", input_types=["Inh"]).check_against_circuit(flyvis=True)
    monkeypatch.setattr("digitalfly.vision.flyvis_eyes.available", lambda *args: (True, ""))
    with pytest.raises(ValueError, match="FlyVis eyes would give"):
        RunConfig(neural_model="connectome", sensor_model="flyvis",
                  connectome_parameters={"circuit": "toy-brain", "input_types": ["Inh"]})
    write_bridge(data, [2])  # the left LCa only
    with pytest.raises(ValueError, match="no right input"):
        ConnectomeParameters(circuit="toy-brain").check_against_circuit(flyvis=True)


def test_a_circuit_being_built_cannot_be_loaded(local, monkeypatch, tmp_path):
    from digitalfly.data import builds
    monkeypatch.setattr(builds, "PREPARED", tmp_path / "prepared.npz")
    builds.PREPARED.write_bytes(b"")
    monkeypatch.setattr(builds.BuildManager, "command",
                        staticmethod(lambda request: [sys.executable, "-c", "import time; time.sleep(5)"]))
    with serve() as client:
        assert client.post("/api/connectome/build", json={"name": "toy-brain", "seeds": ["DNx"]}).json()["status"] == "running"
        response = client.post("/api/reset", json=connectome_body("toy-brain"))
        assert response.status_code == 409 and "being built" in response.json()["detail"]
        assert client.post("/api/reset", json=TOY.model_dump()).status_code == 200


def test_health_reports_the_version_and_capabilities_follow_the_constants():
    with serve() as client:
        assert client.get("/api/health").json()["version"] == __version__
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["recording_limit"] == RECORD_LIMIT and capabilities["control_interval_s"] == CONTROL_DT
        assert capabilities["input_queue_capacity"] == client.app.state.worker.commands.maxsize == 64
        assert capabilities["engines"] == ["flygym", "toy"] and capabilities["default_engine"] == "flygym"
        assert capabilities["connectome_dynamics"] == ["rate", "spiking"] and capabilities["neural_units"] == 6
        assert capabilities["telemetry_target_hz"] == 10
