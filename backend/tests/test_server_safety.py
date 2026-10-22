"""Request limits, status codes, file writes and races at the API's edges, and the launcher's and doctor's probes."""
import asyncio
import errno
import http.server
import importlib.util
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from digitalfly import toolkit
from digitalfly.api.models import (CONFIG_SIZE_LIMIT, LIVE_CONNECTOME_FIELDS, SERVING_REQUEST, BatchRequest, Pose,
                                   RunConfig, reads_files_later)
from digitalfly.data import jobs, presets, research
from digitalfly.data.research import RunItem, delete_run, list_runs
from digitalfly.main import create_app
from digitalfly.neural.connectome import load_circuit
from digitalfly.simulation.engines import ToyBody
from test_run_library_extras import fake_run, key

ROOT = Path(__file__).resolve().parents[2]
CONNECTOME = {**RunConfig(engine="toy").model_dump(), "neural_model": "connectome"}


@pytest.fixture
def configs(tmp_path, monkeypatch):
    folder = tmp_path / "configs"
    folder.mkdir()
    monkeypatch.setattr(presets, "CONFIG_DIR", folder)
    return folder


@pytest.fixture
def client(configs, tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Request sizes: a configuration that can be saved as a preset can be applied and compared.

def largest_config(circuit="fafb783-dna02"):
    """The largest configuration the circuit allows: every list at its maximum, filled with its longest type names."""
    data = load_circuit(circuit)
    names = sorted((name for name in data.type_names if name != "DNa02"), key=lambda name: (-len(name), name))
    both = [name for name in names if len(data.members(name, "left")) and len(data.members(name, "right"))]
    interventions = {"zero_left": True, "silence_dna02": "both", "silence_types": names[:32],
                     "cell_types": [{"name": name, "mode": "scale", "value": .123456789} for name in names[32:64]]}
    parameters = {"circuit": circuit, "readout_types": both[:8], "input_types": both[8:40], "speed_types": names[64:72],
                  "readout_weights": {name: -1.23456789 for name in both[:8]}}
    stimulus = {"x": -12.3456789, "y": 8.7654321, "intensity": 1.23456789}
    events = [{"step": 100 + i, "stimulus": stimulus, "interventions": interventions} for i in range(64)]
    return {**CONNECTOME, "connectome_parameters": parameters, "initial_interventions": interventions,
            "protocol": {"name": "P" * 80, "duration_steps": 1000, "events": events}}


def largest_batch(config):
    stimuli = [{"step": i, "stimulus": event["stimulus"]} for i, event in enumerate(config["protocol"]["events"])]
    live = {name: value for name, value in config["connectome_parameters"].items() if name in LIVE_CONNECTOME_FIELDS}
    custom = [{"label": f"Condition {k} ".ljust(40, "x"), "interventions": config["initial_interventions"],
               "connectome_parameters": {**live, "global_gain": .00123456789}} for k in range(6)]
    return {"config": {**config, "protocol": {**config["protocol"], "events": stimuli}}, "seeds": [1, 2, 3, 4, 5],
            "conditions": [], "custom_conditions": custom}


def test_the_largest_valid_configuration_saves_applies_and_compares(client):
    config = largest_config()
    assert len(json.dumps(config)) > 65536  # the former preset limit, four times the former reset limit
    saved = client.post("/api/configs", json={"name": "largest", "description": "D" * 200, "config": config})
    assert saved.status_code == 201, saved.text
    loaded = client.get("/api/configs/largest").json()["config"]
    reset = client.post("/api/reset", json=loaded)
    assert reset.status_code == 200, reset.text
    assert reset.json()["config"] == loaded and reset.json()["status"] == "paused"
    batch = largest_batch(loaded)
    assert len(json.dumps(batch)) > 16384  # the former comparison limit
    started = client.post("/api/batch/start", json=batch)
    assert started.status_code == 200, started.text
    assert started.json()["batch"]["total"] == 30
    assert client.post("/api/batch/cancel", json={}).json()["batch"]["status"] == "cancelled"


def schema_valid(model, data):
    """Validated as a request body is on the API's event loop: the schema in full, no circuit file read."""
    async def validate():
        token = SERVING_REQUEST.set(True)
        try:
            assert reads_files_later()
            return model.model_validate(data)
        finally:
            SERVING_REQUEST.reset(token)
    return asyncio.run(validate())


def test_the_size_limit_holds_the_largest_configuration_the_schema_allows(client):
    def names(prefix, n):
        return [f"{prefix}{i:03d}".ljust(120, "x") for i in range(n)]
    long_float = -0.12345678901234567
    interventions = {"silence_dna02": "both", "silence_types": names("s", 32),
                     "cell_types": [{"name": name, "side": "right", "mode": "activate", "value": .12345678901234567}
                                    for name in names("c", 32)]}
    readout = names("r", 8)
    parameters = {"circuit": "c" * 64, "dynamics": "spiking", "synapse_threshold": 1000, "readout_types": readout,
                  "input_types": names("i", 32), "speed_types": names("v", 8),
                  "readout_weights": dict.fromkeys(readout, long_float * 10)}
    stimulus = {"x": long_float * 100, "y": long_float * 100, "intensity": -long_float}
    config = {**CONNECTOME, "seed": 2147483647, "stimulus": stimulus, "connectome_parameters": parameters,
              "initial_interventions": interventions,
              "protocol": {"name": "P" * 80, "duration_steps": 29999,
                           "events": [{"step": 29900 + i, "stimulus": stimulus, "interventions": interventions}
                                      for i in range(64)]}}
    dumped = schema_valid(RunConfig, config).model_dump()
    preset = json.dumps({"name": "n" * 48, "description": "d" * 200, "config": dumped}, indent=2) + "\n"
    assert len(json.dumps(dumped)) < CONFIG_SIZE_LIMIT and len(preset.encode()) <= presets.SIZE_LIMIT
    batch = largest_batch({**dumped, "protocol": {**dumped["protocol"], "duration_steps": 1000}})
    assert len(json.dumps(schema_valid(BatchRequest, batch).model_dump())) < CONFIG_SIZE_LIMIT
    # Beyond it, and beyond 16 KB for every other command: refused before anything is parsed.
    headers = {"content-type": "application/json"}
    for path in ["/api/reset", "/api/batch/start", "/api/configs"]:
        assert client.post(path, content=" " * (CONFIG_SIZE_LIMIT + 1), headers=headers).status_code == 413
    assert client.post("/api/stimulus", content=" " * 16385, headers=headers).status_code == 413


# Presets: saving where it cannot be done, and never through a link.

def test_presets_that_cannot_be_saved_answer_503_and_capabilities_say_so(client, configs):
    assert client.get("/api/capabilities").json()["presets"] == {"available": True, "writable": True}
    (configs / "local").write_text("")  # as unwritable as a root-owned folder is to the container's user
    assert not presets.writable()
    assert client.get("/api/capabilities").json()["presets"] == {"available": True, "writable": False}
    refused = client.post("/api/configs", json={"name": "mine", "config": RunConfig(engine="toy").model_dump()})
    assert refused.status_code == 503 and "Presets cannot be saved" in refused.json()["detail"]
    assert "/app/configs/local" in refused.json()["detail"] and client.get("/api/configs").status_code == 200


def test_a_preset_is_never_written_through_a_link(client, configs, tmp_path):
    local, outside = configs / "local", tmp_path / "outside.txt"
    local.mkdir()
    outside.write_text("keep")
    (local / f".mine.json.{os.getpid()}.part").symlink_to(outside)  # where a predictable partial file would be
    saved = client.post("/api/configs", json={"name": "mine", "config": RunConfig(engine="toy").model_dump()})
    assert saved.status_code == 201 and outside.read_text() == "keep"
    path = local / "mine.json"
    assert path.is_file() and not path.is_symlink() and json.loads(path.read_text())["name"] == "mine"
    assert not [p for p in local.iterdir() if not p.is_symlink() and p != path]  # no partial file left behind


# Status codes: the same invalid input is 422 whether it comes with a reset or while the run goes on.

def test_invalid_interventions_and_parameters_are_422_live_as_at_a_reset(client):
    assert client.post("/api/reset", json=CONNECTOME).status_code == 200
    parameters = client.get("/api/status").json()["config"]["connectome_parameters"]
    weights = {**parameters, "readout_weights": {"AN_GNG_109": 1.0}}  # not a readout type
    live = client.post("/api/connectome/parameters", json=weights)
    assert live.status_code == 422 and "not read out" in live.json()["detail"]
    assert client.post("/api/reset", json={**CONNECTOME, "connectome_parameters": weights}).status_code == 422
    for interventions in [{"silence": "sensory"}, {"cell_types": [{"name": "NotAType", "mode": "silence"}]}]:
        assert client.post("/api/interventions", json=interventions).status_code == 422
        assert client.post("/api/reset", json={**CONNECTOME, "initial_interventions": interventions}).status_code == 422
    # What the running experiment cannot change without a reset stays a conflict.
    assert client.post("/api/connectome/parameters", json={**parameters, "dynamics": "spiking"}).status_code == 409
    assert client.post("/api/reset", json=RunConfig(engine="toy").model_dump()).status_code == 200
    assert client.post("/api/interventions", json={"silence_dna02": "both"}).status_code == 422
    assert client.post("/api/connectome/parameters", json=parameters).status_code == 409


def test_invalid_data_from_the_run_is_not_reported_as_an_invalid_request(client, monkeypatch):
    def diverged(self, legs=True):
        return Pose(x=math.nan, y=0, z=0, yaw=0, velocity=0)
    monkeypatch.setattr(ToyBody, "pose", diverged)
    response = client.post("/api/step", json={})
    assert response.status_code == 500 and "invalid data" in response.json()["detail"], response.text
    assert client.get("/api/status").json()["status"] == "error"
    assert client.post("/api/stimulus", json={"x": 99}).json()["detail"][0]["location"] == ["body", "x"]


def test_configurations_are_checked_in_full_inside_any_other_event_loop():
    missing = {**CONNECTOME, "connectome_parameters": {"circuit": "no-such-circuit"}}

    async def notebook_cell():  # a Jupyter cell runs inside the kernel's event loop
        assert not reads_files_later()
        with pytest.raises(ValidationError, match="no-such-circuit"):
            toolkit.configure(missing)
    asyncio.run(notebook_cell())


# Saved runs: replay verdicts as the API declares them, and deletions racing other work on the run.

def test_replay_verdicts_match_the_declared_model(tmp_path):
    replay = load_script("replay")
    runs = tmp_path / "runs"
    directory = fake_run(runs, key(1))
    report = {"passed": True, "maximum_absolute_error": 0., "tolerance": 1e-8, "message": "Replayed 10 samples",
              "samples": 10, "column_errors": {"x_mm": 0., "rate_dna02": None}}
    replay.save_verdict(directory, replay.verdict(report, {}))
    entry = list_runs(runs)[0]
    assert entry["verified"]["samples_compared"] == 10 and entry["verified"]["software_differences"]
    assert RunItem.model_validate(entry).verified.column_errors == {"x_mm": 0., "rate_dna02": None}
    older = {k: entry["verified"][k] for k in ["ok", "max_abs_error", "tolerance", "checked", "same_software", "message"]}
    (directory / "replay.json").write_text(json.dumps({**older, "future_field": 1}))
    assert RunItem.model_validate(list_runs(runs)[0]).verified.samples_compared is None
    schema = create_app(RunConfig(engine="toy"), render=False).openapi()["components"]["schemas"]["ReplayVerdict"]
    assert {"samples_compared", "column_errors", "software_differences"} <= set(schema["properties"])


def test_a_run_cannot_be_deleted_while_a_replay_of_it_waits_or_runs(client, tmp_path):
    fake_run(tmp_path / "runs", key(1))
    manager = client.app.state.jobs
    job = manager.submit("replay", "Replay", [sys.executable, "-c", "import time; time.sleep(60)"], target=key(1))
    refused = client.delete(f"/api/runs/{key(1)}")
    assert refused.status_code == 409 and "replay" in refused.json()["detail"]
    assert (tmp_path / "runs" / key(1)).is_dir()
    assert client.post(f"/api/jobs/{job.id}/cancel", json={}).json()["job"]["status"] == "cancelled"
    assert client.delete(f"/api/runs/{key(1)}").json() == {"deleted": key(1)}


def test_a_run_is_not_deleted_while_its_notes_are_written(tmp_path):
    runs = tmp_path / "runs"
    fake_run(runs, key(1))
    with research._annotating:
        deletion = threading.Thread(target=delete_run, args=(key(1), runs))
        deletion.start()
        deletion.join(.3)
        assert deletion.is_alive() and (runs / key(1)).is_dir()
    deletion.join(10)
    assert not (runs / key(1)).exists()


def test_notes_on_a_run_deleted_meanwhile_answer_404(client, tmp_path, monkeypatch):
    fake_run(tmp_path / "runs", key(1))
    real = research._run_directory

    def deleted_after_the_check(name, root):
        directory = real(name, root)
        shutil.rmtree(directory)
        return directory
    monkeypatch.setattr(research, "_run_directory", deleted_after_the_check)
    assert client.patch(f"/api/runs/{key(1)}", json={"notes": "late"}).status_code == 404


def test_cancelling_a_job_whose_process_has_exited_leaves_its_result(monkeypatch):
    signals = []
    monkeypatch.setattr(jobs.os, "killpg", lambda pid, number: signals.append((pid, number)))
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()  # exited and reaped: its id may belong to another process by now
    manager = jobs.JobManager()
    job = jobs.Job("replay", "Replay", [])
    job.status, job.process, job.thread = "running", process, threading.Thread(target=lambda: None)
    job.thread.start()
    manager.jobs.append(job)
    manager.cancel(job.id)
    assert not job.cancel_requested and signals == []
    jobs._terminate([process])
    assert signals == []


# The launcher and the doctor.

def test_the_launcher_treats_ipv6_loopback_as_a_network_address():
    env = {k: v for k, v in os.environ.items() if k not in {"DIGITALFLY_ALLOW_NETWORK_BIND", "DIGITALFLY_HOST"}}
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    try:  # held, so a launcher that accepted ::1 stops at once instead of serving
        held = socket.socket(socket.AF_INET6)
        held.bind(("::1", port))
        held.listen()
    except OSError:
        held = None
    try:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/launch.py"), "--toy", "--dev", "--port", str(port),
                                 "--host", "::1"], env=env, capture_output=True, text=True, timeout=60)
    finally:
        if held is not None:
            held.close()
    assert result.returncode == 1 and "DIGITALFLY_ALLOW_NETWORK_BIND=1" in result.stderr, result
    assert "Traceback" not in result.stderr


