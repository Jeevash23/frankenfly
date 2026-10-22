"""Background jobs: one process per job in its own session, queued per kind and cancellable; replay checks of saved
runs through the API; leftovers of interrupted work removed at startup."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import psutil
import pytest
from fastapi.testclient import TestClient
from digitalfly import toolkit
from digitalfly.api.models import RunConfig, Stimulus
from digitalfly.data import jobs as background
from digitalfly.data.jobs import JobManager, remove_leftovers
from digitalfly.main import create_app
from digitalfly.simulation import experiment
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("replay", ROOT / "scripts/replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)
FINISHED = ("done", "failed", "cancelled")


def python(code):
    return [sys.executable, "-c", code]


def until(condition, timeout=60):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(.02)
    assert condition()


def finished(manager, job, timeout=60):
    until(lambda: manager.describe(job)["status"] in FINISHED, timeout)
    return manager.describe(job)


def toy_run(runs: Path, steps=40, **settings) -> Path:
    config = toolkit.configure({"engine": "toy", "seed": 5, **settings}, stimulus=toolkit.target(30, 10))
    exp = Experiment(config, render=False)
    try:
        for i in range(steps):
            if i == 20:
                exp.set_stimulus(Stimulus(x=-5, y=9))
            exp.advance()
        return Path(exp.export(runs)["path"])
    finally:
        exp.close()


def test_jobs_of_one_kind_queue_while_other_kinds_run(tmp_path):
    manager = JobManager()
    gate = tmp_path / "gate"
    try:
        first = manager.submit("replay", "first", python(
            f"import pathlib, time\nprint('@progress 0.5', flush=True)\n"
            f"while not pathlib.Path({str(gate)!r}).exists(): time.sleep(.02)\nprint('{{\"ok\": true}}')"),
            finish=background.verdict_result)
        second = manager.submit("replay", "second", python("print('{\"ok\": false}')"), finish=background.verdict_result)
        build = manager.submit("build", "build", python("print('selecting'); print('{\"neurons\": 3}')"))
        state = finished(manager, build)  # while the first replay still runs
        assert state["status"] == "done" and state["result"] == {"neurons": 3}
        assert state["log_tail"] == ["selecting", '{"neurons": 3}'] and state["progress"] == 1
        until(lambda: manager.describe(first)["progress"] == .5)
        assert manager.describe(first)["status"] == "running" and manager.describe(first)["log_tail"] == []
        assert manager.describe(second)["status"] == "queued" and manager.describe(second)["started"] is None
        gate.write_text("")
        assert finished(manager, second)["result"] == {"ok": False}  # a verdict, passed or not, completes the job
        state = manager.describe(first)
        assert state["status"] == "done" and state["result"] == {"ok": True} and state["progress"] == 1
        assert state["created"] <= state["started"] <= state["finished"]
        assert [job["label"] for job in manager.listing()] == ["build", "second", "first"]
        failing = manager.submit("build", "broken", python("import sys; print('step one'); sys.exit('the build broke')"))
        state = finished(manager, failing)
        assert state["status"] == "failed" and state["error"] == "the build broke" and state["result"] is None
        silent = manager.submit("replay", "silent", python("print('no verdict')"), finish=background.verdict_result)
        assert finished(manager, silent)["error"] == "The replay finished without a verdict."
        manager.submit("replay", "once", python("import time; time.sleep(5)"), target="run", duplicate="already")
        with pytest.raises(ValueError, match="already"):
            manager.submit("replay", "twice", python("pass"), target="run", duplicate="already")
        with pytest.raises(ValueError, match="busy"):
            manager.submit("replay", "exclusive", python("pass"), busy="busy")
    finally:
        manager.close()


def test_cancel_terminates_the_whole_process_group_and_drops_waiting_jobs(tmp_path):
    manager = JobManager()
    pid_file = tmp_path / "grandchild"
    script = (f"import pathlib, subprocess, sys, time\n"
              f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\nprint('started', flush=True)\ntime.sleep(60)")
    try:
        running = manager.submit("replay", "slow", python(script))
        waiting = manager.submit("replay", "next", python("print(1)"))
        until(lambda: pid_file.is_file() and pid_file.read_text() and running.lines)
        grandchild = int(pid_file.read_text())
        state = manager.cancel(waiting.id)
        assert state["status"] == "cancelled" and state["started"] is None
        started = time.monotonic()
        state = manager.cancel(running.id)
        assert time.monotonic() - started < background.STOP_TIMEOUT
        assert state["status"] == "cancelled" and state["error"] == "Cancelled." and state["log_tail"] == ["started"]
        gone = lambda: not psutil.pid_exists(grandchild) or psutil.Process(grandchild).status() == psutil.STATUS_ZOMBIE
        until(gone, timeout=5)
        assert manager.cancel(running.id) == state  # finished: left as it is
        assert manager.describe(waiting)["status"] == "cancelled"
        with pytest.raises(KeyError):
            manager.cancel("unknown")
    finally:
        manager.close()


def test_logs_and_the_job_list_are_bounded_and_close_stops_every_job(monkeypatch):
    monkeypatch.setattr(background, "KEEP", 3)
    manager = JobManager()
    noisy = manager.submit("build", "noisy", python("for i in range(500): print(i)"))
    assert finished(manager, noisy)["log_tail"] == [str(i) for i in range(300, 500)]
    for i in range(4):
        finished(manager, manager.submit("build", str(i), python("pass")))
    assert [job["label"] for job in manager.listing()] == ["3", "2", "1"]
    for i in range(background.QUEUE_LIMIT + 1):
        manager.submit("replay", f"slow {i}", python("import time; time.sleep(60)"))
    with pytest.raises(ValueError, match="waiting"):
        manager.submit("replay", "one too many", python("pass"))
    started = time.monotonic()
    manager.close()
    assert time.monotonic() - started < background.STOP_TIMEOUT
    assert all(job["status"] == "cancelled" for job in manager.listing() if job["label"].startswith("slow"))
    with pytest.raises(RuntimeError, match="shutting down"):
        manager.submit("build", "late", python("pass"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def follow(client, job):
    deadline = time.monotonic() + 120
    while job["status"] not in FINISHED and time.monotonic() < deadline:
        time.sleep(.05)
        job = next(j for j in client.get("/api/jobs").json()["jobs"] if j["id"] == job["id"])
    return job


def replay_through_the_api(client, key):
    response = client.post(f"/api/runs/{key}/replay", json={})
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    assert job["kind"] == "replay" and job["target"] == key and job["label"] == f"Replay {key}"
    return follow(client, job)


def edit_cell(run: Path, row: int, column: str, value: str):
    lines = (run / "telemetry.csv").read_text().splitlines()
    index = lines[0].split(",").index(column)
    cells = lines[row + 1].split(",")
    cells[index] = value(cells[index]) if callable(value) else value
    lines[row + 1] = ",".join(cells)
    (run / "telemetry.csv").write_text("\n".join(lines) + "\n")


def test_replay_jobs_verify_saved_runs_and_catch_a_damaged_recording(client, tmp_path):
    run = toy_run(tmp_path / "runs")
    key = run.name
    assert client.get("/api/runs").json()["runs"][0]["verified"] is None
    assert client.post(f"/api/runs/{key}/replay", json={"extra": 1}).status_code == 422
    for missing in ["20260101T000000-00000000-000000", "not-a-run"]:
        assert client.post(f"/api/runs/{missing}/replay", json={}).status_code == 404
    response = client.post(f"/api/runs/{key}/replay", json={})
    assert response.status_code == 202 and response.json()["job"]["status"] in ("queued", "running")
    assert client.post(f"/api/runs/{key}/replay", json={}).status_code == 409  # one check of a run at a time
    job = follow(client, response.json()["job"])
    assert job["status"] == "done" and job["error"] is None and job["progress"] == 1, job
    assert job["result"]["ok"] and job["result"]["samples_compared"] == 41
    verified = client.get("/api/runs").json()["runs"][0]["verified"]
    assert verified == json.loads((run / "replay.json").read_text()) == job["result"]
    assert verified["max_abs_error"] == 0 and verified["tolerance"] == 1e-8 and verified["same_software"]
    assert verified["message"] == "Replayed 41 samples: maximum absolute error 0, within the tolerance 1e-08."
    assert verified["checked"] > job["created"] and client.get(f"/api/runs/{key}").json()["verified"] == verified
    assert not list(run.glob(".replay*"))
    # A damaged recording no longer verifies, and the verdict says where.
    edit_cell(run, 10, "x_mm", lambda value: repr(float(value) + .5))
    job = replay_through_the_api(client, key)
    assert job["status"] == "done" and job["result"]["ok"] is False
    verified = client.get("/api/runs").json()["runs"][0]["verified"]
    assert verified["ok"] is False and verified["message"].startswith("x_mm differs by 0.5 at step 10 (recorded ")
    assert verified["max_abs_error"] == pytest.approx(.5) and verified["column_errors"]["y_mm"] == 0
    # A value that is not a number never matches (scripts/replay.py used to skip it and pass).
    edit_cell(run, 10, "x_mm", "nan")
    verified = replay_through_the_api(client, key)["result"]
    assert not verified["ok"] and verified["message"] == "x_mm at step 10 is not a number in telemetry.csv."
    assert verified["max_abs_error"] == 0 and verified["column_errors"]["x_mm"] is None
    detail = client.get(f"/api/runs/{key}").json()  # the damaged row is left out of the trajectory, not a server error
    assert detail["verified"] == verified and len(detail["trajectory"]) == 40
    # Missing rows, and a file that cannot be read at all.
    lines = (run / "telemetry.csv").read_text().splitlines()
    (run / "telemetry.csv").write_text("\n".join(lines[:5] + lines[12:30]) + "\n")
    verified = replay_through_the_api(client, key)["result"]
    assert not verified["ok"] and verified["message"].startswith("telemetry.csv has 22 rows, but the run recorded 41")
    (run / "telemetry.csv").write_text(lines[0] + "\n1,2\n")
    verified = replay_through_the_api(client, key)["result"]
    assert not verified["ok"] and verified["message"].startswith("telemetry.csv is unreadable") and verified["samples_compared"] == 0
    assert client.get(f"/api/runs/{key}").json()["verified"] == verified
    # Cancelling a finished job changes nothing; unknown jobs are not found.
    finished_job = client.get("/api/jobs").json()["jobs"][0]
    assert client.post(f"/api/jobs/{finished_job['id']}/cancel", json={}).json()["job"] == finished_job
    assert client.post("/api/jobs/unknown/cancel", json={}).status_code == 404


def test_a_replay_that_cannot_run_fails_the_job_and_keeps_the_last_verdict(client, tmp_path):
    run = toy_run(tmp_path / "runs", neural_model="connectome")
    key = run.name
    assert replay_through_the_api(client, key)["result"]["ok"]
    before = client.get(f"/api/runs/{key}").json()["verified"]
    metadata = json.loads((run / "metadata.json").read_text())
    metadata["neural"]["circuit_sha256"] = "0" * 64  # as if the run had used an earlier build of its circuit
    (run / "metadata.json").write_text(json.dumps(metadata))
    job = replay_through_the_api(client, key)
    assert job["status"] == "failed" and job["result"] is None
    assert "fafb783-dna02 circuit has changed" in job["error"] and job["log_tail"][-1] == job["error"]
    assert client.get(f"/api/runs/{key}").json()["verified"] == before


def test_builds_are_jobs_and_a_cancelled_build_frees_its_circuit(client, tmp_path, monkeypatch):
    from digitalfly.data import builds
    monkeypatch.setattr(builds, "PREPARED", tmp_path / "prepared.npz")
    builds.PREPARED.write_bytes(b"")
    monkeypatch.setattr(builds.BuildManager, "command",
                        staticmethod(lambda request: python("print('selecting', flush=True); import time; time.sleep(60)")))
    started = client.post("/api/connectome/build", json={"name": "my-circuit", "seeds": ["DNx"]}).json()
    assert started["status"] == "running" and started["name"] == "my-circuit" and isinstance(started["started"], float)
    job = client.get("/api/jobs").json()["jobs"][0]
    assert job["kind"] == "build" and job["target"] == "my-circuit" and job["status"] == "running"
    body = {"engine": "toy", "neural_model": "connectome", "connectome_parameters": {"circuit": "my-circuit"}}
    assert "being built" in client.post("/api/reset", json=body).json()["detail"]
    until(lambda: client.get("/api/connectome/build").json()["log"] == ["selecting"])
    cancelled = client.post(f"/api/jobs/{job['id']}/cancel", json={}).json()["job"]
    assert cancelled["status"] == "cancelled" and cancelled["log_tail"] == ["selecting"]
    status = client.get("/api/connectome/build").json()
    assert status["status"] == "failed" and status["exit_code"] == -15 and status["result"] is None
    assert "being built" not in client.post("/api/reset", json=body).json()["detail"]  # now: no such circuit


def test_software_differences_name_what_changed():
    run_metadata = {"python": "3.0.0", "dependencies": {**experiment.dependency_versions(), "numpy": "0.0"},
                    "lockfiles": {"requirements.lock": "0" * 64, "requirements-old.lock": "1" * 64}}
    differences = replay.software_differences(run_metadata)
    assert differences[0].startswith("Python 3.0.0 → ") and f"numpy 0.0 → {experiment.dependency_versions()['numpy']}" in differences
    assert "requirements.lock changed" in differences and "requirements-old.lock removed" in differences
    assert "the run recorded no lockfile hashes" in replay.software_differences({})
    report = {"passed": True, "maximum_absolute_error": 0., "tolerance": 1e-8, "message": "Replayed 3 samples",
              "samples": 3, "column_errors": {"x_mm": 0.}}
    verdict = replay.verdict(report, run_metadata)
    assert verdict["ok"] and not verdict["same_software"] and "The software differs from the recording's: Python" in verdict["message"]


def test_replay_environment_passes_the_servers_opengl_choice(monkeypatch):
    monkeypatch.delenv("MUJOCO_GL", raising=False)
    monkeypatch.setattr("digitalfly.simulation.engines.select_gl", lambda: "egl")
    assert background.replay_environment("flygym")["MUJOCO_GL"] == "egl"
    assert "MUJOCO_GL" not in background.replay_environment("toy")  # no OpenGL question for the toy body
    monkeypatch.setattr("digitalfly.simulation.engines.select_gl", lambda: None)
    assert "MUJOCO_GL" not in background.replay_environment("flygym")


def test_capabilities_report_the_eye_renderer_jobs_and_presets(client, monkeypatch):
    monkeypatch.setattr("digitalfly.main.select_gl", lambda: None)
    capabilities = client.get("/api/capabilities").json()
    assert capabilities["compound_eye_sensor"] is False
    assert capabilities["jobs"] == {"available": True, "kinds": ["build", "replay"]} and capabilities["presets"]["available"]
    monkeypatch.setattr("digitalfly.main.select_gl", lambda: "glfw")
    assert client.get("/api/capabilities").json()["compound_eye_sensor"] is True


def test_leftovers_of_interrupted_work_are_removed_once_old(tmp_path, monkeypatch):
    runs, local = tmp_path / "runs", tmp_path / "data/circuits/local"
    run = runs / "20260101T120000-00000000-abcdef"
    for folder in [runs / ".tmp-a/inner", runs / ".deleting-b", run, local]:
        folder.mkdir(parents=True)
    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait()
    files = {runs / ".tmp-a.zip": "x", run / "metadata.json": "{}", run / ".replay.json.1.part": "x",
             local / f".gone.json.{exited.pid}.part": "x", local / f".writing.json.{os.getpid()}.part": "x",
             local / "kept.json": "{}", local / ".notes.part": "x"}
    for path, text in files.items():
        path.write_text(text)
    assert remove_leftovers(tmp_path) == []  # younger than an hour
    removed = remove_leftovers(tmp_path, age_s=-60)
    assert sorted(removed) == sorted(["runs/.tmp-a", "runs/.tmp-a.zip", "runs/.deleting-b",
                                      f"runs/{run.name}/.replay.json.1.part", f"data/circuits/local/.gone.json.{exited.pid}.part",
                                      "data/circuits/local/.notes.part"])
    assert (run / "metadata.json").is_file() and (local / "kept.json").is_file()
    assert (local / f".writing.json.{os.getpid()}.part").is_file()  # its builder is still running
    # The server does this when it starts.
    (runs / ".tmp-c").mkdir()
    monkeypatch.setattr(background, "LEFTOVER_AGE_S", -60)
    monkeypatch.setattr("digitalfly.main.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000"):
        assert app.state.removed_leftovers == ["runs/.tmp-c"] and not (runs / ".tmp-c").exists()


@pytest.mark.flygym
def test_a_replay_job_verifies_a_flygym_run_with_the_servers_opengl_backend(tmp_path):
    exp = Experiment(RunConfig(engine="flygym", seed=2), render=False)
    try:
        assert exp.status == "paused", exp.error
        for i in range(15):
            if i == 8:
                exp.set_stimulus(Stimulus(x=4, y=-6))
            exp.advance()
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    manager = JobManager()
    try:
        state = finished(manager, background.submit_replay(manager, run), timeout=300)
    finally:
        manager.close()
    assert state["status"] == "done" and state["result"]["ok"] and state["result"]["max_abs_error"] == 0, state
    assert state["result"]["same_software"] and json.loads((run / "replay.json").read_text()) == state["result"]
