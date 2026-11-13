"""Export schema 5: target, stimulus and intervention telemetry columns, per-type activity, replay of old and new
exports, and exports written off the simulation thread."""
import csv
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
import numpy as np
import pytest
from digitalfly.api.models import Interventions, RunConfig, Stimulus
from digitalfly.neural.connectome import load_circuit
from digitalfly.simulation import experiment as experiment_module
from digitalfly.simulation.experiment import Experiment, ExportJob, intervention_code
from digitalfly.simulation.worker import SimulationWorker

ROOT = Path(__file__).resolve().parents[2]
BASE = ["step", "time_s", "x_mm", "y_mm", "z_mm", "yaw_rad", "speed_mm_s", "sensor_l", "sensor_r", "raw_sensor_l",
        "raw_sensor_r"]
TARGET = ["target_bearing_deg", "target_distance_mm", "stimulus_x_mm", "stimulus_y_mm", "stimulus_intensity",
          "intervention_code"]


def replay(run):
    return subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)], capture_output=True, text=True,
                          timeout=120)


def scheduled_run(tmp_path, config=None):
    exp = Experiment(config or RunConfig(engine="toy", seed=9), render=False)
    try:
        exp.set_stimulus(Stimulus(x=-6, y=14, intensity=.5))  # at step 0, after the first sample
        for i in range(60):
            if i == 20:
                exp.set_stimulus(Stimulus(x=5, y=-9))
            if i == 40:
                exp.set_interventions(Interventions(zero_left=True, silence="descending"))
            exp.advance()
        return exp, Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()


