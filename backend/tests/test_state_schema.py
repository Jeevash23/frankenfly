"""The typed State contract: real snapshots match the models and their JSON Schema, and the generated TypeScript
is up to date."""
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import (Batch, ConnectomeLive, Protocol, Provenance, RunConfig, RunMetrics, Sample, State,
    Vision, construct, state_schema)
from digitalfly.main import create_app
from digitalfly.simulation.experiment import Experiment
from digitalfly.simulation.worker import SimulationWorker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = state_schema()


def problems(value, schema, where="state") -> list[str]:
    """Where `value` departs from a JSON Schema as sent: required keys missing, undeclared keys, wrong types."""
    if "$ref" in schema:
        return problems(value, SCHEMA["$defs"][schema["$ref"].rsplit("/", 1)[-1]], where)
    if "anyOf" in schema:
        found = [problems(value, option, where) for option in schema["anyOf"]]
        return [] if [] in found else min(found, key=len)
    if "enum" in schema:
        return [] if value in schema["enum"] else [f"{where}: {value!r} not in {schema['enum']}"]
    kind = schema.get("type")
    checks = {"string": str, "boolean": bool, "null": type(None), "array": list, "object": dict}
    if kind in ("integer", "number"):
        ok = isinstance(value, int if kind == "integer" else (int, float)) and not isinstance(value, bool)
        return [] if ok else [f"{where}: {value!r} is not {kind}"]
    if kind in checks and not isinstance(value, checks[kind]):
        return [f"{where}: {type(value).__name__} is not {kind}"]
    found = []
    if kind == "array":
        for i, item in enumerate(value):
            items = schema["prefixItems"][i] if "prefixItems" in schema else schema.get("items", {})
            found += problems(item, items, f"{where}[{i}]")
    if kind == "object":
        properties = schema.get("properties", {})
        found += [f"{where}.{k} missing" for k in schema.get("required", []) if k not in value]
        extra = schema.get("additionalProperties", True)
        for k, item in value.items():
            if k in properties:
                found += problems(item, properties[k], f"{where}.{k}")
            elif extra is False:
                found.append(f"{where}.{k} not declared")
            elif isinstance(extra, dict):
                found += problems(item, extra, f"{where}.{k}")
    return found


def check(snapshot: dict):
    """A snapshot validates against State, and holds exactly what the JSON Schema says is sent."""
    State.model_validate(snapshot)
    assert problems(snapshot, SCHEMA) == []


@pytest.fixture
def app(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        app.state.client = client
        yield app


def sources(worker):
    """What the worker builds each State part from, checked strictly: a key a model does not declare would be
    dropped from the State by construct()."""
    exp = worker.experiment
    Provenance.model_validate(exp.provenance)
    RunMetrics.model_validate(exp.metrics)
    Vision.model_validate(exp.body.vision)
    if worker.batch is not None:
        Batch.model_validate(worker.batch)
    if exp.connectome_snapshot() is not None:
        ConnectomeLive.model_validate(exp.connectome_snapshot())


def wait(client, condition, seconds=30):
    deadline = time.monotonic() + seconds
    while not condition(state := client.get("/api/status").json()):
        assert time.monotonic() < deadline, state
        time.sleep(.05)
    return state


def test_engineered_snapshots_match_the_schema(app):
    client, worker = app.state.client, app.state.worker
    check(client.get("/api/status").json())
    client.post("/api/stimulus", json={"x": 3, "y": -4})
    for _ in range(3):
        client.post("/api/step", json={})
    state = client.get("/api/status").json()
    assert state["metrics"]["min_target_distance_mm"] > 0 and state["vision"] == {} and state["batch"] is None
    check(state)
    sources(worker)
    assert client.get("/api/schema/state").json() == SCHEMA


def test_connectome_comparison_snapshots_match_the_schema(app):
    client, worker = app.state.client, app.state.worker
    config = RunConfig(engine="toy", neural_model="connectome", protocol=Protocol(duration_steps=15))
    assert client.post("/api/reset", json=config.model_dump()).status_code == 200
    body = {"config": config.model_dump(), "seeds": [1, 2], "conditions": ["control", "dna02_both_off"], "max_speed": True}
    assert client.post("/api/batch/start", json=body).status_code == 200
    check(client.get("/api/status").json())  # running, with the connectome block
    state = wait(client, lambda s: s["batch"]["status"] == "completed")
    assert len(state["batch"]["results"]) == 4 and state["connectome"]["top_types"]
    check(state)
    sources(worker)
    # A cancelled comparison carries its unfinished trial, marked partial.
    slow = {**body, "config": {**body["config"], "protocol": {"duration_steps": 3000}}, "seeds": [1], "max_speed": False}
    assert client.post("/api/batch/start", json=slow).status_code == 200
    wait(client, lambda s: s["sample"]["step"] > 2)
    assert client.post("/api/batch/cancel", json={}).status_code == 200
    state = client.get("/api/status").json()
    assert state["batch"]["status"] == "cancelled" and state["batch"]["partial"]["partial"] is True
    check(state)
    sources(worker)


def test_construct_builds_nested_models_without_validation_or_warnings():
    batch = {"id": "a1", "status": "running", "total": 1, "current": 1, "protocol": "p", "cell_type": None,
             "max_speed": False, "results": [{"batch_id": "a1", "condition": "control", "seed": 1, "index": 1,
             "total": 1, "cell_type": None, "run_id": "r", "samples": 2, "path": "p", "download_url": "d",
             "metrics": {"duration_s": .01}}], "undeclared": 1}
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        built = construct(Batch, batch)
        dumped = built.model_dump()
    assert isinstance(built.results[0].metrics, RunMetrics) and "undeclared" not in dumped
    assert dumped["results"][0]["metrics"] == {"duration_s": .01}  # absent metrics are left out, not null
    assert "condition" not in dumped and "error" not in dumped
    assert construct(Batch, None) is None


def test_generated_typescript_is_up_to_date():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/gen_types.py"), "--check"], capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    text = (ROOT / "frontend/src/api.gen.ts").read_text()
    assert text.startswith("// generated by scripts/gen_types.py — do not edit")
    for name in ["State", "Batch", "ConnectomeLive", "RunMetrics", "Vision", "RunItem", "BatchSummary", "RunAnnotations"]:
        assert f"export interface {name} {{" in text, name


@pytest.mark.flygym
@pytest.mark.render
def test_flygym_vision_snapshots_match_the_schema():
    exp = Experiment(RunConfig(sensor_model="vision"), render=False)
    try:
        assert exp.status == "paused", exp.error
        for _ in range(6):
            exp.advance()
        Vision.model_validate(exp.body.vision)
        Sample.model_validate(exp.sample.model_dump())
        worker = SimulationWorker(exp.config, render=False)  # never started: only its publishing is used
        worker.experiment = exp
        worker._publish()
        check(worker.snapshot)
        assert worker.snapshot["vision"]["ommatidia_per_eye"] == 721
        assert len(worker.snapshot["sample"]["body_signals"]["joint_position_rad"]) > 40
        assert "joint_position_rad" not in worker.snapshot["history"][-1]["body_signals"]
    finally:
        exp.close()
