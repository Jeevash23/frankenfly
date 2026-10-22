"""Check this computer and checkout for what DigitalFly needs: one line per check, with a fix.

    python3 scripts/doctor.py              # any Python 3.8+; the project environment is inspected separately
    python3 scripts/doctor.py --port 8001 --python /path/to/other/venv/bin/python
    python3 scripts/doctor.py --backend-only   # after ./scripts/setup.sh --backend-only: no interface expected

It only reads and probes: nothing is installed, downloaded, changed or stopped. Exits 1 if a check fails.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / "backend/.venv/bin/python"
SETUP = "./scripts/setup.sh"
# The repository's Dockerfile sets DIGITALFLY_CONTAINER=image; other containers are recognised by their marker files.
IMAGE = os.environ.get("DIGITALFLY_CONTAINER") == "image"
CONTAINER = IMAGE or Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
REBUILD = "rebuild the image: docker build -t digitalfly . (see docs/INSTALL.md)"
BACKEND_ONLY = False
failures = []


def report(status: str, name: str, detail: str, fix: str = ""):
    if status == "fail":
        failures.append(name)
    print(f"[{status:^4}] {name:<15} {detail}" + (f" -> {fix}" if fix and status != "ok" else ""), flush=True)


def venv(code: str, *args: str, timeout: float = 120):
    """Run code in the project environment, with this checkout's backend on the path; parsed JSON or None."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend/src")}
    try:
        result = subprocess.run([str(VENV_PYTHON), "-c", code, *args], capture_output=True, text=True,
                                timeout=timeout, env=env, cwd=ROOT)
        return json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def version_tuple(text: str):
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def satisfies(found: str, spec: str) -> bool:
    """found against a simple npm-style range such as '>=22.12 <27'."""
    have = version_tuple(found)
    for op, wanted in re.findall(r"(>=|<=|>|<|=)?\s*(\d+(?:\.\d+){0,2})", spec):
        want = version_tuple(wanted)
        size = len(want)
        ok = {">=": have >= want, "<=": have[:size] <= want, ">": have[:size] > want,
              "<": have < want, "": have[:size] == want, "=": have[:size] == want}[op]
        if not ok:
            return False
    return True


def lock_pins(path: Path) -> dict:
    """{normalized name: (version, marker or '')} from a pip-compile lock."""
    pins = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?$", line)
        if match:
            pins[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = (match.group(2), (match.group(3) or "").strip())
    return pins


INSTALLED = """
import json, re, sys
from importlib import metadata
try:
    from pip._vendor.packaging.markers import Marker
except ImportError:
    Marker = None
names = {re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower(): d.version for d in metadata.distributions() if d.metadata["Name"]}
pins = json.loads(sys.argv[1])
applies = {n: Marker is None or not m or Marker(m).evaluate() for n, (v, m) in pins.items()}
print(json.dumps({"python": list(sys.version_info[:3]), "installed": {n: names.get(n) for n in pins if applies[n]}}))
"""

EXTRAS = """
import json
from importlib import metadata
def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
from digitalfly.vision.flyvis_eyes import available
ok, reason = available()
print(json.dumps({"flyvis": version("flyvis"), "torch": version("torch"), "pyarrow": version("pyarrow"),
                  "flyvis_ready": ok, "flyvis_reason": reason}))
"""

PROBE = """
import json, sys
from digitalfly.simulation.engines import GL_FIXES, probe_gl
print(json.dumps({"fixes": GL_FIXES, "results": {backend: probe_gl(backend) for backend in sys.argv[1:]}}))
"""


def check_python():
    if not VENV_PYTHON.is_file():
        report("fail", "Python", f"the project environment {VENV_PYTHON} is missing", REBUILD if IMAGE else
               f"{SETUP} (needs Python 3.12; PYTHON_BIN=/path/to/python3.12 {SETUP} to choose one)")
        return None
    pins = lock_pins(ROOT / "backend/requirements.lock")
    info = venv(INSTALLED, json.dumps(pins))
    if info is None:
        report("fail", "Python", f"{VENV_PYTHON} does not run", f"rm -rf backend/.venv && {SETUP}")
        return None
    found, minor = ".".join(map(str, info["python"])), tuple(info["python"][:2])
    recreate = f"rm -rf backend/.venv && PYTHON_BIN=/path/to/python3.12 {SETUP}"
    if not (3, 12) <= minor < (3, 15):
        report("fail", "Python", f"the project environment has Python {found}; DigitalFly needs 3.12, 3.13 or 3.14 "
               "(3.12 recommended)", recreate)
    elif minor != (3, 12):  # supported (pyproject, CI), as setup.sh says when it builds one
        report("info", "Python", f"{found} in the project environment; 3.12 is the recorded stack: on {found} FlyVis is "
               "unavailable and exact replay of recorded runs is not guaranteed", f"for those, {recreate}")
    else:
        report("ok", "Python", f"{found} in the project environment")
    return pins, info["installed"]


def check_lock(pins, installed):
    missing = sorted(n for n, v in installed.items() if v is None)
    differ = sorted(f"{n} {v} (lock {pins[n][0]})" for n, v in installed.items() if v is not None and v != pins[n][0])
    fix = REBUILD if IMAGE else "backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock"
    if missing or differ:
        listed = (["missing: " + ", ".join(missing[:8])] if missing else []) + (["differ: " + ", ".join(differ[:8])] if differ else [])
        report("fail", "Locked packages", f"{len(missing) + len(differ)} of {len(installed)} do not match "
               f"backend/requirements.lock ({'; '.join(listed)})", fix)
    else:
        report("ok", "Locked packages", f"all {len(installed)} match backend/requirements.lock")


def check_node():
    if IMAGE or BACKEND_ONLY:
        report("info", "Node/npm", "not needed: " + ("the image ships the built interface" if IMAGE else "--backend-only"))
        return
    spec = json.loads((ROOT / "frontend/package.json").read_text()).get("engines", {}).get("node", "")
    fix = f"install Node.js {spec} with npm (nodejs.org or your package manager); only needed to build the interface"
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        npm = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=60,
                             shell=sys.platform == "win32").stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        node = npm = ""
    if not node or not npm:
        report("warn", "Node/npm", f"{'npm' if node else 'node'} not found (needs Node {spec})", fix)
    elif not satisfies(node, spec):
        report("warn", "Node/npm", f"Node {node} is outside frontend/package.json engines {spec}; npm {npm}", fix)
    else:
        report("ok", "Node/npm", f"Node {node} (engines {spec}), npm {npm}")


