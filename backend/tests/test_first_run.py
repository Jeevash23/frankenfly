"""First run: OpenGL backend selection, the launcher's Ctrl+C and the doctor script."""
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import pytest
from digitalfly.simulation import engines
from digitalfly.simulation.engines import ROOT

FIXES = ["--toy", "xvfb-run -a", "MUJOCO_GL=glfw", "libegl1", "libosmesa6"]


@pytest.fixture
def fresh_gl(monkeypatch):
    """A process that has not chosen a backend yet and has not imported MuJoCo."""
    monkeypatch.setattr(engines, "_gl", {})
    monkeypatch.delitem(sys.modules, "mujoco", raising=False)
    monkeypatch.setenv("MUJOCO_GL", "unset")  # so that undoing restores the original, absent or not
    monkeypatch.delenv("MUJOCO_GL")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(engines.sys, "platform", "linux")
    probed = []
    return probed


def fake_probe(probed, working):
    def probe(backend, timeout=60):
        probed.append(backend)
        return None if backend in working else f"{backend} unavailable"
    return probe


def test_headless_without_a_backend_says_what_to_do(fresh_gl, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(engines, "probe_gl", fake_probe(fresh_gl, set()))
    assert engines.select_gl() is None and fresh_gl == ["egl", "osmesa"]
    assert "MUJOCO_GL" not in os.environ  # MuJoCo still imports, so physics runs without rendering
    message = engines.gl_help()
    assert "tried EGL, OSMesa; GLFW needs a display" in message
    assert all(fix in message for fix in FIXES)
    assert engines.select_gl() is None and fresh_gl == ["egl", "osmesa"]  # probed once per process


def test_first_working_backend_is_used(fresh_gl, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(engines, "probe_gl", fake_probe(fresh_gl, {"osmesa"}))
    assert engines.select_gl() == "osmesa" and os.environ["MUJOCO_GL"] == "osmesa" and fresh_gl == ["egl", "osmesa"]


def test_a_display_keeps_mujocos_default_first(fresh_gl, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(engines, "probe_gl", fake_probe(fresh_gl, {"glfw", "egl"}))
    assert engines.select_gl() == "glfw" and fresh_gl == ["glfw"]


def test_explicit_mujoco_gl_is_never_overridden(fresh_gl, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("MUJOCO_GL", "egl")
    monkeypatch.setattr(engines, "probe_gl", fake_probe(fresh_gl, {"osmesa"}))
    assert engines.select_gl() == "egl" and os.environ["MUJOCO_GL"] == "egl" and fresh_gl == []


CHILD = """
import json, sys
from digitalfly.simulation import engines
from digitalfly.simulation.experiment import Experiment
from digitalfly.api.models import RunConfig
out = {}
for sensor in ["geometric", "vision"]:
    exp = Experiment(RunConfig(sensor_model=sensor), render=True)
    out[sensor] = {"status": exp.status, "error": exp.error, "rendering": exp.body is not None and exp.body.renderer is not None,
                   "render_error": exp.body.render_error if exp.body else None}
    exp.close()
out["backend"] = engines._gl["backend"]
print(json.dumps(out))
"""


def run_child(command, env):
    result = subprocess.run(command + [sys.executable, "-c", CHILD], env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.flygym
def test_headless_first_start_runs_physics_or_explains(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"DISPLAY", "WAYLAND_DISPLAY", "MUJOCO_GL", "PYOPENGL_PLATFORM"}}
    env["PYTHONPATH"] = str(ROOT / "backend/src")
    out = run_child([], env)
    geometric, vision = out["geometric"], out["vision"]
    assert geometric["status"] == "paused", geometric  # physics always works
    if out["backend"] is None:  # this container: no EGL, no OSMesa
        assert not geometric["rendering"] and all(fix in geometric["render_error"] for fix in FIXES)
        assert vision["status"] == "error" and all(fix in vision["error"] for fix in FIXES)
    else:
        assert geometric["rendering"] and vision["status"] == "paused", out


@pytest.mark.flygym
@pytest.mark.render
def test_virtual_display_selects_glfw(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"MUJOCO_GL", "PYOPENGL_PLATFORM", "WAYLAND_DISPLAY"}}
    env["PYTHONPATH"] = str(ROOT / "backend/src")
    if env.get("DISPLAY"):
        command = []
    elif shutil.which("xvfb-run"):
        command = ["xvfb-run", "-a"]
    else:
        pytest.skip("needs a display or xvfb-run")
    out = run_child(command, env)
    assert out["backend"] == "glfw", out
    assert out["geometric"]["rendering"] and out["vision"]["status"] == "paused", out


@pytest.mark.parametrize("host", [[], ["--host", "0.0.0.0"]])
def test_launcher_stops_cleanly_on_ctrl_c(tmp_path, host):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Listening beyond loopback (as in the container image) needs the explicit acknowledgement.
    env = {**os.environ, "DIGITALFLY_ALLOW_NETWORK_BIND": "1"} if host else None
    launcher = subprocess.Popen([sys.executable, str(ROOT / "scripts/launch.py"), "--toy", "--dev", "--port", str(port), *host],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and launcher.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                    assert json.loads(response.read())["worker_alive"]
                    break
            except OSError:
                time.sleep(.1)
        launcher.send_signal(signal.SIGINT)
        out, err = launcher.communicate(timeout=60)
    finally:
        if launcher.poll() is None:
            launcher.kill()
    assert launcher.returncode in {0, 130}, err
    assert "Traceback" not in err and "KeyboardInterrupt" not in err, err
    assert "Ctrl+C to stop" in out
    assert (f"Listening on 0.0.0.0:{port}" in out) == bool(host), out


def test_launcher_refuses_network_bind_and_bad_origins_without_starting():
    env = {k: v for k, v in os.environ.items() if k not in {"DIGITALFLY_ALLOW_NETWORK_BIND", "DIGITALFLY_HOST"}}
    launch = [sys.executable, str(ROOT / "scripts/launch.py"), "--toy", "--dev", "--port", "8999"]
    for args, extra in [(["--host", "0.0.0.0"], {}), ([], {"DIGITALFLY_HOST": "0.0.0.0"}),
                        (["--host", "0.0.0.0"], {"DIGITALFLY_ALLOW_NETWORK_BIND": "yes"})]:
        result = subprocess.run([*launch, *args], env={**env, **extra}, capture_output=True, text=True, timeout=60)
        assert result.returncode == 1 and "DIGITALFLY_ALLOW_NETWORK_BIND=1" in result.stderr, result
        assert "Ctrl+C to stop" not in result.stdout
    result = subprocess.run(launch, env={**env, "DIGITALFLY_ALLOWED_ORIGINS": "localhost:9000"}, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 1 and "not an origin like http://localhost:9000" in result.stderr, result


def load_doctor():
    spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts/doctor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_doctor_reads_locks_and_version_ranges(tmp_path):
    doctor = load_doctor()
    lock = tmp_path / "requirements.lock"
    lock.write_text("absl-py==2.5.0 \\\n    --hash=sha256:00\n    # via mujoco\n"
                    "cffi==2.1.1 ; platform_python_implementation != 'PyPy' \\\n    --hash=sha256:11\n"
                    "Zope.Interface[extra]==8.0\n")
    assert doctor.lock_pins(lock) == {"absl-py": ("2.5.0", ""), "zope-interface": ("8.0", ""),
                                      "cffi": ("2.1.1", "platform_python_implementation != 'PyPy'")}
    assert doctor.satisfies("v22.12.0", ">=22.12 <27") and doctor.satisfies("v26.9.1", ">=22.12 <27")
    assert not doctor.satisfies("v22.11.9", ">=22.12 <27") and not doctor.satisfies("v27.0.0", ">=22.12 <27")


def test_doctor_prints_one_line_per_check():
    python = ROOT / "backend/.venv/bin/python"
    python = python if python.is_file() else sys.executable  # a worktree may share another checkout's environment
    result = subprocess.run([sys.executable, str(ROOT / "scripts/doctor.py"), "--python", str(python)],
                            capture_output=True, text=True, timeout=600)
    assert result.returncode in {0, 1}, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("[")]
    names = {line[7:22].strip() for line in lines}
    assert {"Python", "Locked packages", "Node/npm", "Frontend build", "OpenGL", "FlyVis eyes", "Cache",
            "Disk space", "Port"} <= names, result.stdout
    assert all(" -> " in line for line in lines if line.startswith(("[warn]", "[fail]"))), result.stdout
