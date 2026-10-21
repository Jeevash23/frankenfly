"""Circuit builds started from the app: a background job (jobs.py) running the repository's own builder, one at a time.

Arguments are validated and passed as a list, never through a shell. The builder reads only the
prepared FlyWire archive in the ignored cache, needs no network and writes to data/circuits/local/.
"""
import json
import sys
import threading
from pathlib import Path
from typing import Annotated
from pydantic import Field
from digitalfly.api.models import CircuitName, StrictModel
from digitalfly.data.jobs import JobManager

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
    """Builds as "build" jobs. A build never queues: a second one is refused while one runs. status() keeps the
    shape GET /api/connectome/build has always had; GET /api/jobs lists the same jobs."""

    def __init__(self, jobs: JobManager | None = None):
        self.jobs = jobs or JobManager()
        self.lock = threading.Lock()
        self.job = None  # the latest build started here, and its request
        self.request = None

    def status(self):
        with self.lock:
            job, request = self.job, self.request
        if job is None:
            return {"status": "idle", "log": []}
        with self.jobs.lock:
            state = {"status": {"queued": "running", "cancelled": "failed"}.get(job.status, job.status),
                     "name": request.name, "request": request.model_dump(), "started": job.started_s}
            if not job.active:
                state.update(exit_code=job.exit_code, result=job.result, finished=job.finished_s)
            return {**state, "log": list(job.lines)[-40:]}

    def building(self) -> str | None:
        """The name of the circuit a running build will write, if a build is running."""
        with self.lock:
            job, request = self.job, self.request
        return request.name if job is not None and job.active else None

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
            self.job = self.jobs.submit("build", f"Build circuit {request.name}", command, target=request.name,
                                        busy="A circuit build is already running. Wait for it to finish.")
            self.request = request
        return self.status()

    @staticmethod
    def command(request: BuildRequest) -> list[str]:
        command = [sys.executable, str(ROOT / "scripts/build_circuit.py"), "build", "--name", request.name,
                   "--hops", str(request.hops), "--threshold", str(request.threshold), "--cap", str(request.cap)]
        command += [part for seed in request.seeds for part in ("--seed", seed)]
        return command + (["--whole-brain"] if request.whole_brain else [])

    def close(self):
        self.jobs.close("build")
