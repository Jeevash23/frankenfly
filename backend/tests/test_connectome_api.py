"""The connectome model through the API: validation, interventions, exports, replay and comparisons."""
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import Protocol, RunConfig
from digitalfly.main import create_app
from digitalfly.neural.connectome import CIRCUIT_PATH

ROOT = Path(__file__).resolve().parents[2]
CONNECTOME = RunConfig(engine="toy", neural_model="connectome")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr('digitalfly.simulation.experiment.ROOT', tmp_path)
    monkeypatch.setattr('digitalfly.main.ROOT', tmp_path)
    app = create_app(CONNECTOME, render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_state_capabilities_and_circuit_describe_the_connectome_model(client):
    state = client.post("/api/step", json={}).json()
    assert state["config"]["neural_model"] == "connectome"
    assert len(state["sample"]["rates"]) == 5 and state["connectome"]["type_rates"]
    assert state["connectome"]["unit_names"][:2] == ["DNa02 L", "DNa02 R"] and state["connectome"]["readout_types"] == ["DNa02"]
    assert state["connectome"]["circuit"] == "fafb783-dna02" and state["connectome"]["dynamics"] == "rate"
    assert "data-derived" in state["provenance"]["neural_model"]
    assert "CC BY-NC 4.0" in state["provenance"]["connectivity_source"]
    capabilities = client.get("/api/capabilities").json()
    assert capabilities["active_neural_model"] == "connectome" and capabilities["active_dynamics"] == "rate"
    assert capabilities["biological_connectome"] and not capabilities["whole_brain_connectome"]
    assert capabilities["connectome_circuit"]["sha256"] == hashlib.sha256(CIRCUIT_PATH.read_bytes()).hexdigest()
    circuit = client.get("/api/connectome/circuit").json()
    names = {t["index"]: t["name"] for t in circuit["types"]}
    readout = circuit["readouts"][0]
    assert readout["cell_type"] == "DNa02" and names[readout["type_index"]] == "DNa02"
    assert len(names) == len(state["connectome"]["type_rates"]) == circuit["types_total"] == circuit["types_shown"]
    assert len(circuit["edges"]["pre"]) == len(circuit["edges"]["synapses"]) > 0
    assert set(circuit["edges"]["sign"]) <= {-1, 1} and readout["inputs"]["left"]["synapses"]


def test_new_settings_are_validated(client):
    def status(path, body):
        return client.post(path, json=body).status_code
    assert status("/api/reset", {**CONNECTOME.model_dump(), "neural_model": "whole_brain"}) == 422
    assert status("/api/reset", {**CONNECTOME.model_dump(), "connectome_parameters": {"global_gain": -1}}) == 422
    assert status("/api/connectome/parameters", {"synapse_threshold": 0}) == 422
    assert status("/api/connectome/parameters", {"tau_ms": "fast"}) == 422
    assert status("/api/interventions", {"silence_types": ["Not-a-type"]}) == 422
    assert status("/api/interventions", {"silence_dna02": "middle"}) == 422
    # Each model only accepts its own interventions and parameters.
    assert status("/api/interventions", {"silence": "descending"}) == 409
    assert status("/api/parameters", {"tonic_drive": .4}) == 409
    engineered = {**CONNECTOME.model_dump(), "neural_model": "engineered"}
    assert status("/api/reset", engineered) == 200
    assert status("/api/interventions", {"silence_dna02": "left"}) == 409
    assert status("/api/connectome/parameters", {"global_gain": .002}) == 409
    assert status("/api/reset", {**engineered, "initial_interventions": {"silence_dna02": "both"}}) == 422


def test_silencing_and_parameters_change_the_computation(client):
    state = client.post("/api/interventions", json={"silence_dna02": "left", "silence_types": ["DNa03"]}).json()
    assert state["sample"]["rates"][0] == 0 and state["connectome"]["silenced_neurons"] >= 3
    for _ in range(20):
        state = client.post("/api/step", json={}).json()
    assert state["sample"]["rates"][0] == 0
    assert "DNa02 left" in state["events"][-21]["message"]
    state = client.post("/api/connectome/parameters", json={"global_gain": .002, "synapse_threshold": 10}).json()
    assert state["config"]["connectome_parameters"]["synapse_threshold"] == 10
    assert state["events"][-1]["kind"] == "connectome_parameters"
    assert client.get("/api/connectome/circuit").json()["parameters"]["synapse_threshold"] == 10


def test_export_records_the_circuit_and_replays_exactly(client, tmp_path):
    client.post("/api/stimulus", json={"x": 10, "y": -6, "intensity": 1})
    for _ in range(15):
        client.post("/api/step", json={})
    client.post("/api/interventions", json={"silence_dna02": "right"})
    client.post("/api/connectome/parameters", json={"output_gain": 2})
    for _ in range(15):
        client.post("/api/step", json={})
    result = client.post("/api/export", json={}).json()
    run = Path(result["path"])
    metadata = json.loads((run / "metadata.json").read_text())
    neural = metadata["neural"]
    assert neural["kind"] == "connectome" and neural["parameters"]["output_gain"] == 2
    assert neural["circuit_sha256"] == hashlib.sha256(CIRCUIT_PATH.read_bytes()).hexdigest()
    assert neural["labels"]["signs"] == "assumed" and neural["license"].startswith("CC BY-NC 4.0")
    header = (run / "telemetry.csv").read_text().splitlines()[0].split(",")
    assert [h for h in header if h.startswith("rate_")] == [
        "rate_dna02_l", "rate_dna02_r", "rate_visual_input_l", "rate_visual_input_r", "rate_circuit_mean"]
    replay = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)],
                            capture_output=True, text=True, timeout=120)
    assert replay.returncode == 0, replay.stderr
    report = json.loads(replay.stdout)
    assert report["passed"] and report["maximum_absolute_error"] == 0 and report["samples"] == 31


