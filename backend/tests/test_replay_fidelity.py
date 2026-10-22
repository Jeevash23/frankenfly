"""Exported runs replay exactly: several input changes within one control step, readout cell types whose names
contain commas, v0.5 spiking runs with live parameter edits, and a live change whose update fails."""
import csv
import importlib.util
import json
import shutil
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import (CellTypeIntervention, ConnectomeParameters, Interventions, NeuralParameters, RunConfig,
                                   Stimulus)
from digitalfly.main import create_app
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("replay_fidelity", ROOT / "scripts/replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
TOY = {"circuit": "toy-brain", "global_gain": .05}
# Toy circuit (conftest): DNx readout, LCa input (also read out as "Visual input"), Solo excites DNx left only.


def connectome(dynamics="rate", **parameters):
    return {"engine": "toy", "seed": 3, "neural_model": "connectome", "stimulus": {"x": 20, "y": 15},
            "connectome_parameters": {**TOY, "dynamics": dynamics, **parameters}}


def cells(*items):
    return Interventions(cell_types=[CellTypeIntervention(name=name, mode=mode, value=value) for name, mode, value in items])


def apply(exp, change):
    {Interventions: exp.set_interventions, Stimulus: exp.set_stimulus, NeuralParameters: exp.set_parameters,
     ConnectomeParameters: exp.set_connectome_parameters}[type(change)](change)


def run_and_replay(tmp_path, config, changes, before=30, after=40):
    """Run, make every change at one step (as while paused), run on, export and replay in this process."""
    exp = Experiment(RunConfig.model_validate(config), render=False)
    try:
        for _ in range(before):
            exp.advance()
        for change in changes:
            apply(exp, change)
        for _ in range(after):
            exp.advance()
        logged = [e.kind for e in exp.events if e.step == before]
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    return logged, replay.replay(run)


MOTOR = {"motor_tau_ms": 50, "output_gain": 5}
# Changes that alter the network or the motor path as they apply (silenced neurons go to rest, a clamped rate is set,
# the motor path restarts): each must be logged, or replay misses the state the earlier ones left.
EVERY_CHANGE = {
    "silence then restore, rate": (connectome(), [cells(("LCa", "silence", 0)), Interventions()]),
    "silence one type then another, rate": (connectome(), [cells(("LCa", "silence", 0)), cells(("DNx", "silence", 0))]),
    "activate one type then another, rate": (connectome(), [cells(("Solo", "activate", .6)), cells(("DNy", "activate", .6))]),
    "silence then restore, spiking": (connectome("spiking"), [Interventions(silence_types=["LCa"]), Interventions()]),
    "silence one type then another, spiking": (connectome("spiking"), [cells(("LCa", "silence", 0)),
                                                                      cells(("DNx", "silence", 0))]),
    "motor low-pass off and on": (connectome(**MOTOR), [ConnectomeParameters(**TOY, **{**MOTOR, "motor_tau_ms": 0}),
                                                        ConnectomeParameters(**TOY, **MOTOR)]),
    "engineered silence then restore": ({"engine": "toy", "seed": 3}, [Interventions(silence="steering"), Interventions()]),
}
# Changes whose last value is all that reaches the simulation: repeats within a step still keep only the last.
LAST_CHANGE = {
    "stimulus": (connectome("spiking", **MOTOR) | {"initial_interventions": {"silence_types": ["Inh"]}},
                 [Stimulus(x=-20, y=0), Stimulus(x=20, y=-20)]),
    "engineered parameters": ({"engine": "toy", "seed": 3}, [NeuralParameters(steering_gain=2), NeuralParameters(steering_gain=.5)]),
}


@pytest.mark.parametrize("name", list(EVERY_CHANGE))
def test_every_change_within_one_step_is_logged_and_replays(toy_brain, tmp_path, name):
    config, changes = EVERY_CHANGE[name]
    logged, report = run_and_replay(tmp_path, config, changes)
    assert len(logged) == len(changes)
    assert report["passed"] and report["maximum_absolute_error"] == 0, report["message"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy", seed=5, neural_model="connectome"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_the_app_verifies_a_run_whose_manipulation_was_changed_while_paused(client):
    """Silence LC10a, think better of it and silence LC10c instead, then step on: the app's own replay check of
    the export used to fail (the first silencing had already reset LC10a, and its event was dropped)."""
    for _ in range(20):
        assert client.post("/api/step", json={}).status_code == 200
    for name in ["LC10a", "LC10c"]:
        assert client.post("/api/interventions", json={"cell_types": [{"name": name, "mode": "silence"}]}).status_code == 200
    for _ in range(20):
        client.post("/api/step", json={})
    events = [(e["step"], e["kind"]) for e in client.get("/api/status").json()["events"]]
    assert events.count((20, "interventions")) == 2
    key = Path(client.post("/api/export", json={}).json()["path"]).name
    job = client.post(f"/api/runs/{key}/replay", json={}).json()["job"]
    deadline = time.monotonic() + 120
    while job["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.05)
        job = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job["id"])
    verified = client.get(f"/api/runs/{key}").json()["verified"]
    assert job["status"] == "done" and verified["ok"] and verified["max_abs_error"] == 0, verified


@pytest.mark.parametrize("name", list(LAST_CHANGE))
def test_repeated_stimulus_or_parameter_changes_within_one_step_keep_the_last(toy_brain, tmp_path, name):
    config, changes = LAST_CHANGE[name]
    logged, report = run_and_replay(tmp_path, config, changes)
    assert len(logged) == 1
    assert report["passed"] and report["maximum_absolute_error"] == 0, report["message"]


def test_readout_types_with_commas_in_their_names_replay(tmp_path):
    readout = ["DNa02", "LAL003,LAL044", "LAL028, LAL029"]  # FlyWire names a few merged types this way
    logged, report = run_and_replay(tmp_path, {"engine": "toy", "seed": 3, "neural_model": "connectome",
                                               "connectome_parameters": {"readout_types": readout}},
                                    [cells(("LAL003,LAL044", "silence", 0))], before=10, after=10)
    run = next(path for path in tmp_path.iterdir() if path.is_dir())
    with (run / "telemetry.csv").open(newline="") as file:
        header = next(csv.reader(file))
    assert ["rate_lal003,lal044_l", "rate_lal028,_lal029_r"] == [header[13], header[16]]  # column names unchanged
    assert report["passed"] and report["maximum_absolute_error"] == 0, report["message"]
    assert report["compared_rates"][2:6] == ["rate_lal003,lal044_l", "rate_lal003,lal044_r", "rate_lal028,_lal029_l",
                                             "rate_lal028,_lal029_r"]
    assert report["column_errors"]["rate_lal028,_lal029_r"] == 0


def test_a_ragged_or_textual_telemetry_file_is_reported(tmp_path):
    run = shutil.copytree(FIXTURES / "v05-spiking-edits", tmp_path / "run")
    lines = (run / "telemetry.csv").read_text().splitlines()
    (run / "telemetry.csv").write_text("\n".join(lines[:10] + ["1,2"] + lines[11:]) + "\n")
    report = replay.replay(run)
    assert not report["passed"] and report["message"] == "telemetry.csv is unreadable: line 11 has 2 fields, the header 18"
    cells_ = lines[5].split(",")
    cells_[2] = "north"
    (run / "telemetry.csv").write_text("\n".join(lines[:5] + [",".join(cells_)] + lines[6:]) + "\n")
    report = replay.replay(run)
    assert not report["passed"] and report["message"] == "x_mm at step 4 is not a number in telemetry.csv"
    (run / "telemetry.csv").write_text("")
    assert replay.replay(run)["message"] == "telemetry.csv lacks the columns step, x_mm, y_mm, z_mm, yaw_rad, motor_l, motor_r"


def test_v05_spiking_runs_with_live_parameter_edits_replay(toy_brain, tmp_path):
    """Up to v0.5 (export schema 3) every live connectome parameter edit restarted the spiking network from the run's
    seed; later versions keep it. The fixture was recorded with v0.5.0 (main c929052): fafb783-dna02, spiking, seed 3,
    edits at steps 15 (output gain) and 35 (input gain, synapse weight), DNa02 left silenced at 25, target moved at 45."""
    run = shutil.copytree(FIXTURES / "v05-spiking-edits", tmp_path / "run")
    metadata = json.loads((run / "metadata.json").read_text())
    assert metadata["schema_version"] == 3 and metadata["application_version"] == "0.5.0"
    report = replay.replay(run)
    assert report["passed"] and report["maximum_absolute_error"] == 0 and report["samples"] == 61, report["message"]
    # The fixture needs the restart: read as a run of this version, it no longer matches.
    (run / "metadata.json").write_text(json.dumps({**metadata, "schema_version": 5}))
    assert not replay.replay(run)["passed"]
    # Runs of this version keep the network across edits, and replay that way.
    logged, report = run_and_replay(tmp_path / "now", connectome("spiking"), [
        ConnectomeParameters(**TOY, dynamics="spiking", output_gain=2, spiking={"synapse_weight_mv": .4})])
    assert logged == ["connectome_parameters"]
    assert report["passed"] and report["maximum_absolute_error"] == 0, report["message"]


@pytest.mark.parametrize("change", [cells(("LCa", "silence", 0)), Stimulus(x=-15, y=5)], ids=["interventions", "stimulus"])
def test_a_live_change_whose_update_fails_ends_the_run_and_the_export_replays(toy_brain, tmp_path, change):
    exp = Experiment(RunConfig.model_validate(connectome()), render=False)
    try:
        for _ in range(20):
            exp.advance()
        def lost(*args):
            raise RuntimeError("eye camera lost")
        exp.body.sensors = lost
        with pytest.raises(RuntimeError, match="eye camera lost"):
            apply(exp, change)  # silenced neurons went to rest, or the target moved, before the update failed
        del exp.body.sensors
        assert exp.status == "error" and exp.error == "RuntimeError: eye camera lost"
        assert exp.interventions == Interventions() and exp.config.stimulus == Stimulus(x=20, y=15)
        for _ in range(20):
            if exp.status == "error":
                break
            exp.advance()
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    report = replay.replay(run)
    assert report["passed"] and report["samples"] == 21, report["message"]
