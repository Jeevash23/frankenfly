"""A comparison's summary counts each condition and seed once, from trials that ran their protocol to the end."""
import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import Protocol, RunConfig
from digitalfly.data.research import BatchSummary, batch_summary
from digitalfly.main import create_app
from digitalfly.simulation.experiment import Experiment
from test_run_library_extras import fake_run, key, trial


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def until(client, condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition(state := client.get("/api/status").json()):
        assert time.monotonic() < deadline, state["batch"]
        time.sleep(.02)
    return state


def test_an_export_during_a_comparison_is_saved_partial_and_left_out_of_its_summary(client):
    config = RunConfig(engine="toy", speed=.05, protocol=Protocol(name="P", duration_steps=40))
    started = client.post("/api/batch/start", json={"config": config.model_dump(), "seeds": [1, 2],
                                                    "conditions": ["control", "left_sensor_off"]})
    batch_id = started.json()["batch"]["id"]
    until(client, lambda state: state["sample"]["step"] >= 1)
    assert client.post("/api/pause", json={}).status_code == 200
    export = client.post("/api/export", json={}).json()  # the first trial, saved by hand before its end
    saved = json.loads((Path(export["path"]) / "metadata.json").read_text())
    assert saved["trial"]["partial"] and saved["trial"]["condition"] == "control" and saved["trial"]["seed"] == 1
    assert not saved["metrics"]["protocol_complete"]
    assert client.post("/api/speed", json={"speed": 2}).status_code == 200
    assert client.post("/api/run", json={}).status_code == 200
    batch = until(client, lambda state: state["batch"]["status"] != "running")["batch"]
    assert batch["status"] == "completed" and len(batch["results"]) == 4
    # The trial itself, finished afterwards, is saved complete.
    first = json.loads((Path(batch["results"][0]["path"]) / "metadata.json").read_text())
    assert "partial" not in first["trial"] and first["metrics"]["protocol_complete"]
    assert client.get("/api/runs", params={"batch": batch_id}).headers["X-Total-Count"] == "5"
    summary = client.get(f"/api/batches/{batch_id}/summary").json()
    assert BatchSummary.model_validate(summary)
    assert (summary["n_trials"], summary["partial_trials"], summary["duplicate_trials"]) == (4, 1, 0)
    assert [c["n"] for c in summary["conditions"]] == [2, 2] and {p["n_pairs"] for p in summary["paired"]} == {2}


def test_the_summary_counts_complete_trials_once_per_condition_and_seed(tmp_path):
    runs = tmp_path / "runs"

    def metrics(path, complete=True):
        return {"target_distance_mm": 5, "path_length_mm": path, "net_turn_deg": 0, "mean_speed_mm_s": 1,
                "min_target_distance_mm": 1, "protocol_complete": complete}
    for index, (condition, seed) in enumerate([("control", 1), ("off", 1), ("control", 2), ("off", 2)], 1):
        fake_run(runs, key(index), trial=trial("cmp", condition, seed, index), metrics=metrics(10 * index))
    # Saved by hand before the trial ended, by a version that did not mark it partial; and a second copy of a trial.
    fake_run(runs, key(10), trial=trial("cmp", "control", 1, 1), metrics=metrics(999, complete=False))
    fake_run(runs, key(11), trial=trial("cmp", "off", 2, 4), metrics=metrics(999))
    fake_run(runs, key(12), trial=trial("cmp", "off", 1, 2, partial=True), metrics=metrics(999))
    data = batch_summary("cmp", runs)
    assert (data["n_trials"], data["partial_trials"]) == (4, 2) and data["duplicate_trials"] == 1
    assert {c["condition"]: c["n"] for c in data["conditions"]} == {"control": 2, "off": 2}
    path = {c["condition"]: c["metrics"]["path_length_mm"]["mean"] for c in data["conditions"]}
    assert path == {"control": 20, "off": 30}
    assert {p["n_pairs"] for p in data["paired"]} == {2}


def test_a_state_that_cannot_be_published_ends_the_comparison_and_restores_the_workbench(client, monkeypatch):
    workbench = client.post("/api/reset", json=RunConfig(engine="toy", seed=7).model_dump()).json()["config"]
    config = RunConfig(engine="toy", seed=7, speed=.05, protocol=Protocol(duration_steps=200))
    assert client.post("/api/batch/start", json={"config": config.model_dump(), "seeds": [1],
                                                 "conditions": ["baseline"]}).status_code == 200
    until(client, lambda state: state["sample"]["step"] >= 1)
    real, failures = Experiment.connectome_snapshot, [KeyError("readout")]

    def once(self):
        if failures:
            raise failures.pop()
        return real(self)
    monkeypatch.setattr(Experiment, "connectome_snapshot", once)
    state = until(client, lambda state: state["batch"]["status"] != "running")
    # Like any failed comparison: the workbench is back, ready to run, and the unfinished trial is saved.
    assert state["config"] == workbench and state["status"] == "paused" and state["error"] is None
    batch = state["batch"]
    assert batch["status"] == "failed" and "readout" in batch["error"] and batch["partial"]["partial"]
