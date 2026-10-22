"""The run library's filters, tags and notes, and per-condition summaries of comparisons."""
import csv
import io
import json
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from digitalfly import toolkit
from digitalfly.api.models import Protocol, RunConfig
from digitalfly.data.research import RunAnnotations, annotate_run, batch_summary, list_runs
from digitalfly.main import create_app

CONNECTOME = RunConfig(engine="toy").model_dump() | {"neural_model": "connectome"}


def fake_run(runs: Path, key: str, config=None, trial=None, metrics=None, samples=10):
    directory = runs / key
    directory.mkdir(parents=True)
    metadata = {"schema_version": 5, "run_id": key[:24], "created_utc": "2026-01-01T12:00:00+00:00",
                "initial_config": config or RunConfig(engine="toy").model_dump(), "recorded_samples": samples,
                "metrics": metrics or {}, "trial": trial, "error": None, "provenance": {"body_engine": "toy"}}
    (directory / "metadata.json").write_text(json.dumps(metadata))
    (runs / f"{key}.zip").write_bytes(b"PK")
    return directory


def key(day: int, suffix="abcdef") -> str:
    return f"202601{day:02d}T120000-{day:08x}-{suffix}"


def trial(batch, condition, seed, index, **extra):
    return {"batch_id": batch, "condition": condition, "seed": seed, "index": index, "total": 4,
            "neural_model": "engineered", "cell_type": None, **extra}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def keys(response):
    return [run["key"] for run in response.json()["runs"]]


def test_filters_combine_with_paging_and_the_total(client, tmp_path):
    runs = tmp_path / "runs"
    steering = {**CONNECTOME, "connectome_parameters": {"circuit": "fafb783-steering"}}
    legacy = {**RunConfig(engine="toy").model_dump(), "neural_model": "connectome_dna02"}  # v0.3, no circuit field
    del legacy["connectome_parameters"]
    fake_run(runs, key(1), config=CONNECTOME, trial=trial("b1", "control", 1, 1))
    fake_run(runs, key(2), config=CONNECTOME, trial=trial("b1", "dna02_both_off", 1, 2))
    fake_run(runs, key(3), config=CONNECTOME, trial=trial("b1", "control", 2, 3))
    fake_run(runs, key(4), config=steering)
    fake_run(runs, key(5))
    fake_run(runs, key(6), config=legacy)
    fake_run(runs, key(7), trial=trial("b2", "control", 1, 1))
    every = client.get("/api/runs")
    assert every.headers["X-Total-Count"] == "7"
    item = every.json()["runs"][-1]
    assert item["batch_id"] == "b1" and item["condition"] == "control" and item["tags"] == [] and item["notes"] == ""
    assert every.json()["runs"][2]["batch_id"] is None and every.json()["runs"][2]["condition"] is None

    connectome = client.get("/api/runs", params={"model": "connectome"})
    assert connectome.headers["X-Total-Count"] == "5" and keys(connectome) == [key(6), key(4), key(3), key(2), key(1)]
    assert keys(client.get("/api/runs", params={"model": "engineered"})) == [key(7), key(5)]
    # Circuit means connectome runs on it: engineered runs carry the default circuit name too.
    default = client.get("/api/runs", params={"circuit": "fafb783-dna02"})
    assert keys(default) == [key(6), key(3), key(2), key(1)]
    assert keys(client.get("/api/runs", params={"circuit": "fafb783-steering"})) == [key(4)]
    batch = client.get("/api/runs", params={"batch": "b1", "model": "connectome", "offset": 1, "limit": 1})
    assert batch.headers["X-Total-Count"] == "3" and keys(batch) == [key(2)]
    page = client.get("/api/runs", params={"batch": "b1", "q": "CONTROL", "limit": 1})
    assert page.headers["X-Total-Count"] == "2" and keys(page) == [key(3)]
    assert keys(client.get("/api/runs", params={"q": key(4)[:20]})) == [key(4)]
    none = client.get("/api/runs", params={"batch": "b2", "model": "connectome"})
    assert none.headers["X-Total-Count"] == "0" and none.json() == {"runs": []}
    for bad in [{"model": "spiking"}, {"circuit": "../x"}, {"batch": "a/b"}, {"tag": "x" * 25}, {"q": ""},
                {"q": "x" * 201}]:
        assert client.get("/api/runs", params=bad).status_code == 422, bad


