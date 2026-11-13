"""Background jobs: long work in its own process, so it never blocks the simulation or the API.

Each job runs one subprocess, started from an argument list (never a shell) in its own session, at a lower
scheduling priority. Cancelling a job terminates its whole process group. One job of each kind runs at a time;
later ones wait in a queue. Output is kept as a bounded log tail; a line "@progress F" (0 ≤ F ≤ 1) updates the
job's progress instead of the log. Circuit builds (builds.py) and replay checks of saved runs are the two kinds.
"""
from collections import deque
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import psutil

ROOT = Path(__file__).resolve().parents[4]
KINDS = ("build", "replay")
KEEP = 50  # jobs listed, newest first; waiting and running ones are never dropped
LOG_LINES = 200
QUEUE_LIMIT = 20  # waiting jobs per kind
STOP_TIMEOUT = 10  # seconds between terminating a job's process group and killing it
PROGRESS = re.compile(r"@progress (\d+(?:\.\d*)?|\.\d+)")
LEFTOVER_AGE_S = 3600
log = logging.getLogger("digitalfly")


def _now():
    return datetime.now(timezone.utc).isoformat()


class Job:
    def __init__(self, kind, label, command, env=None, target=None, finish=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.label, self.command, self.env, self.target = kind, label, command, env, target
        self.finish = finish or last_line_result
        self.status = "queued"
        self.created, self.started, self.finished = _now(), None, None
        self.started_s = self.finished_s = None  # epoch seconds, for the build status the app has always shown
        self.progress = None
        self.lines = deque(maxlen=LOG_LINES)
        self.result = self.error = self.exit_code = None
        self.process = None
        self.thread = None
        self.cancel_requested = False

    @property
    def active(self):
        return self.status in ("queued", "running")

    def describe(self):
        return {"id": self.id, "kind": self.kind, "status": self.status, "label": self.label, "target": self.target,
                "created": self.created, "started": self.started, "finished": self.finished,
                "progress": self.progress, "log_tail": list(self.lines), "result": self.result, "error": self.error}


def _last_output(job, code):
    lines = [line for line in job.lines if line.strip()]
    return lines[-1] if lines else f"The job exited with code {code}."


def last_line_result(job, code):
    """The builder's convention: on success, its last output line is a JSON summary."""
    result = None
    if code == 0 and job.lines:
        try:
            result = json.loads(job.lines[-1])
        except ValueError:
            pass
    return ("done", result, None) if code == 0 else ("failed", None, _last_output(job, code))


def verdict_result(job, code):
    """A replay check is done once it has reached a verdict, passed or not (scripts/replay.py --save prints it as
    one JSON line); without one it failed, and its last output line says why."""
    for line in reversed(job.lines):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "ok" in data:
            return "done", data, None
    return "failed", None, "The replay finished without a verdict." if code == 0 else _last_output(job, code)


def _terminate(processes, timeout=STOP_TIMEOUT):
    """Terminate each process's group (its session), then kill what is left after the timeout. A process that has
    exited is left alone: once it is reaped, its id may belong to another process."""
    processes = [process for process in processes if process.poll() is None]
    def signal_group(process, number):
        try:
            os.killpg(process.pid, number)
        except (ProcessLookupError, PermissionError):
            pass
        except AttributeError:  # no process groups on this platform
            process.send_signal(number)
    for process in processes:
        signal_group(process, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            signal_group(process, getattr(signal, "SIGKILL", signal.SIGTERM))
            process.wait()


class JobManager:
    def __init__(self, cwd: Path = ROOT):
        self.cwd = cwd
        self.lock = threading.Lock()
        self.jobs: list[Job] = []  # oldest first
        self.closed = False

    def submit(self, kind, label, command, *, env=None, target=None, finish=None, busy=None, duplicate=None) -> Job:
        """Queue a job. `env` may be a function, called just before the job starts. Refuse with the message `busy`
        while another job of the kind waits or runs, instead of queueing behind it, or with `duplicate` while one
        for the same target does."""
        if kind not in KINDS:
            raise ValueError(f"Unknown job kind {kind}.")
        with self.lock:
            if self.closed:
                raise RuntimeError("DigitalFly is shutting down.")
            active = [job for job in self.jobs if job.kind == kind and job.active]
            if busy is not None and active:
                raise ValueError(busy)
            if duplicate is not None and any(job.target == target for job in active):
                raise ValueError(duplicate)
            if sum(job.status == "queued" for job in active) >= QUEUE_LIMIT:
                raise ValueError(f"{QUEUE_LIMIT} {kind} jobs are already waiting. Wait for some to finish.")
            job = Job(kind, label, command, env, target, finish)
            self.jobs.append(job)
            self._start_next(kind)
            self._prune()
            return job

    def _start_next(self, kind):
        """With the lock held: start the oldest waiting job of a kind, unless one of that kind runs."""
        if self.closed or any(job.kind == kind and job.status == "running" for job in self.jobs):
            return
        job = next((job for job in self.jobs if job.kind == kind and job.status == "queued"), None)
        if job is not None:
            job.status, job.started, job.started_s = "running", _now(), time.time()
            job.thread = threading.Thread(target=self._run, args=(job,), name=f"digitalfly-job-{job.id}", daemon=True)
            job.thread.start()

    def _prune(self):
        finished = [job for job in self.jobs if not job.active]
        for job in finished[:max(0, len(self.jobs) - KEEP)]:
            self.jobs.remove(job)

    def _run(self, job):
        code = None
        try:
            env = job.env() if callable(job.env) else job.env
            # stdout and stderr share one pipe: unbuffered output keeps them in order, so a crash message is the
            # last line read and becomes the job's error instead of output that was still waiting in a buffer
            env = {**(os.environ if env is None else env), "PYTHONUNBUFFERED": "1"}
            with self.lock:
                if not job.cancel_requested:
                    job.process = subprocess.Popen(job.command, cwd=self.cwd, env=env, stdin=subprocess.DEVNULL,
                                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                   errors="replace", start_new_session=True)
            if job.process is not None:
                try:
                    os.setpriority(os.PRIO_PROCESS, job.process.pid, 10)  # the live simulation comes first
                except (AttributeError, OSError):
                    pass
                for line in job.process.stdout:
                    line = line.rstrip()
                    progress = PROGRESS.fullmatch(line)
                    with self.lock:
                        if progress:
                            job.progress = min(1., float(progress.group(1)))
                        else:
                            job.lines.append(line)
                job.process.stdout.close()
                code = job.process.wait()
        except Exception as exc:
            with self.lock:
                job.lines.append(f"{type(exc).__name__}: {exc}")
            if job.process is not None and job.process.poll() is None:
                _terminate([job.process])
        with self.lock:
            job.exit_code = code
            if job.cancel_requested:
                job.status, job.result, job.error = "cancelled", None, "Cancelled."
            elif code is None:
                job.status, job.result, job.error = "failed", None, _last_output(job, code)
            else:
                job.status, job.result, job.error = job.finish(job, code)
            if job.status == "done":
                job.progress = 1.
            job.finished, job.finished_s = _now(), time.time()
            self._start_next(job.kind)
            self._prune()

    def listing(self) -> list[dict]:
        with self.lock:
            return [job.describe() for job in reversed(self.jobs)][:KEEP]

    def get(self, job_id) -> Job:
        with self.lock:
            for job in self.jobs:
                if job.id == job_id:
                    return job
        raise KeyError(job_id)

    def describe(self, job) -> dict:
        with self.lock:
            return job.describe()

    def active(self, kind, target=None) -> list[Job]:
        with self.lock:
            return [job for job in self.jobs if job.kind == kind and job.active
                    and (target is None or job.target == target)]

    def cancel(self, job_id) -> dict:
        """Cancel a waiting job, or terminate a running one's process group. A finished job is left as it is."""
        job = self.get(job_id)
        self._stop([job])
        return self.describe(job)

    def _stop(self, jobs):
        with self.lock:
            running = []
            for job in jobs:
                if job.status == "queued":
                    job.status, job.error, job.finished, job.finished_s = "cancelled", "Cancelled.", _now(), time.time()
                # A running job whose process has exited is finishing on its own: its result stands.
                elif job.status == "running" and (job.process is None or job.process.poll() is None):
                    job.cancel_requested = True
                    running.append(job)
        _terminate([job.process for job in running if job.process is not None])
        for job in running:
            job.thread.join(timeout=STOP_TIMEOUT)

    def close(self, kind=None):
        """Cancel every waiting job and terminate the running ones (of one kind, or all when shutting down)."""
        with self.lock:
            if kind is None:
                self.closed = True
            jobs = [job for job in self.jobs if job.active and kind in (None, job.kind)]
        self._stop(jobs)


def replay_environment(engine: str):
    """The server's own environment, with its OpenGL choice (simulation/engines.py select_gl) for FlyGym runs:
    a replay renders through the same backend as the run it checks."""
    env = dict(os.environ)
    if engine == "flygym":
        from digitalfly.simulation.engines import select_gl
        backend = select_gl()
        if backend not in (None, "default"):
            env["MUJOCO_GL"] = backend
    return env


def submit_replay(jobs: JobManager, directory: Path) -> Job:
    """Queue scripts/replay.py on a saved run folder. It writes its verdict to the folder's replay.json."""
    try:
        engine = json.loads((directory / "metadata.json").read_text())["initial_config"]["engine"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FileNotFoundError("Saved run not found or unreadable.") from exc
    command = [sys.executable, str(ROOT / "scripts/replay.py"), str(directory), "--save", "--progress"]
    return jobs.submit("replay", f"Replay {directory.name}", command, target=directory.name,
                       env=lambda: replay_environment(engine), finish=verdict_result,
                       duplicate="A replay of this run is already waiting or running.")


def _writer_alive(path: Path) -> bool:
    # The circuit builder names partial files .NAME.PID.part (scripts/build_circuit.py write_atomic).
    pid = path.name.rsplit(".", 2)[-2] if path.name.count(".") >= 2 else ""
    return pid.isdigit() and psutil.pid_exists(int(pid))


def remove_leftovers(root: Path, age_s: float | None = None) -> list[str]:
    """Remove what interrupted work left behind, once older than age_s (default LEFTOVER_AGE_S, one hour):
    unfinished exports (runs/.tmp-*), deletions (runs/.deleting-*) and replay verdicts (runs/*/.replay.json.*.part),
    and partial circuit files (data/circuits/local/.*.part) whose builder has exited. Links are removed, never
    followed. Returns the removed paths, relative to root."""
    cutoff = time.time() - (LEFTOVER_AGE_S if age_s is None else age_s)
    runs, local = root / "runs", root / "data/circuits/local"
    candidates = []
    if runs.is_dir() and not runs.is_symlink():
        candidates += [*runs.glob(".tmp-*"), *runs.glob(".deleting-*"), *runs.glob("*/.replay.json.*.part")]
    if local.is_dir() and not local.is_symlink():
        candidates += [path for path in local.glob(".*.part") if not _writer_alive(path)]
    removed = []
    for path in sorted(candidates):
        try:
            stat = path.lstat()
            if max(stat.st_mtime, stat.st_ctime) > cutoff:  # a rename updates ctime only
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            continue
        removed.append(str(path.relative_to(root)))
    if removed:
        log.warning("Removed %d leftover(s) of interrupted exports, deletions or builds: %s", len(removed),
                    ", ".join(removed))
    return removed
