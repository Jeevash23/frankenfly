"""Circuit builds started from the app: one subprocess at a time, running the repository's own builder.

Arguments are validated and passed as a list, never through a shell. The builder reads only the
prepared FlyWire archive in the ignored cache, needs no network and writes to data/circuits/local/.
"""
import json
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Annotated
from pydantic import Field
from digitalfly.api.models import CircuitName, StrictModel

ROOT = Path(__file__).resolve().parents[4]
PREPARED = ROOT / ".cache/circuits/fafb783-connectome.npz"
CATALOG = ROOT / ".cache/circuits/fafb783-catalog.json"
SeedName = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")]


class BuildRequest(StrictModel):
    name: CircuitName
    seeds: list[SeedName] = Field(min_length=1, max_length=20)
    hops: int = Field(default=2, ge=1, le=6)
    threshold: int = Field(default=5, ge=1, le=1000)
    cap: int = Field(default=3000, ge=10, le=200_000)
    whole_brain: bool = False


def catalog():
    """Every FlyWire v783 cell type available to the builder, or None before `prepare` has run."""
    if not CATALOG.is_file():
        return None
    return json.loads(CATALOG.read_text())


def catalog_ready() -> bool:
    return CATALOG.is_file()


class BuildManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.lines = deque(maxlen=200)
        self.state = {"status": "idle"}

    def status(self):
        with self.lock:
            return {**self.state, "log": list(self.lines)[-40:]}

    def building(self) -> str | None:
        """The name of the circuit a running build will write, if a build is running."""
        with self.lock:
            running = self.process is not None and self.process.poll() is None
            return self.state.get("name") if running else None

    def start(self, request: BuildRequest, in_use: set[str] = frozenset()):
        """Start a build. `in_use` names the circuits the simulation has loaded: rebuilding one of them in place would
        leave the running experiment on wiring that no longer matches its file."""
        from digitalfly.neural.connectome import CIRCUIT_DIR
        if not PREPARED.is_file():
            raise FileNotFoundError("Prepare the FlyWire data once first: backend/.venv/bin/python scripts/build_circuit.py prepare "
                                    "(it needs the build-only data lock and the cached or downloaded FlyWire files).")
        if any((CIRCUIT_DIR / f"{request.name}{suffix}").exists() for suffix in (".json", ".npz")):
            raise ValueError(f"{request.name} is a built-in circuit. Choose another name.")
        if request.name in in_use:
            raise ValueError(f"The running experiment uses the {request.name} circuit, so it cannot be rebuilt now. "
                             "Choose another name, or reset onto another circuit or model first.")
        command = self.command(request)
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise ValueError("A circuit build is already running. Wait for it to finish.")
            self.lines.clear()
            self.process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, start_new_session=True)
            self.state = {"status": "running", "name": request.name, "request": request.model_dump(),
                          "started": time.time()}
            process = self.process
        threading.Thread(target=self._follow, args=(process,), daemon=True).start()
        return self.status()

    @staticmethod
    def command(request: BuildRequest) -> list[str]:
        command = [sys.executable, str(ROOT / "scripts/build_circuit.py"), "build", "--name", request.name,
                   "--hops", str(request.hops), "--threshold", str(request.threshold), "--cap", str(request.cap)]
        command += [part for seed in request.seeds for part in ("--seed", seed)]
        return command + (["--whole-brain"] if request.whole_brain else [])

    def _follow(self, process):
        for line in process.stdout:
            with self.lock:
                self.lines.append(line.rstrip())
        code = process.wait()
        with self.lock:
            if process is self.process:
                result = None
                if code == 0 and self.lines:
                    try:
                        result = json.loads(self.lines[-1])
                    except ValueError:
                        pass
                self.state = {**self.state, "status": "done" if code == 0 else "failed", "exit_code": code,
                              "result": result, "finished": time.time()}

    def close(self):
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