def test_telemetry_gains_target_and_intervention_columns(tmp_path):
    exp, run = scheduled_run(tmp_path)
    with (run / "telemetry.csv").open(newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        rows = [dict(zip(header, row)) for row in reader]
    assert header == BASE + ["rate_" + n.lower().replace(" ", "_") for n in exp.circuit.unit_names] + \
        ["motor_l", "motor_r"] + TARGET  # existing columns first, unchanged
    assert len(rows) == 61
    targets = [(float(r["stimulus_x_mm"]), float(r["stimulus_y_mm"]), float(r["stimulus_intensity"])) for r in rows]
    # Each row's target is the one its sample was taken with: a change at step k applies from step k + 1.
    assert targets[0] == (12, 8, 1) and set(targets[1:21]) == {(-6, 14, .5)} and set(targets[21:]) == {(5, -9, 1)}
    assert [r["intervention_code"] for r in rows] == ["L1R1"] * 41 + ["L0R1;units:descending"] * 20
    for row in rows:
        x, y, yaw = float(row["x_mm"]), float(row["y_mm"]), float(row["yaw_rad"])
        sx, sy = float(row["stimulus_x_mm"]), float(row["stimulus_y_mm"])
        assert float(row["target_distance_mm"]) == pytest.approx(math.hypot(sx - x, sy - y), abs=1e-12)
        bearing = math.degrees(math.atan2(sy - y, sx - x) - yaw)
        assert float(row["target_bearing_deg"]) == pytest.approx((bearing + 180) % 360 - 180, abs=1e-9)
        assert -180 <= float(row["target_bearing_deg"]) <= 180
    metadata = json.loads((run / "metadata.json").read_text())
    assert metadata["schema_version"] == 6 and metadata["units"]["target_bearing"] == "deg"
    assert metadata["activity"] is None and not (run / "activity_types.npz").exists()
    assert metadata["metrics"]["min_target_distance_mm"] == min(float(r["target_distance_mm"]) for r in rows)
    # replay.py compares its own columns by name and ignores the new ones, text included.
    done = replay(run)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["maximum_absolute_error"] == 0


def test_runs_saved_before_schema_5_still_replay(tmp_path):
    _, run = scheduled_run(tmp_path)
    old = tmp_path / "old"
    shutil.copytree(run, old)
    metadata = json.loads((old / "metadata.json").read_text())
    metadata["schema_version"] = 4
    for key in ["activity"]:
        metadata.pop(key)
    metadata["metrics"].pop("min_target_distance_mm")
    metadata["initial_config"].pop("record_activity")
    (old / "metadata.json").write_text(json.dumps(metadata))
    with (run / "telemetry.csv").open(newline="") as file:
        rows = [row[:-len(TARGET)] for row in csv.reader(file)]
    with (old / "telemetry.csv").open("w", newline="") as file:
        csv.writer(file).writerows(rows)
    done = replay(old)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["passed"]


def test_intervention_codes():
    assert intervention_code(Interventions()) == "L1R1"
    assert intervention_code(Interventions(zero_right=True, silence="sensory")) == "L1R0;units:sensory"
    weird = Interventions(zero_left=True, silence_dna02="left", silence_types=["DNp09", "odd name;x:y,z"])
    assert intervention_code(weird) == "L0R1;DNa02:left;DNp09:silence;odd_name_x_y_z:silence"
    # Cell-type entries: a side (none for both) and a mode with its value.
    v2 = Interventions(cell_types=[{"name": "DNp09", "side": "left", "mode": "scale", "value": .5},
                                   {"name": "LC10a", "mode": "activate", "value": 150},
                                   {"name": "DNa01", "side": "right", "mode": "silence"},
                                   {"name": "odd, name", "side": "left", "mode": "scale", "value": 1.25}])
    assert intervention_code(v2) == "L1R1;DNp09:L:scale0.5;LC10a:activate150;DNa01:R:silence;odd__name:L:scale1.25"
    assert all(c not in intervention_code(weird) for c in ',"#')


def connectome_config(**settings):
    return RunConfig(engine="toy", neural_model="connectome", connectome_parameters={"circuit": "toy-brain"}, **settings)


def replay_script():
    spec = importlib.util.spec_from_file_location("replay_script", ROOT / "scripts/replay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cell_type_interventions_are_coded_and_replay_exactly(toy_brain, tmp_path):
    exp = Experiment(connectome_config(seed=6, record_activity="types"), render=False)
    try:
        for _ in range(10):
            exp.advance()
        exp.set_interventions(Interventions(zero_right=True, silence_dna02="none", silence_types=["Spd"], cell_types=[
            {"name": "Inh", "side": "left", "mode": "scale", "value": .5},
            {"name": "LCa", "side": "right", "mode": "silence"},
            {"name": "DNy", "mode": "activate", "value": .3}]))
        for _ in range(20):
            exp.advance()
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    with (run / "telemetry.csv").open(newline="") as file:
        codes = [row["intervention_code"] for row in csv.DictReader(file)]
    assert codes == ["L1R1"] * 11 + ["L1R0;Spd:silence;Inh:L:scale0.5;LCa:R:silence;DNy:activate0.3"] * 20
    report = replay_script().replay(run)
    assert report["passed"] and report["maximum_absolute_error"] == 0, report["message"]
    assert report["samples"] == 31 and len(report["compared_rates"]) == len(exp.circuit.unit_names)


def test_per_type_activity_is_recorded_on_request(toy_brain, tmp_path):
    exp = Experiment(connectome_config(record_activity="types", seed=4), render=False)
    try:
        exp.set_interventions(Interventions(silence_types=["Inh"]))
        for _ in range(30):
            exp.advance()
        last = exp.circuit.type_means()
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    data = load_circuit(toy_brain)
    with np.load(run / "activity_types.npz", allow_pickle=False) as saved:
        assert saved["activity"].dtype == np.float32 and saved["activity"].shape == (31, len(data.type_names))
        np.testing.assert_array_equal(saved["step"], np.arange(31))
        np.testing.assert_array_equal(saved["time_s"], [round(s * .01, 8) for s in range(31)])
        assert list(saved["type_names"]) == list(data.type_names)
        np.testing.assert_array_equal(saved["neurons_per_type"], data.type_counts)
        np.testing.assert_array_equal(saved["activity"][-1], last.astype(np.float32))
        assert not saved["activity"][:, list(data.type_names).index("Inh")].any()  # silenced throughout
    metadata = json.loads((run / "metadata.json").read_text())
    assert metadata["activity"]["file"] == "activity_types.npz" and metadata["activity"]["samples"] == 31
    assert metadata["activity"]["every_steps"] == 1 and metadata["activity"]["units"] == "dimensionless rate"
    with zipfile.ZipFile(f"{run}.zip") as archive:
        assert archive.getinfo("activity_types.npz").compress_type == zipfile.ZIP_STORED


def test_a_committed_circuit_run_with_activity_replays(tmp_path):
    config = RunConfig(engine="toy", neural_model="connectome", record_activity="types", seed=2)
    exp = Experiment(config, render=False)
    try:
        for _ in range(20):
            exp.advance()
        run = Path(exp.export(tmp_path)["path"])
        types = len(exp.circuit.data.type_names)
    finally:
        exp.close()
    with np.load(run / "activity_types.npz") as saved:
        assert saved["activity"].shape == (21, types) and np.isfinite(saved["activity"]).all()
    done = replay(run)
    assert done.returncode == 0, done.stderr


def test_activity_recording_halves_its_rate_to_stay_within_its_budget(toy_brain, tmp_path, monkeypatch):
    types = len(load_circuit(toy_brain).type_names)
    monkeypatch.setattr(experiment_module, "ACTIVITY_BYTES", 10 * types * 4)  # ten samples
    exp = Experiment(connectome_config(record_activity="types"), render=False)
    try:
        for _ in range(60):
            exp.advance()
        assert exp.activity_every == 8 and exp.activity_steps == list(range(0, 61, 8))
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    with np.load(run / "activity_types.npz") as saved:
        np.testing.assert_array_equal(saved["step"], range(0, 61, 8))
        assert saved["activity"].shape == (8, types)
    assert json.loads((run / "metadata.json").read_text())["activity"]["every_steps"] == 8


def test_activity_needs_the_connectome_model_and_a_recording(toy_brain, tmp_path):
    engineered = Experiment(RunConfig(engine="toy", record_activity="types"), render=False)
    lean = Experiment(connectome_config(record_activity="types"), render=False, record=False)
    plain = Experiment(connectome_config(), render=False)
    try:
        for exp in [engineered, lean, plain]:
            exp.advance()
        assert lean.activity == [] and lean.activity_steps == []
        for exp in [engineered, plain]:
            run = Path(exp.export(tmp_path)["path"])
            assert not (run / "activity_types.npz").exists() and json.loads((run / "metadata.json").read_text())["activity"] is None
    finally:
        for exp in [engineered, lean, plain]:
            exp.close()
    with pytest.raises(ValueError):
        RunConfig(record_activity="neurons")


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.ROOT", tmp_path)
    worker = SimulationWorker(RunConfig(engine="toy"), render=False)
    worker.start()
    assert worker.ready.wait(10)
    yield worker
    worker.close()


def held_writes(monkeypatch):
    """ExportJob.write held until released, counting how many run at once."""
    release, state, lock = threading.Event(), {"running": 0, "most": 0, "started": 0}, threading.Lock()
    write = ExportJob.write

    def held(job):
        with lock:
            state["running"] += 1
            state["started"] += 1
            state["most"] = max(state["most"], state["running"])
        try:
            assert release.wait(10)
            return write(job)
        finally:
            with lock:
                state["running"] -= 1
    monkeypatch.setattr(ExportJob, "write", held)
    return release, state


def export_events(worker):
    return [e for e in worker.get_snapshot()["events"] if e["kind"] == "export"]


def test_exports_are_written_while_the_simulation_goes_on(worker, monkeypatch):
    release, state = held_writes(monkeypatch)
    first, second = worker.submit("export", {}), worker.submit("export", {"share_safe": True})
    # The simulation thread answers other commands while both exports wait to be written.
    for _ in range(5):
        worker.submit("step", {}).result(timeout=5)
    assert worker.get_snapshot()["sample"]["step"] == 5
    assert not first.done() and not second.done() and state["started"] == 1 and export_events(worker) == []
    release.set()
    results = [first.result(timeout=10), second.result(timeout=10)]
    assert state["most"] == 1  # one export at a time
    # Each holds the run as it was when the export was requested, and its files are complete when it answers.
    for result in results:
        run = Path(result["path"])
        assert result["samples"] == 1 and (run / "telemetry.csv").read_text().count("\n") == 2
        assert Path(f"{run}.zip").is_file() and result["download_url"].endswith(f"{run.name}.zip")
    assert "platform" not in json.loads((Path(results[1]["path"]) / "metadata.json").read_text())
    worker.submit("pause", {}).result(timeout=5)  # a command after both: their events are logged by now
    assert [e["message"] for e in export_events(worker)] == ["Saved 1 samples locally"] * 2


def test_a_failed_export_answers_with_its_error(worker, monkeypatch):
    def broken(job):
        raise OSError("No space left on device")
    monkeypatch.setattr(ExportJob, "write", broken)
    with pytest.raises(OSError, match="No space"):
        worker.submit("export", {}).result(timeout=10)
    worker.submit("step", {}).result(timeout=5)
    assert export_events(worker) == [] and worker.get_snapshot()["status"] == "paused"


def test_closing_waits_for_exports_being_written(tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.ROOT", tmp_path)
    release, _ = held_writes(monkeypatch)
    worker = SimulationWorker(RunConfig(engine="toy"), render=False)
    worker.start()
    assert worker.ready.wait(10)
    export = worker.submit("export", {})
    worker.submit("step", {}).result(timeout=5)
    threading.Timer(.3, release.set).start()
    worker.close()
    assert Path(export.result(timeout=1)["path"]).is_dir()
