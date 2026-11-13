"""NWB export of saved runs: a round trip through pynwb, the validator, old exports, the toolkit and the API.
Skipped without pynwb (backend/requirements-nwb.lock)."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest

pynwb = pytest.importorskip("pynwb")
from fastapi.testclient import TestClient  # noqa: E402
from digitalfly import nwb, provenance  # noqa: E402
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, Stimulus  # noqa: E402
from digitalfly.simulation.experiment import Experiment  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OLD_RUN = ROOT / "backend/tests/fixtures/v05-spiking-edits"


def recorded(tmp_path, config, steps=120):
    exp = Experiment(config, render=False)
    try:
        for i in range(steps):
            if i == 30:
                exp.set_interventions(Interventions(zero_left=True))
            if i == 60:
                exp.set_stimulus(Stimulus(x=-6, y=14, intensity=.5))
            if i == 90:
                exp.set_interventions(Interventions())
            exp.advance()
        return exp, Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()


def telemetry(run):
    with (run / "telemetry.csv").open(newline="") as file:
        return list(csv.DictReader(file))


def column(rows, name):
    return np.array([float(r[name]) for r in rows])


def read(path):
    io = pynwb.NWBHDF5IO(str(path), "r")
    return io, io.read()


def test_spiking_run_round_trips_through_nwb(tmp_path, toy_brain):
    config = RunConfig(engine="toy", seed=4, neural_model="connectome", record_activity="types",
                       connectome_parameters=ConnectomeParameters(circuit="toy-brain", dynamics="spiking", input_gain=10))
    exp, run = recorded(tmp_path, config)
    path = nwb.export_run(run)
    assert path == run / f"{run.name}.nwb" and nwb.validate(path) == []
    rows, meta = telemetry(run), json.loads((run / "metadata.json").read_text())
    io, f = read(path)
    try:
        assert f.identifier == run.name and f.session_id == meta["run_id"]
        assert f.subject.species == "Drosophila melanogaster"
        assert "toy-brain" in f.experiment_description and "leaky integrate-and-fire" in f.experiment_description
        behavior, model = f.processing["behavior"], f.processing["model"]
        position = behavior["Position"]["body_position"]
        assert position.conversion == 1e-3 and position.rate == pytest.approx(100)
        assert np.allclose(position.data[:, 0], column(rows, "x_mm")) and np.allclose(position.data[:, 2], column(rows, "z_mm"))
        assert np.allclose(behavior["CompassDirection"]["heading"].data[:], column(rows, "yaw_rad"))
        speed = behavior["BehavioralTimeSeries"]["speed"]
        assert np.allclose(speed.data[:], column(rows, "speed_mm_s"))
        assert np.allclose(model["sensor_input"].data[:, 1], column(rows, "sensor_r"))
        readout = model["readout_activity"]
        assert readout.unit == "Hz" and readout.conversion == 100  # rate_scale_hz
        assert np.allclose(readout.data[:, 1], column(rows, "rate_dnx_r"))
        columns = model["readout_columns"].to_dataframe()
        assert columns["column"].tolist() == meta["neural"]["unit_names"]
        assert columns["cell_type"].tolist()[:2] == ["DNx", "DNx"] and columns["side"].tolist()[:2] == ["left", "right"]
        assert columns["root_ids"].tolist()[:2] == ["1", "2"]
        with np.load(run / "activity_types.npz") as activity:
            assert np.allclose(model["cell_type_activity"].data[:], activity["activity"])
            assert model["cell_types"].to_dataframe()["cell_type"].tolist() == activity["type_names"].tolist()
        # Spike times: one unit per readout neuron, the times exported in spikes_readout.npz.
        with np.load(run / "spikes_readout.npz") as spikes:
            units = f.units.to_dataframe()
            assert units["cell_type"].tolist() == ["DNx", "DNx"] and units["side"].tolist() == ["left", "right"]
            assert units["root_id"].tolist() == ["1", "2"]
            for i in range(2):
                assert np.allclose(units["spike_times"].iloc[i], spikes["spike_time_s"][spikes["spike_unit"] == i])
        assert sum(len(t) for t in units["spike_times"]) == meta["spikes"]["spikes"] > 0
        # Stimulus: the initial target, then the change at step 60.
        target = f.stimulus["target_position"]
        assert target.timestamps[:].tolist() == [0, .6] and target.data[:].tolist() == [[12, 8], [-6, 14]]
        assert f.stimulus["target_intensity"].data[:].tolist() == [1, .5]
        # Interventions: intervals of constant interventions, with telemetry's codes.
        intervals = f.intervals["interventions"].to_dataframe()
        assert intervals["start_time"].tolist() == [0, .3, .9]
        assert intervals["stop_time"].tolist() == pytest.approx([.3, .9, 1.21])
        assert intervals["code"].tolist() == ["L1R1", "L0R1", "L1R1"]
        codes = [r["intervention_code"] for r in rows]  # telemetry: a change at step k shows from row k + 1
        assert codes[30] == "L1R1" and codes[31] == "L0R1" and codes[91] == "L1R1"
        stored = f.scratch["digitalfly_manifest"].data
        manifest = json.loads(stored if isinstance(stored, str) else stored[()])
        assert manifest == json.loads((run / provenance.MANIFEST_FILE).read_text())
    finally:
        io.close()


def test_engineered_run_has_no_units(tmp_path):
    _, run = recorded(tmp_path, RunConfig(engine="toy", seed=1), 40)
    path = nwb.export_run(run, tmp_path / "out.nwb")
    assert nwb.validate(path) == []
    io, f = read(path)
    try:
        assert f.units is None
        assert f.processing["model"]["readout_columns"].to_dataframe()["kind"].tolist() == ["engineered unit"] * 6
        assert f.processing["model"]["readout_activity"].unit == "n.a."
    finally:
        io.close()


def test_old_exports_convert(tmp_path):
    """A v0.5 export (schema 3): no target columns, manifest or spikes; the stimulus comes from its events."""
    run = tmp_path / "20261021T153237-ec8b3ba1-abcdef"
    shutil.copytree(OLD_RUN, run)
    path = nwb.export_run(run)
    assert nwb.validate(path) == []
    rows, meta = telemetry(run), json.loads((run / "metadata.json").read_text())
    io, f = read(path)
    try:
        assert "DigitalFly 0.5.0" in f.experiment_description and f.units is None
        assert len(f.processing["behavior"]["Position"]["body_position"].data) == len(rows)
        assert f.stimulus["target_position"].data[0].tolist() == [meta["initial_config"]["stimulus"]["x"],
                                                                 meta["initial_config"]["stimulus"]["y"]]
    finally:
        io.close()
    assert sorted(p.name for p in run.iterdir()) == sorted(["metadata.json", "telemetry.csv", path.name])


def test_toolkit_command_writes_and_validates(tmp_path):
    run = tmp_path / "20261021T153237-ec8b3ba1-abcdef"
    shutil.copytree(OLD_RUN, run)
    done = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "nwb", str(run), "--out", str(tmp_path / "a.nwb")],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert "validator found no problems" in done.stdout and (tmp_path / "a.nwb").is_file()
    methods = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "methods", str(run)],
                             capture_output=True, text=True, timeout=120)
    assert methods.returncode == 0 and "DigitalFly 0.5.0" in methods.stdout


def test_api_downloads_nwb(tmp_path, monkeypatch):
    from digitalfly.main import create_app
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    _, run = recorded(tmp_path / "runs", RunConfig(engine="toy", seed=2), 20)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        assert client.get("/api/capabilities").json()["nwb_export"] is True
        response = client.get(f"/api/runs/{run.name}/nwb")
        assert response.status_code == 200 and response.headers["content-type"] == "application/x-nwb"
        assert f'filename="{run.name}.nwb"' in response.headers["content-disposition"]
        (tmp_path / "download.nwb").write_bytes(response.content)
        assert nwb.validate(tmp_path / "download.nwb") == []
        monkeypatch.setattr("digitalfly.nwb.available", lambda: False)
        assert client.get(f"/api/runs/{run.name}/nwb").status_code == 503