def test_tags_and_notes_are_saved_beside_the_metadata(client, tmp_path):
    runs = tmp_path / "runs"
    directory = fake_run(runs, key(1))
    fake_run(runs, key(2))
    metadata = (directory / "metadata.json").read_bytes()
    response = client.patch(f"/api/runs/{key(1)}", json={"tags": ["Pilot", "left turn", "v-2_a"]})
    assert response.status_code == 200
    item = response.json()
    assert item["key"] == key(1) and item["tags"] == ["Pilot", "left turn", "v-2_a"] and item["notes"] == ""
    assert "trajectory" not in item and item["samples"] == 10
    # Only the fields given change.
    item = client.patch(f"/api/runs/{key(1)}", json={"notes": "Target hidden at 2 s.\nSecond line."}).json()
    assert item["tags"] == ["Pilot", "left turn", "v-2_a"] and item["notes"] == "Target hidden at 2 s.\nSecond line."
    assert json.loads((directory / "annotations.json").read_text()) == {
        "tags": ["Pilot", "left turn", "v-2_a"], "notes": "Target hidden at 2 s.\nSecond line."}
    assert (directory / "metadata.json").read_bytes() == metadata
    assert sorted(p.name for p in directory.iterdir()) == ["annotations.json", "metadata.json"]  # no temporary file
    assert client.get(f"/api/runs/{key(1)}").json()["notes"].startswith("Target hidden")
    tagged = client.get("/api/runs", params={"tag": "pilot"})
    assert tagged.headers["X-Total-Count"] == "1" and keys(tagged) == [key(1)]
    assert keys(client.get("/api/runs", params={"q": "hidden"})) == [key(1)]
    assert client.patch(f"/api/runs/{key(1)}", json={"tags": []}).json()["tags"] == []
    assert client.get("/api/runs", params={"tag": "pilot"}).headers["X-Total-Count"] == "0"
    assert client.patch(f"/api/runs/{key(2)}", json={}).json()["tags"] == []  # nothing to change