def check_frontend():
    index = ROOT / "frontend/dist/index.html"
    sources = [*(ROOT / "frontend/src").rglob("*"), ROOT / "frontend/package-lock.json", ROOT / "frontend/index.html",
               ROOT / "frontend/vite.config.ts"]
    stale = index.is_file() and any(path.is_file() and path.stat().st_mtime > index.stat().st_mtime for path in sources)
    if BACKEND_ONLY and (stale or not index.is_file()):  # the interface was opted out of, so it cannot fail
        report("info", "Frontend build", ("frontend/dist is older than frontend/src" if stale else "not built")
               + " (--backend-only); the toolkit, replay and tests do not need it",
               f"{SETUP} without --backend-only, for the web interface")
    elif not index.is_file():
        report("fail", "Frontend build", "frontend/dist is missing", REBUILD if IMAGE else
               f"{SETUP}, or npm --prefix frontend ci && npm --prefix frontend run build")
    elif stale:
        report("fail", "Frontend build", "frontend/dist is older than frontend/src; the launcher refuses a stale build",
               "npm --prefix frontend run build")
    else:
        report("ok", "Frontend build", "frontend/dist is newer than frontend/src")


def check_gl():
    explicit = os.environ.get("MUJOCO_GL")
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if sys.platform == "darwin":
        candidates = ["cgl"]
    else:
        candidates = ([explicit] if explicit else []) + [b for b in ["glfw"] * bool(display) + ["egl", "osmesa"] if b != explicit]
    probe = venv(PROBE, *candidates, timeout=300)
    if probe is None:
        report("warn", "OpenGL", "could not probe (the project environment does not import)", "fix the checks above, then rerun")
        return
    results, fixes = probe["results"], probe["fixes"]
    if CONTAINER:
        fixes = ("in a container: build from the repository's Dockerfile, which installs Mesa EGL and OSMesa, or add "
                 "libegl1 libgl1-mesa-dri to your image; otherwise " + fixes)
    working = [b for b in candidates if results.get(b) is None]
    failed = "; ".join(f"{b}: {results[b][:90]}" for b in candidates if results.get(b) is not None)
    if explicit and results.get(explicit) is not None:
        report("fail", "OpenGL", f"MUJOCO_GL={explicit} does not work ({results[explicit][:120]})",
               f"unset MUJOCO_GL to let DigitalFly choose{', or use MUJOCO_GL=' + working[0] if working else '; or ' + fixes}")
    elif working:
        chosen = explicit or working[0]
        report("ok", "OpenGL", f"{', '.join(working)} render{'s' if len(working) == 1 else ''}; DigitalFly uses {chosen}"
               + (" (MUJOCO_GL)" if explicit else "") + (f" (not: {failed})" if failed else ""))
    else:
        report("warn", "OpenGL", f"no backend renders ({failed or 'none tried'}); physics runs without the 3D view "
               "and compound-eye vision is unavailable", fixes)