def test_comparisons_accept_model_and_dna02_conditions(client, tmp_path):
    config = RunConfig(engine="toy", neural_model="connectome", speed=2, protocol=Protocol(duration_steps=10))
    body = {"config": config.model_dump(), "seeds": [42],
            "conditions": ["dna02_left_off", "dna02_both_off", "cell_type_off", "engineered_model"], "cell_type": "DNa03"}
    assert client.post("/api/batch/start", json={**body, "cell_type": None}).status_code == 422
    assert client.post("/api/batch/start", json={**body, "cell_type": "Not-a-type"}).status_code == 422
    engineered = {**body, "config": {**body["config"], "neural_model": "engineered"}}
    assert client.post("/api/batch/start", json=engineered).status_code == 422
    assert client.post("/api/batch/start", json=body).status_code == 200
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get("/api/status").json()
        if state["batch"]["status"] == "completed":
            break
        time.sleep(.05)
    assert state["batch"]["status"] == "completed", state["batch"]
    trials = {m["trial"]["condition"]: m for m in
              (json.loads(p.read_text()) for p in tmp_path.glob("runs/*/metadata.json"))}
    assert trials["dna02_left_off"]["initial_config"]["initial_interventions"]["silence_dna02"] == "left"
    assert trials["dna02_both_off"]["initial_config"]["initial_interventions"]["silence_dna02"] == "both"
    assert trials["cell_type_off"]["initial_config"]["initial_interventions"]["silence_types"] == ["DNa03"]
    assert trials["engineered_model"]["initial_config"]["neural_model"] == "engineered"
    assert trials["engineered_model"]["neural"]["kind"] == "engineered"


@pytest.mark.flygym
def test_connectome_model_drives_flygym_repeatably():
    from digitalfly.simulation.experiment import Experiment
    config = RunConfig(neural_model="connectome")
    exp = Experiment(config, render=False)
    try:
        assert exp.status == "paused", exp.error
        for _ in range(40):
            exp.advance()
        first = exp.sample.model_dump()
        assert all(map(math.isfinite, first["rates"])) and first["pose"]["x"] > .1
        exp.reset(config)
        for _ in range(40):
            exp.advance()
        assert exp.sample.model_dump() == first
    finally:
        exp.close()