def test_the_launcher_explains_an_address_it_cannot_use(monkeypatch):
    launch = load_script("launch")
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert "is occupied" in launch.address_problem("127.0.0.1", port)
    assert launch.address_problem("127.0.0.1", port) is None

    real = socket.socket

    def no_ipv6(family=socket.AF_INET, *args):
        if family == socket.AF_INET6:
            raise OSError(errno.EAFNOSUPPORT, "Address family not supported by protocol")
        return real(family, *args)
    monkeypatch.setattr(launch.socket, "socket", no_ipv6)
    problem = launch.address_problem("fe80::1", 8000)
    assert problem.startswith("Cannot listen on fe80::1 port 8000: Address family not supported") and "--host" in problem


def test_the_doctor_reaches_the_local_server_past_a_configured_proxy(monkeypatch, capsys):
    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"service": "DigitalFly"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ["no_proxy", "NO_PROXY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")  # nothing listens there
    monkeypatch.setattr(urllib.request, "_opener", None)
    try:
        doctor = load_script("doctor")
        doctor.check_port(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
    assert "in use by a running DigitalFly server" in capsys.readouterr().out


def test_the_doctor_names_data_folders_it_cannot_write(tmp_path, monkeypatch, capsys):
    doctor = load_script("doctor")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    doctor.check_writable()
    assert "[ ok ] Data folders" in capsys.readouterr().out
    (tmp_path / "configs").write_text("")  # configs/local cannot be made
    doctor.check_writable()
    out = capsys.readouterr().out
    assert "[warn] Data folders" in out and "cannot write configs/local:" in out and doctor.failures == []