def check_extras():
    extras = venv(EXTRAS)
    if extras is None:
        report("warn", "Optional extras", "could not check (the project environment does not import)")
        return
    if extras["flyvis_ready"]:
        report("ok", "FlyVis eyes", f"flyvis {extras['flyvis']}, torch {extras['torch']}, pretrained network present")
    elif extras["flyvis"] and extras["torch"]:
        report("info", "FlyVis eyes", "installed, but the pretrained networks are missing (optional)",
               "backend/.venv/bin/python scripts/fetch_flyvis.py")
    else:
        report("info", "FlyVis eyes", "not installed (optional)", "rebuild the image with --build-arg EXTRAS=flyvis"
               if IMAGE else f"{SETUP} --with flyvis (the vision lock, then scripts/fetch_flyvis.py)")
    prepared = (ROOT / ".cache/circuits/fafb783-catalog.json").is_file() and (ROOT / ".cache/circuits/fafb783-connectome.npz").is_file()
    if prepared:
        report("ok", "Circuit builder", "FlyWire archive prepared in .cache/circuits/" + (f"; pyarrow {extras['pyarrow']}" if extras["pyarrow"] else ""))
    elif extras["pyarrow"]:
        report("info", "Circuit builder", f"pyarrow {extras['pyarrow']} installed; FlyWire archive not prepared (optional)",
               "backend/.venv/bin/python scripts/build_circuit.py prepare")
    else:
        report("info", "Circuit builder", "not prepared, pyarrow not installed (optional; committed circuits work without it)",
               "rebuild the image with --build-arg EXTRAS=builder" if IMAGE
               else f"{SETUP} --with builder (the data lock, then scripts/build_circuit.py prepare)")


def size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def check_caches():
    folders = [(".cache/matplotlib", "font cache; the first start builds it (about 20 s)"),
               ("data/flygym-assets", "FlyGym's asset cache; filled on the first FlyGym start"),
               (".cache/flyvis", "FlyVis networks (optional)"), (".cache/circuits", "FlyWire downloads (optional)")]
    for folder, purpose in folders:
        path = ROOT / folder
        if path.is_dir():
            report("ok", "Cache", f"{folder}: {size(path) / 1e6:,.1f} MB")
        else:
            report("info", "Cache", f"{folder} absent: {purpose}")
    runs = ROOT / "runs"
    leftovers = sorted(p.name for p in runs.glob(".tmp-*")) + sorted(p.name for p in runs.glob(".deleting-*")) if runs.is_dir() else []
    saved = [p for p in runs.iterdir() if p.is_dir() and not p.name.startswith(".")] if runs.is_dir() else []
    detail = f"runs/: {len(saved)} saved runs, {size(runs) / 1e6:,.1f} MB" if runs.is_dir() else "runs/ is empty"
    if leftovers:
        report("warn", "Saved runs", f"{detail}; {len(leftovers)} interrupted export or deletion folders (never listed)",
               "delete them: rm -rf runs/.tmp-* runs/.deleting-*")
    else:
        report("ok", "Saved runs", detail)


def check_disk():
    free = shutil.disk_usage(ROOT).free / 1e9
    fix = "free space, for example by deleting old runs in the Run library or folders under runs/"
    if free < .5:
        report("fail", "Disk space", f"{free:.2f} GB free", fix)
    elif free < 2:
        report("warn", "Disk space", f"{free:.1f} GB free; a full FlyGym export takes about 70 MB, FlyVis about 1 GB", fix)
    else:
        report("ok", "Disk space", f"{free:,.1f} GB free")


def check_port(port: int):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            report("ok", "Port", f"{port} is free")
            return
        except OSError:
            pass
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            ours = json.loads(response.read()).get("service") == "DigitalFly"
    except Exception:
        ours = False
    if IMAGE and ours:
        report("info", "Port", f"{port} is in use by this container's DigitalFly server (expected with docker exec)")
        return
    report("warn", "Port", f"{port} is in use" + (" by a running DigitalFly server" if ours else ""),
           f"stop that server (Ctrl+C or Quit), or start on another port: ./scripts/start.sh --port {port + 1}"
           + (f"; from the host, publish another port instead: docker run -p 127.0.0.1:{port + 1}:8000 ..." if CONTAINER else ""))


def main():
    parser = argparse.ArgumentParser(description="Check what DigitalFly needs on this computer.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--python", type=Path, default=VENV_PYTHON, help="The project environment's Python")
    parser.add_argument("--backend-only", action="store_true", help="Do not expect Node.js or the built interface")
    args = parser.parse_args()
    globals().update(VENV_PYTHON=args.python, BACKEND_ONLY=args.backend_only)
    print(f"DigitalFly doctor · {ROOT}" + (" · DigitalFly container image" if IMAGE else " · in a container" if CONTAINER else "")
          + "\n", flush=True)
    environment = check_python()
    if environment is not None:
        check_lock(*environment)
    check_node()
    check_frontend()
    if environment is not None:
        check_gl()
        check_extras()
    check_caches()
    check_disk()
    check_port(args.port)
    print("\n" + (f"{len(failures)} check(s) failed: {', '.join(failures)}." if failures else "No blocking problems found."))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