def test_circuit_list_paths_and_dynamics_switching(client):
    listed = client.get("/api/connectome/circuits").json()
    assert listed["active"] == "fafb783-dna02"
    assert any(c["name"] == "fafb783-dna02" and c["committed"] and c["neurons"] == 3000 for c in listed["circuits"])
    paths = client.get("/api/connectome/paths", params={"source": "DNa03", "target": "DNa02", "max_hops": 2}).json()
    assert paths["paths"] and all(p["cell_types"][0] == "DNa03" and p["cell_types"][-1] == "DNa02" for p in paths["paths"])
    assert all(0 < p["strength"] <= 1 and p["net_sign"] in (-1, 1) for p in paths["paths"])
    assert client.get("/api/connectome/paths", params={"source": "Nope", "target": "DNa02"}).status_code == 422
    assert client.get("/api/connectome/paths", params={"source": "DNa03", "target": "DNa02", "max_hops": 9}).status_code == 422
    # Dynamics and circuit are fixed for a run; switching them takes a reset.
    assert client.post("/api/connectome/parameters", json={"dynamics": "spiking"}).status_code == 409
    assert client.post("/api/connectome/parameters", json={"readout_types": ["DNa02", "DNa03"]}).status_code == 409
    state = client.post("/api/reset", json={**CONNECTOME.model_dump(), "connectome_parameters": {"dynamics": "spiking"}}).json()
    assert state["config"]["connectome_parameters"]["dynamics"] == "spiking"
    assert client.get("/api/capabilities").json()["active_dynamics"] == "spiking"
    unknown = {**CONNECTOME.model_dump(), "connectome_parameters": {"circuit": "no-such-circuit"}}
    assert client.post("/api/reset", json=unknown).status_code == 422


def test_spiking_runs_export_and_replay_exactly(client):
    config = {**CONNECTOME.model_dump(), "seed": 9, "connectome_parameters": {"dynamics": "spiking"}}
    client.post("/api/reset", json=config)
    client.post("/api/stimulus", json={"x": 10, "y": 6, "intensity": 1})
    for _ in range(10):
        client.post("/api/step", json={})
    client.post("/api/interventions", json={"silence_dna02": "left"})
    for _ in range(10):
        client.post("/api/step", json={})
    run = Path(client.post("/api/export", json={}).json()["path"])
    neural = json.loads((run / "metadata.json").read_text())["neural"]
    assert neural["dynamics"] == "spiking" and neural["spiking_constants"]["delay_ms"] == 1.8
    replay = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)],
                            capture_output=True, text=True, timeout=180)
    assert replay.returncode == 0, replay.stderr
    report = json.loads(replay.stdout)
    assert report["passed"] and report["maximum_absolute_error"] == 0


def test_build_jobs_validate_and_report(client, tmp_path, monkeypatch):
    from digitalfly.data import builds
    monkeypatch.setattr(builds, "PREPARED", tmp_path / "missing.npz")
    monkeypatch.setattr(builds, "CATALOG", tmp_path / "missing.json")
    assert client.get("/api/connectome/catalog").status_code == 404
    assert not client.get("/api/capabilities").json()["circuit_builder_ready"]
    good = {"name": "my-circuit", "seeds": ["DNa01", "DNa02"]}
    for bad in [{**good, "name": "Bad Name"}, {**good, "seeds": []}, {**good, "hops": 0}, {**good, "cap": 5},
                {**good, "threshold": 0}, {**good, "seeds": ["bad\nseed"]}, {**good, "extra": 1}]:
        assert client.post("/api/connectome/build", json=bad).status_code == 422, bad
    assert client.post("/api/connectome/build", json=good).status_code == 409  # not prepared yet
    builds.PREPARED.write_bytes(b"")
    builds.CATALOG.write_text(json.dumps({"release": "test", "cell_types": [{"cell_type": "DNa02"}]}))
    assert client.get("/api/connectome/catalog").json()["cell_types"] == [{"cell_type": "DNa02"}]
    assert client.post("/api/connectome/build", json={**good, "name": "fafb783-dna02"}).status_code == 409
    seen, real = [], builds.BuildManager.command

    def fake(request):
        seen.append(real(request))
        script = "import json, time; print('selecting', flush=True); time.sleep(.5); print(json.dumps({'name': 'my-circuit', 'neurons': 12}))"
        return [sys.executable, "-c", script]
    monkeypatch.setattr(builds.BuildManager, "command", staticmethod(fake))
    started = client.post("/api/connectome/build", json={**good, "whole_brain": True}).json()
    assert started["status"] == "running" and started["name"] == "my-circuit"
    assert seen[0][-1] == "--whole-brain" and seen[0][seen[0].index("--name") + 1] == "my-circuit"
    assert client.post("/api/connectome/build", json=good).status_code == 409  # one build at a time
    deadline = time.monotonic() + 10
    while (status := client.get("/api/connectome/build").json())["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.05)
    assert status["status"] == "done" and status["result"] == {"name": "my-circuit", "neurons": 12}
    assert status["log"][0] == "selecting"