def test_annotations_are_validated_and_confined(client, tmp_path):
    runs = tmp_path / "runs"
    fake_run(runs, key(1))
    for body in [{"tags": ["a"] * 1 + ["b;"]}, {"tags": ["x" * 25]}, {"tags": [str(i) for i in range(11)]},
                 {"tags": ["Pilot", "pilot"]}, {"tags": ["  "]}, {"tags": None}, {"notes": "x" * 2001},
                 {"notes": None}, {"tags": "pilot"}, {"colour": "red"}]:
        assert client.patch(f"/api/runs/{key(1)}", json=body).status_code == 422, body
    assert client.patch(f"/api/runs/{key(1)}", json={"tags": [" padded "]}).json()["tags"] == ["padded"]
    assert client.patch(f"/api/runs/{key(1)}", json={"notes": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.patch(f"/api/runs/{key(1)}", content="notes=x",
                        headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    for attempt in [key(9), "..", "..%2Fvictim", key(1).upper(), f"{key(1)}.zip"]:
        assert client.patch(f"/api/runs/{attempt}", json={"notes": "x"}).status_code in {404, 405}, attempt
    # A link named annotations.json is replaced, never written through.
    outside = tmp_path / "outside.json"
    outside.write_text("keep")
    (runs / key(1) / "annotations.json").unlink()
    (runs / key(1) / "annotations.json").symlink_to(outside)
    assert client.get("/api/runs").json()["runs"][0]["notes"] == ""
    assert client.patch(f"/api/runs/{key(1)}", json={"notes": "mine"}).json()["notes"] == "mine"
    assert outside.read_text() == "keep" and not (runs / key(1) / "annotations.json").is_symlink()
    # Unreadable notes never hide the run.
    (runs / key(1) / "annotations.json").write_text("{not json")
    assert client.get("/api/runs").json()["runs"][0]["tags"] == []


def test_annotations_follow_a_rewrite_within_the_same_clock_tick(tmp_path):
    runs = tmp_path / "runs"
    fake_run(runs, key(1))
    for notes in ["a", "b", "c"]:  # same size each time: the listing cache keys on the file's identity
        annotate_run(key(1), RunAnnotations(notes=notes), runs)
        assert list_runs(runs)[0]["notes"] == notes
    with pytest.raises(ValueError):
        annotate_run("../x", RunAnnotations(notes="x"), runs)


def summary_runs(runs, metrics_of, reached=True):
    """Two seeds × three conditions of batch 'cmp', plus a partial trial and another batch."""
    index = 0
    for seed in [1, 2, 3]:
        for condition in ["control", "left_sensor_off", "baseline"]:
            index += 1
            metrics = metrics_of(condition, seed)
            if not reached:
                metrics.pop("min_target_distance_mm")
            fake_run(runs, key(index), trial=trial("cmp", condition, seed, index), metrics=metrics)
    fake_run(runs, key(20), trial=trial("cmp", "control", 4, 10, partial=True), metrics=metrics_of("control", 9))
    fake_run(runs, key(21), trial=trial("other", "control", 1, 1), metrics=metrics_of("control", 1))


def synthetic_metrics(condition, seed):
    shift = {"control": 0, "left_sensor_off": 3, "baseline": -1}[condition]
    return {"target_distance_mm": 10 + shift + seed, "path_length_mm": 20 + 2 * shift + seed * seed,
            "net_turn_deg": 30 * shift - seed, "mean_speed_mm_s": 4 + seed / 10,
            "min_target_distance_mm": 1.5 if (condition == "control" or seed == 1) else 6.0, "protocol_complete": True}


def test_comparison_summary_statistics(client, tmp_path):
    summary_runs(tmp_path / "runs", synthetic_metrics)
    response = client.get("/api/batches/cmp/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "cmp" and data["n_trials"] == 9 and data["partial_trials"] == 1 and data["reach_mm"] == 2
    assert data["duplicate_trials"] == 0
    assert [c["condition"] for c in data["conditions"]] == ["control", "left_sensor_off", "baseline"]
    control = data["conditions"][0]
    assert control["n"] == 3 and set(control["metrics"]) == set(toolkit_metrics()) | {"reached"}
    values = [synthetic_metrics("control", seed)["path_length_mm"] for seed in [1, 2, 3]]
    path = control["metrics"]["path_length_mm"]
    assert path["mean"] == pytest.approx(np.mean(values)) and path["sd"] == pytest.approx(np.std(values, ddof=1))
    assert path["ci95"] == pytest.approx(list(toolkit.bootstrap_interval(values)))
    off = data["conditions"][1]["metrics"]["reached"]
    assert off["mean"] == pytest.approx(1 / 3) and off["ci95"] == pytest.approx(list(toolkit.wilson_interval(1, 3)))
    assert data["conditions"][0]["metrics"]["reached"]["sd"] == 0
    paired = {(p["condition"], p["metric"]): p for p in data["paired"]}
    assert {p["baseline"] for p in data["paired"]} == {"control"} and len(paired) == 2 * 5
    turn = paired[("left_sensor_off", "net_turn_deg")]
    assert turn["n_pairs"] == 3 and turn["mean_diff"] == pytest.approx(90) and turn["ci95"] == pytest.approx([90, 90])
    distance = paired[("baseline", "target_distance_mm")]
    assert distance["mean_diff"] == pytest.approx(-1)
    assert paired[("left_sensor_off", "reached")]["mean_diff"] == pytest.approx(-2 / 3)
    assert "bootstrap" in data["methods"]["means"] and "seed" in data["methods"]["paired"]

    table = client.get("/api/batches/cmp/summary", params={"format": "csv"})
    assert table.status_code == 200 and table.headers["content-type"].startswith("text/csv")
    assert 'filename="comparison-cmp.csv"' in table.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(table.text)))
    assert len(rows) == 3 * 5 + 2 * 5
    row = next(r for r in rows if r["kind"] == "condition" and r["condition"] == "control" and r["metric"] == "path_length_mm")
    assert float(row["mean"]) == pytest.approx(path["mean"]) and float(row["ci95_low"]) == pytest.approx(path["ci95"][0])
    row = next(r for r in rows if r["kind"] == "paired" and r["metric"] == "net_turn_deg" and r["condition"] == "left_sensor_off")
    assert row["baseline"] == "control" and float(row["mean"]) == 90 and row["sd"] == "" and row["n"] == "3"

    assert client.get("/api/batches/nothing/summary").status_code == 404
    assert client.get("/api/batches/a.b/summary").status_code == 404
    assert client.get("/api/batches/cmp/summary", params={"format": "xml"}).status_code == 422


def toolkit_metrics():
    return ["target_distance_mm", "path_length_mm", "net_turn_deg", "mean_speed_mm_s"]


def test_summary_leaves_out_reached_for_older_runs_and_handles_single_trials(tmp_path):
    runs = tmp_path / "runs"
    summary_runs(runs, synthetic_metrics, reached=False)
    data = batch_summary("cmp", runs)
    assert "reached" not in data["conditions"][0]["metrics"] and {p["metric"] for p in data["paired"]} == set(toolkit_metrics())
    single = batch_summary("other", runs)
    assert single["n_trials"] == 1 and single["paired"] == []
    metric = single["conditions"][0]["metrics"]["path_length_mm"]
    assert metric["sd"] is None and metric["ci95"] is None and metric["mean"] == 21
    with pytest.raises(FileNotFoundError):
        batch_summary("missing", runs)


def compare(client, **body):
    """Run a comparison of toy trials at maximum speed and return its finished batch."""
    config = RunConfig(engine="toy", protocol=Protocol(duration_steps=20))
    assert client.post("/api/batch/start", json={"config": config.model_dump(), "max_speed": True, **body}).status_code == 200
    deadline = time.monotonic() + 30
    while (batch := client.get("/api/status").json()["batch"])["status"] != "completed":
        assert time.monotonic() < deadline and batch["status"] == "running", batch
        time.sleep(.05)
    return batch


def test_summary_of_a_real_comparison(client, tmp_path):
    batch = compare(client, seeds=[1, 2], conditions=["control", "left_sensor_off"])
    listed = client.get("/api/runs", params={"batch": batch["id"]})
    assert listed.headers["X-Total-Count"] == "4"
    assert sorted(run["condition"] for run in listed.json()["runs"]) == ["control", "control", "left_sensor_off", "left_sensor_off"]
    data = client.get(f"/api/batches/{batch['id']}/summary").json()
    assert data["n_trials"] == 4 and [c["n"] for c in data["conditions"]] == [2, 2]
    results = {(r["condition"], r["seed"]): r["metrics"] for r in batch["results"]}
    diffs = [results[("left_sensor_off", s)]["net_turn_deg"] - results[("control", s)]["net_turn_deg"] for s in [1, 2]]
    turn = next(p for p in data["paired"] if p["metric"] == "net_turn_deg")
    assert turn["n_pairs"] == 2 and turn["mean_diff"] == pytest.approx(np.mean(diffs))
    reached = [results[("control", s)]["min_target_distance_mm"] <= toolkit.REACH_MM for s in [1, 2]]
    assert data["conditions"][0]["metrics"]["reached"]["mean"] == pytest.approx(np.mean(reached))


def test_summary_of_a_comparison_with_a_custom_condition(client, tmp_path):
    label = 'Eyes off, "both"'  # labels may hold commas and quotes; the CSV quotes them
    batch = compare(client, seeds=[1, 2], conditions=["control"],
                    custom_conditions=[{"label": label, "interventions": {"zero_left": True, "zero_right": True}}])
    custom = [r["key"] for r in client.get("/api/runs", params={"batch": batch["id"]}).json()["runs"] if r["condition"] == label]
    assert len(custom) == 2 and keys(client.get("/api/runs", params={"q": "eyes OFF"})) == custom
    data = client.get(f"/api/batches/{batch['id']}/summary").json()
    assert [c["condition"] for c in data["conditions"]] == ["control", label] and data["n_trials"] == 4
    assert {(p["condition"], p["baseline"]) for p in data["paired"]} == {(label, "control")}
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/batches/{batch['id']}/summary?format=csv").text)))
    assert {row["condition"] for row in rows} == {"control", label}
    assert all(row["baseline"] == "control" for row in rows if row["kind"] == "paired")
