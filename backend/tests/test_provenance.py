"""Export schema 6: the RO-Crate provenance manifest, the drafted methods paragraph, the readout spike times of spiking
runs, and manifests and methods for runs exported before them."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from digitalfly import provenance
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, Stimulus
from digitalfly.simulation.experiment import Experiment, SPIKE_FILE

ROOT = Path(__file__).resolve().parents[2]
OLD_RUN = ROOT / "backend/tests/fixtures/v05-spiking-edits"


def export(tmp_path, config, steps=40, edit=None):
    exp = Experiment(config, render=False)
    try:
        for i in range(steps):
            if edit and i in edit:
                edit[i](exp)
            exp.advance()
        return exp, Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()


def spiking(**settings):
    return RunConfig(engine="toy", seed=5, neural_model="connectome",
                     connectome_parameters=ConnectomeParameters(circuit="toy-brain", dynamics="spiking", **settings))


def graph(manifest):
    return {node["@id"]: node for node in manifest["@graph"]}


def test_manifest_lists_every_file_with_its_hash(tmp_path):
    _, run = export(tmp_path, RunConfig(engine="toy", seed=11))
    manifest = json.loads((run / provenance.MANIFEST_FILE).read_text())
    assert manifest["@context"][0] == "https://w3id.org/ro/crate/1.1/context"
    nodes = graph(manifest)
    assert nodes[provenance.MANIFEST_FILE]["conformsTo"]["@id"] == "https://w3id.org/ro/crate/1.1"
    parts = {p["@id"] for p in nodes["./"]["hasPart"]}
    assert parts == {p.name for p in run.iterdir()} - {provenance.MANIFEST_FILE}
    assert {"metadata.json", "telemetry.csv", "methods.md"} <= parts
    for name in parts:
        assert nodes[name]["sha256"] == hashlib.sha256((run / name).read_bytes()).hexdigest()
        assert nodes[name]["contentSize"] == str((run / name).stat().st_size)
    assert {p["@id"] for p in nodes["#run"]["result"]} == parts
    with zipfile.ZipFile(run.with_suffix(".zip")) as archive:  # the ZIP carries them too
        assert {provenance.MANIFEST_FILE, provenance.METHODS_FILE} <= set(archive.namelist())


def test_manifest_records_versions_locks_seed_and_choices(tmp_path):
    _, run = export(tmp_path, RunConfig(engine="toy", seed=11, sensor_model="geometric"))
    meta = json.loads((run / "metadata.json").read_text())
    nodes = graph(json.loads((run / provenance.MANIFEST_FILE).read_text()))
    software = nodes["#digitalfly"]
    assert software["version"] == meta["application_version"] and meta["code"]["digitalfly"] == software["version"]
    commit = provenance._git("rev-parse", "HEAD")
    assert software["digitalfly:gitCommit"] == (commit or "not recorded")
    locks = {n["name"]: n["sha256"] for k, n in nodes.items() if k.startswith("#lock-")}
    assert locks and locks == meta["lockfiles"]
    for name, digest in locks.items():
        assert digest == hashlib.sha256((ROOT / "backend" / name).read_bytes()).hexdigest()
    assert nodes["#dependency-numpy"]["version"] == meta["dependencies"]["numpy"]
    assert nodes["#setting-seed"]["value"] == 11 and nodes["#setting-engine"]["value"] == "toy"
    assert nodes["#setting-sensor_model"]["value"] == "geometric" and nodes["#setting-neural_model"]["value"] == "engineered"
    assert nodes["./"]["license"]["@id"] == "#license-not-chosen"  # no FlyWire data in an engineered run


def test_parameter_diff_from_defaults():
    config = RunConfig(engine="toy", seed=3, connectome_parameters=ConnectomeParameters(output_gain=2.5),
                       stimulus=Stimulus(x=5))
    diff = {d["parameter"]: (d["value"], d["default"]) for d in provenance.parameter_diff(config.model_dump(mode="json"))}
    assert diff == {"engine": ("toy", "flygym"), "seed": (3, 42), "connectome_parameters.output_gain": (2.5, 1.0),
                    "stimulus.x": (5.0, 12.0)}
    assert provenance.parameter_diff(RunConfig().model_dump(mode="json")) == []
    with_protocol = RunConfig.model_validate({"protocol": {"name": "Hold", "duration_steps": 50},
                                              "connectome_parameters": {"readout_weights": {"DNa02": 2}}})
    groups = {d["parameter"]: d["default"] for d in provenance.parameter_diff(with_protocol.model_dump(mode="json"))}
    assert groups == {"protocol": None, "connectome_parameters.readout_weights": None}  # each group once, whole


def test_connectome_manifest_has_sources_circuit_and_diff(tmp_path, toy_brain):
    config = spiking(output_gain=2)
    _, run = export(tmp_path, config, 30, {10: lambda e: e.set_interventions(Interventions(silence_types=["Inh"]))})
    meta = json.loads((run / "metadata.json").read_text())
    nodes = graph(json.loads((run / provenance.MANIFEST_FILE).read_text()))
    assert nodes["#circuit"]["sha256"] == meta["neural"]["circuit_sha256"] and nodes["#circuit"]["name"] == "toy-brain"
    assert nodes["#setting-connectome_parameters.dynamics"]["value"] == "spiking"
    assert nodes["#changed-connectome_parameters.output_gain"]["value"] == 2
    assert nodes["#changed-connectome_parameters.output_gain"]["digitalfly:default"] == 1
    assert {d["parameter"] for d in meta["parameter_diff"]} >= {"connectome_parameters.output_gain", "seed"}
    assert nodes["./"]["license"]["@id"] == provenance.CC_BY_NC
    changes = [n for k, n in nodes.items() if k.startswith("#change-")]
    assert [(c["propertyID"], c["digitalfly:step"]) for c in changes] == [("interventions", 10)]


def test_committed_circuit_sources_have_urls_and_hashes(tmp_path):
    config = RunConfig(engine="toy", seed=1, neural_model="connectome")
    _, run = export(tmp_path, config, 3)
    nodes = graph(json.loads((run / provenance.MANIFEST_FILE).read_text()))
    sources = [nodes[p["@id"]] for p in nodes["#connectome"]["hasPart"]]
    assert sources and all(s["@id"].startswith("https://") and len(s["sha256"]) == 64 for s in sources)
    assert nodes["#connectome"]["name"] == "FlyWire FAFB v783"
    assert "fafb_783_meta.feather" in {s["name"] for s in sources}  # the annotation release
    methods = (run / provenance.METHODS_FILE).read_text()
    assert "FlyWire FAFB v783" in methods and "fafb_783_meta.feather" in methods and "seed 1" in methods


def test_methods_paragraph_states_what_the_manifest_holds(tmp_path, toy_brain):
    _, run = export(tmp_path, spiking(output_gain=2), 20)
    manifest = json.loads((run / provenance.MANIFEST_FILE).read_text())
    text = provenance.methods_paragraph(manifest)
    nodes = graph(manifest)
    assert f"DigitalFly {nodes['#digitalfly']['version']}" in text
    assert "seed 5" in text
    assert "leaky integrate-and-fire" in text and "toy-brain" in text and nodes["#circuit"]["sha256"][:12] in text
    assert "connectome_parameters.output_gain = 2" in text and "(default 1" in text
    assert "0.2 s of simulated time" in text and "21 recorded samples" in text
    assert (run / provenance.METHODS_FILE).read_text().count(text) == 1


def test_spiking_runs_export_readout_spike_times(tmp_path, toy_brain):
    exp, run = export(tmp_path, spiking(input_gain=10), 200,
                      {0: lambda e: e.set_stimulus(Stimulus(x=0, y=5))})
    meta = json.loads((run / "metadata.json").read_text())
    with np.load(run / SPIKE_FILE) as data:
        times, units = data["spike_time_s"], data["spike_unit"]
        assert data["unit_cell_type"].tolist() == ["DNx", "DNx"] and data["unit_side"].tolist() == ["left", "right"]
        assert data["unit_root_id"].tolist() == ["1", "2"]
    assert meta["spikes"]["spikes"] == len(times) > 0 and meta["spikes"]["units"] == 2
    assert np.all(np.diff(times) >= 0) and times.max() < 2.0 and set(units.tolist()) <= {0, 1}
    # Spike times agree with the recorded firing rate: rate_hz jumps by 1000 / window at each spike.
    rows = np.genfromtxt(run / "telemetry.csv", delimiter=",", names=True)
    window = exp.circuit.parameters.spiking.rate_window_ms / 1000
    scale = exp.circuit.parameters.spiking.rate_scale_hz
    for unit, column in ((0, "rate_dnx_l"), (1, "rate_dnx_r")):
        t = rows["time_s"][-1]
        own = times[units == unit]
        expected = np.sum(np.exp(-(t - own[own < t] - 1e-4) / window)) / window / scale
        assert rows[column][-1] == pytest.approx(expected, rel=.02, abs=1e-6)


def test_rate_runs_record_no_spikes(tmp_path, toy_brain):
    _, run = export(tmp_path, RunConfig(engine="toy", neural_model="connectome",
                                        connectome_parameters=ConnectomeParameters(circuit="toy-brain")), 10)
    assert not (run / SPIKE_FILE).exists() and json.loads((run / "metadata.json").read_text())["spikes"] is None


def test_spike_recording_changes_no_number(tmp_path, toy_brain):
    """Replay equality: a recorded and an unrecorded spiking run are identical."""
    config = spiking(input_gain=10)
    runs = []
    for record in (True, False):
        exp = Experiment(config, render=False, record=record)
        try:
            for _ in range(80):
                exp.advance()
            runs.append((exp.sample.rates, exp.sample.pose.x, exp.circuit.spiking.v.copy()))
        finally:
            exp.close()
    assert runs[0][0] == runs[1][0] and runs[0][1] == runs[1][1] and np.array_equal(runs[0][2], runs[1][2])


def test_old_runs_get_a_manifest_and_methods(tmp_path):
    run = tmp_path / "20261021T153237-ec8b3ba1-abcdef"
    shutil.copytree(OLD_RUN, run)
    manifest = provenance.run_manifest(run)
    nodes = graph(manifest)
    assert nodes["#digitalfly"]["version"] == "0.5.0" and nodes["#digitalfly"]["digitalfly:gitCommit"] == "not recorded"
    assert {p["@id"] for p in nodes["./"]["hasPart"]} == {"metadata.json", "telemetry.csv"}
    assert "predates manifests" in nodes["./"]["digitalfly:manifestBuilt"]
    assert nodes["#setting-connectome_parameters.dynamics"]["value"] == "spiking"
    assert nodes["#circuit"]["sha256"] == json.loads((run / "metadata.json").read_text())["neural"]["circuit_sha256"]
    text = provenance.run_methods(run)
    assert "DigitalFly 0.5.0" in text and "seed 3" in text and "fafb783-dna02" in text
    assert not (run / provenance.MANIFEST_FILE).exists()  # built on demand; the saved run is left as it was


def test_comparison_paragraph_names_what_varies(tmp_path, toy_brain):
    manifests, conditions = [], {}
    for seed in (1, 2):
        for gain in (1, 3):
            exp, run = export(tmp_path, spiking(output_gain=gain).model_copy(update={"seed": seed}), 5)
            manifests.append(json.loads((run / provenance.MANIFEST_FILE).read_text()))
            conditions[exp.run_id] = f"gain {gain}"
    text = provenance.comparison_paragraph(manifests, conditions, {"ci95": "percentile bootstrap"})
    assert "We compared 4 runs in 2 conditions with seeds 1, 2" in text
    assert "gain 1 (n = 2); gain 3 (n = 2)" in text
    assert "Settings that varied between runs: connectome_parameters.output_gain." in text
    assert "ci95: percentile bootstrap" in text and "seed 1 and" not in text


def test_api_serves_manifest_and_methods(tmp_path, monkeypatch):
    from digitalfly.main import create_app
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    _, run = export(tmp_path / "runs", RunConfig(engine="toy", seed=4), 5)
    old = tmp_path / "runs" / "20261021T153237-ec8b3ba1-abcdef"
    shutil.copytree(OLD_RUN, old)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        manifest = client.get(f"/api/runs/{run.name}/manifest").json()
        assert manifest == json.loads((run / provenance.MANIFEST_FILE).read_text())
        assert client.get(f"/api/runs/{run.name}/methods").json()["markdown"] == (run / provenance.METHODS_FILE).read_text()
        assert "DigitalFly 0.5.0" in client.get(f"/api/runs/{old.name}/methods").json()["markdown"]
        assert client.get(f"/api/runs/{old.name}/manifest").status_code == 200
        assert client.get("/api/runs/20990101T000000-00000000-000000/manifest").status_code == 404
        assert client.get("/api/runs/not-a-run/methods").status_code == 404
        assert isinstance(client.get("/api/capabilities").json()["nwb_export"], bool)
