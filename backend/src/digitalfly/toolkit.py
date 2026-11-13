"""Research toolkit: closed-loop trials, parameter sweeps and open-loop circuit analyses.

Use it from Python or through scripts/toolkit.py:

    from digitalfly import toolkit
    config = toolkit.configure(engine="toy", neural_model="connectome", stimulus=toolkit.target(45, 12))
    toolkit.run_trial(config, duration_s=10)
    toolkit.run_trials(toolkit.grid(config, **{"seed": [1, 2, 3], "connectome_parameters.dynamics": ["rate", "spiking"]}),
                       workers=4)
    toolkit.ablation_scan(toolkit.ConnectomeParameters(), left=.5, right=.5)

Every run is built from a validated RunConfig, so a result is reproduced by its configuration and
seed. The model's labels still apply: wiring data-derived, signs assumed, dynamics and the sensor
and motor mappings engineered. Results describe this simulation, not flies.

A trial that raises becomes a row with an `error` text instead of ending the sweep, and the trials a dying worker
process takes down run again on their own; `TrialLog` saves rows as they finish and finds the ones a resumed sweep
can skip. Trials keep no per-sample recording, so they have no length limit. `summarize`
adds 95% intervals: Wilson score intervals for fractions, percentile bootstrap intervals for means
(2,000 resamples from a fixed seed, so a report repeats) and paired differences between conditions
over trials with the same seed and target.
"""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
import csv
import hashlib
import inspect
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
from statistics import NormalDist
import subprocess
import sys
import numpy as np
from digitalfly.api.models import CellTypeIntervention, ConnectomeParameters, Interventions, RunConfig, SensorState, Stimulus
from digitalfly.neural.connectome import ConnectomeCircuit, load_circuit
from digitalfly.simulation.engines import CONTROL_DT

ROOT = Path(__file__).resolve().parents[3]
REACH_MM = 2.0
TURN_DEG = 10.0  # a turn counts once the heading has changed this much from the start
THREAD_VARIABLES = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
BOOTSTRAP = {"resamples": 2000, "seed": 0, "level": .95}
PACKAGES = ["flygym", "mujoco", "numpy", "scipy", "numba", "pydantic", "torch", "flyvis"]
ENDINGS = (".csv", ".json", ".jsonl")  # what an output stem may end with; other dots belong to the name


def wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def target(bearing_deg: float, distance_mm: float, intensity: float = 1.0) -> Stimulus:
    """A target at a bearing from the fly's starting heading (positive = left) and a distance."""
    angle = math.radians(bearing_deg)
    return Stimulus(x=round(distance_mm * math.cos(angle), 6), y=round(distance_mm * math.sin(angle), 6),
                    intensity=intensity)


def configure(base: RunConfig | dict | None = None, **settings) -> RunConfig:
    """A validated RunConfig: `base` plus settings, where dotted names reach nested fields,
    for example configure(engine="toy", **{"connectome_parameters.dynamics": "spiking"})."""
    data = base.model_dump() if isinstance(base, RunConfig) else dict(base or {})
    for key, value in settings.items():
        set_setting(data, key, value.model_dump() if hasattr(value, "model_dump") else value)
    return RunConfig.model_validate(data)


def set_setting(data: dict, key: str, value):
    """Set a dotted name in nested settings; a group that is unset (None, such as readout_weights) starts empty."""
    *parents, last = key.split(".")
    for part in parents:
        if data.get(part) is None:
            data[part] = {}
        data = data[part]
        if not isinstance(data, dict):
            raise ValueError(f"Cannot set {key}: {part} is a single setting, not a group.")
    data[last] = value


def grid(base: RunConfig | dict | None = None, **axes) -> list[RunConfig]:
    """Every combination of the listed values, as configurations (dotted names as in `configure`)."""
    names = list(axes)
    return [configure(base, **dict(zip(names, values))) for values in itertools.product(*(axes[n] for n in names))]


def describe_config(config: RunConfig) -> dict:
    """The settings that usually differ between trials, flattened for tables."""
    p = config.connectome_parameters
    row = {"engine": config.engine, "seed": config.seed, "neural_model": config.neural_model,
           "sensor_model": config.sensor_model, "target_x_mm": config.stimulus.x, "target_y_mm": config.stimulus.y,
           "target_bearing_deg": round(math.degrees(math.atan2(config.stimulus.y, config.stimulus.x)), 6),
           "target_distance_mm": round(math.hypot(config.stimulus.x, config.stimulus.y), 6),
           "target_intensity": config.stimulus.intensity}
    if config.neural_model == "connectome":
        row.update({"circuit": p.circuit, "circuit_sha256": circuit_sha256(p.circuit), "dynamics": p.dynamics,
                    "readout_types": "+".join(p.readout_types or load_circuit(p.circuit).defaults["readout_types"]),
                    "speed_types": "+".join(p.speed_types), "output_gain": p.output_gain, "global_gain": p.global_gain})
    i = config.initial_interventions
    row["silenced"] = "+".join([f"DNa02 {i.silence_dna02}"] * (i.silence_dna02 != "none") + i.silence_types
                               + [c.target if c.mode == "silence" else c.label(p.dynamics) for c in i.cell_types]
                               + [f"{i.silence} units"] * (i.silence != "none")) or "none"
    return row


def circuit_sha256(circuit: str) -> str:
    """SHA-256 of the circuit file the name loads now (read from its header and bytes, without building it)."""
    from digitalfly.neural.connectome import _info, circuit_path
    path = circuit_path(circuit)
    return _info(str(path), path.stat().st_mtime_ns)["sha256"]


def hashable(dumped: dict) -> dict:
    """A dumped RunConfig or ConnectomeParameters as hashes see it: the default CPU backend is left out, so trials
    and variants keep the hashes they had before the backend setting existed (--resume still skips them)."""
    connectome = dumped.get("connectome_parameters", dumped)
    if connectome.get("backend") == "cpu":
        connectome = {k: v for k, v in connectome.items() if k != "backend"}
        return {**dumped, "connectome_parameters": connectome} if "connectome_parameters" in dumped else connectome
    return dumped


def config_hash(config: RunConfig | dict, **kwargs) -> str:
    """A short identity for one trial: its validated configuration, run_trial's settings (defaults filled in)
    and, for the connectome model, the circuit file's hash. `--resume` skips trials whose hash is saved."""
    config = config if isinstance(config, RunConfig) else RunConfig.model_validate(config)
    unknown = set(kwargs) - set(TRIAL_SETTINGS)
    if unknown:
        raise TypeError(f"run_trial has no setting {', '.join(sorted(unknown))}.")
    # duration_s=10 and duration_s=10.0 are the same trial.
    settings = {k: float(v) if isinstance(TRIAL_SETTINGS[k], float) else v for k, v in {**TRIAL_SETTINGS, **kwargs}.items()}
    circuit = circuit_sha256(config.connectome_parameters.circuit) if config.neural_model == "connectome" else None
    text = json.dumps({"config": hashable(config.model_dump(mode="json")), "settings": settings,
                       "circuit_sha256": circuit}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _git(*args):
    try:
        done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def code_version() -> dict:
    """digitalfly's version, the git commit and whether the tracked files had changes (None outside git)."""
    from digitalfly import __version__
    commit, status = _git("rev-parse", "HEAD"), _git("status", "--porcelain", "--untracked-files=no")
    return {"digitalfly": __version__, "git_commit": commit, "git_dirty": None if status is None else bool(status)}


def provenance(circuits=(), command: list[str] | None = None) -> dict:
    """What produced a report: the code's git commit (and whether the tree had changes), the command line,
    each circuit's name and SHA-256, and the versions of the packages that shape the numbers."""
    from importlib.metadata import PackageNotFoundError, version
    from digitalfly import __version__
    packages = {"digitalfly": __version__}
    for name in PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass
    code = code_version()
    named = []
    for name in dict.fromkeys(circuits):
        try:
            named.append({"name": name, "sha256": circuit_sha256(name)})
        except (OSError, ValueError) as exc:
            named.append({"name": name, "sha256": None, "error": str(exc)})
    return {"git_commit": code["git_commit"], "git_dirty": code["git_dirty"],
            "command": list(sys.argv if command is None else command), "circuits": named,
            "python": platform.python_version(), "platform": platform.platform(), "packages": packages}


def recorded_steps(duration_s: float) -> int:
    """Control steps in `duration_s` for an experiment that records every sample, checked against the recording
    limit before anything runs (the reset's sample counts too, so the longest run is 299.99 s)."""
    from digitalfly.simulation.experiment import RECORD_LIMIT
    steps = round(duration_s / CONTROL_DT)
    if steps > RECORD_LIMIT - 1:
        raise ValueError(f"{duration_s:g} simulated s does not fit the recording limit of {RECORD_LIMIT:,} samples: a "
                         f"recorded run lasts at most {(RECORD_LIMIT - 1) * CONTROL_DT:g} s.")
    return steps


def run_trial(config: RunConfig | dict, duration_s: float = 10.0, reach_mm: float = REACH_MM, turn_deg: float = TURN_DEG,
              trajectory_every: int = 0, experiment=None) -> dict:
    """One closed-loop trial from a reset: the configuration, behavior metrics (with `motor_clipped_fraction` for
    the connectome model) and, if asked, a trajectory sampled every `trajectory_every` control steps (10 ms each).
    Its own experiment keeps no per-sample recording (record=False), so a trial has no length limit; a recording
    `experiment` passed in is checked against its limit first. Recording never changes the results."""
    from digitalfly.simulation.experiment import Experiment
    config = config if isinstance(config, RunConfig) else RunConfig.model_validate(config)
    if experiment is not None and experiment.recording:
        recorded_steps(duration_s)
    exp = experiment or Experiment(config, render=False, record=False)
    try:
        if experiment is not None:
            exp.reset(config)
        if exp.status != "paused":
            raise RuntimeError(exp.error or "The experiment did not start.")
        goal = config.stimulus
        start = previous = exp.sample.pose.yaw
        net, reach_time, first_turn, yaw_rates, trajectory = 0., None, None, [], []
        for step in range(round(duration_s / CONTROL_DT)):
            exp.advance()
            pose = exp.sample.pose
            change = wrap(pose.yaw - previous)
            previous = pose.yaw
            net += change
            if exp.t <= 2 + 1e-9:
                yaw_rates.append(change / CONTROL_DT)
            if reach_time is None and math.hypot(goal.x - pose.x, goal.y - pose.y) <= reach_mm:
                reach_time = exp.t
            heading = wrap(pose.yaw - start)
            if first_turn is None and abs(math.degrees(heading)) >= turn_deg:
                first_turn = "left" if heading > 0 else "right"
            if trajectory_every and step % trajectory_every == 0:
                trajectory.append([round(exp.t, 4), round(pose.x, 4), round(pose.y, 4), round(pose.yaw, 5)])
        pose = exp.sample.pose
        bearing = describe_config(config)["target_bearing_deg"]
        lateral = abs(bearing) > 1e-6 and abs(abs(bearing) - 180) > 1e-6
        result = {**describe_config(config), "duration_s": duration_s, "reached": reach_time is not None,
                  "reach_time_s": reach_time, "first_turn": first_turn,
                  "first_turn_toward": (first_turn == "left") == (bearing > 0) if lateral and first_turn else None,
                  "final_distance_mm": math.hypot(goal.x - pose.x, goal.y - pose.y),
                  # Where the target sits relative to the final heading: about -90° while circling it clockwise.
                  "final_target_bearing_deg": math.degrees(wrap(math.atan2(goal.y - pose.y, goal.x - pose.x) - pose.yaw)),
                  "net_turn_deg": math.degrees(net),
                  "mean_yaw_rate_first_2s_deg_s": math.degrees(float(np.mean(yaw_rates))) if yaw_rates else 0.,
                  "mean_speed_mm_s": exp.metrics["mean_speed_mm_s"]}
        if exp.circuit.kind == "connectome":  # engineered diagnostic: control intervals with a clipped motor command
            result["motor_clipped_fraction"] = exp.circuit.motor_clipped_fraction
        if trajectory_every:
            result["trajectory"] = trajectory
        return result
    finally:
        if experiment is None:
            exp.close()


# run_trial's settings and their defaults, which a trial's config_hash includes.
TRIAL_SETTINGS = {name: p.default for name, p in inspect.signature(run_trial).parameters.items()
                  if name not in ("config", "experiment")}


def jumping_target_run(config: RunConfig | dict, duration_s: float = 60.0, every_s: float = 2.0, distance_mm: float = 10.0,
                       max_bearing_deg: float = 120.0, seed: int = 0, export_dir=None) -> dict:
    """A run whose target jumps to a new random bearing (±max_bearing_deg from the current heading) every
    `every_s` seconds, so turning varies in both directions; exported like an app run (for `compare`). The export
    needs the full recording, so `duration_s` must fit the recording limit (checked before the run starts)."""
    from digitalfly.simulation.experiment import Experiment
    config = config if isinstance(config, RunConfig) else RunConfig.model_validate(config)
    steps = recorded_steps(duration_s)
    rng = np.random.default_rng(seed)
    exp = Experiment(config, render=False)
    try:
        if exp.status != "paused":
            raise RuntimeError(exp.error or "The experiment did not start.")
        steps_per_jump = max(1, round(every_s / CONTROL_DT))
        for step in range(steps):
            if step % steps_per_jump == 0:
                pose = exp.sample.pose
                angle = pose.yaw + math.radians(rng.uniform(-max_bearing_deg, max_bearing_deg))
                x, y = pose.x + distance_mm * math.cos(angle), pose.y + distance_mm * math.sin(angle)
                exp.set_stimulus(Stimulus(x=round(min(40, max(-40, x)), 3), y=round(min(40, max(-40, y)), 3),
                                          intensity=config.stimulus.intensity))
            exp.advance()
        return exp.export(export_dir)
    finally:
        exp.close()


_experiments = {}


def _error_row(data: dict, kwargs: dict, error: str) -> dict:
    """The trial's settings, its whole configuration and the error. Describing it can fail for the same reason
    the trial did (a circuit that no longer loads), so that falls back to the raw configuration."""
    try:
        row = describe_config(RunConfig.model_validate(data))
    except Exception:
        stimulus = data.get("stimulus") or {}
        row = {"engine": data.get("engine"), "seed": data.get("seed"), "neural_model": data.get("neural_model"),
               "target_x_mm": stimulus.get("x"), "target_y_mm": stimulus.get("y")}
    try:
        row["config_hash"] = config_hash(data, **kwargs)
    except Exception:
        row["config_hash"] = None
    return {**row, "duration_s": kwargs.get("duration_s", 10.0), "error": error, "config": data}


def _run_in_worker(task):
    index, data, kwargs = task
    engine = data.get("engine")
    try:
        config = RunConfig.model_validate(data)
        exp = _experiments.get(engine)
        if exp is None:
            from digitalfly.simulation.experiment import Experiment
            exp = _experiments[engine] = Experiment(config, render=False, record=False)
        return index, {**run_trial(config, experiment=exp, **kwargs), "error": None,
                       "config_hash": config_hash(config, **kwargs)}
    except Exception as exc:
        broken = _experiments.pop(engine, None)  # the next trial starts from a fresh experiment
        if broken is not None:
            try:
                broken.close()
            except Exception:
                pass
        return index, _error_row(data, kwargs, f"{type(exc).__name__}: {exc}")


@contextmanager
def thread_limit(workers: int):
    """Cap OpenMP, MKL and OpenBLAS threads for worker processes started inside this block: the variables are
    set in this process before the workers spawn, so they inherit them before NumPy (or PyTorch) loads."""
    threads = str(max(1, (os.cpu_count() or 1) // max(workers, 1)))
    saved = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    os.environ.update({name: threads for name in THREAD_VARIABLES})
    try:
        yield int(threads)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _pool(workers: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))


def _log(message):
    print(message, file=sys.stderr, flush=True)


WORKER_DIED = ("BrokenProcessPool: its worker process died while running it, and again when it ran on its own "
               "(killed, or out of memory?)")


def _parallel(function, tasks, workers: int, finished, failed):
    """Run function(task) -> (index, result) for every task (index first) in `workers` spawned processes, calling
    finished(index, result) as each ends. A process holds one task at a time, so when one dies (killed, out of
    memory) and takes the pool down, the tasks that were running are known: each runs again on its own in a fresh
    process, the rest go on in a new pool, and only a task whose process dies again ends as failed(task, error
    text). A task whose process raises anything else ends as failed(task, error text) at once."""
    waiting, retry = deque(tasks), deque()
    while waiting or retry:
        alone = bool(retry)
        queue, size = (retry, 1) if alone else (waiting, workers)
        pool, running, broken = _pool(size), {}, False
        try:
            while running or (queue and not broken):
                while queue and not broken and len(running) < size:
                    task = queue.popleft()
                    try:
                        running[pool.submit(function, task)] = task
                    except BrokenProcessPool:
                        queue.appendleft(task)
                        broken = True
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    task = running.pop(future)
                    try:
                        result = future.result()
                    except BrokenProcessPool:
                        broken = True
                        if not alone:
                            retry.append(task)
                            continue
                        result = task[0], failed(task, WORKER_DIED)
                    except Exception as exc:
                        result = task[0], failed(task, f"{type(exc).__name__}: {exc}")
                    finished(*result)
            if broken and not alone:
                _log("A worker process died (killed, or out of memory?); " + (
                    f"rerunning the {len(retry)} task{'s' * (len(retry) > 1)} it took down, one at a time." if retry
                    else "carrying on in a new pool."))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)


def run_trials(configs: list[RunConfig | dict], workers: int = 1, on_result=None, **kwargs) -> list[dict]:
    """Many trials; the list follows the order of `configs`. With workers > 1 they run in separate processes;
    every trial starts from its own reset, so the results do not depend on the number of workers.

    A trial that raises gives a row with its settings, `config` and an `error` text (None on success) and
    the rest still run. A worker process that dies (killed, out of memory) costs no trials: the ones it took down
    run again, each on its own, and only a trial whose process dies again becomes an error row. `on_result(index,
    row)` is called as each trial finishes, in completion order, so callers can save results while a sweep runs.
    Every row carries `config_hash` (see `config_hash`)."""
    tasks = [(k, (c if isinstance(c, RunConfig) else RunConfig.model_validate(c)).model_dump(mode="json"), kwargs)
             for k, c in enumerate(configs)]
    rows = [None] * len(tasks)

    def finished(index, row):
        rows[index] = row
        if on_result is not None:
            on_result(index, row)
    if workers <= 1:
        try:
            for task in tasks:
                finished(*_run_in_worker(task))
        finally:
            for exp in _experiments.values():
                exp.close()
            _experiments.clear()
        return rows
    with thread_limit(workers):
        _parallel(_run_in_worker, tasks, workers, finished, lambda task, error: _error_row(task[1], kwargs, error))
    return rows


def write_csv(path, rows) -> list[str]:
    """Rows as CSV, leaving out list and dict values; returns the columns."""
    flat = [{k: v for k, v in r.items() if not isinstance(v, (list, dict))} for r in rows]
    fields = list(dict.fromkeys(k for r in flat for k in r))
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat)
    return fields


def with_ending(stem, ending: str) -> Path:
    """`stem` + `ending`, replacing only a .csv, .json or .jsonl ending: other dots belong to the name, so gain-1.5
    gives gain-1.5.json (Path.with_suffix would give gain-1.json)."""
    stem = Path(stem)
    stem = stem.with_suffix("") if stem.suffix in ENDINGS else stem
    return stem.with_name(stem.name + ending)


def _describe_code(code: dict | None) -> str:
    if not code:
        return "not recorded"
    return (f"digitalfly {code.get('digitalfly')}" + (f" at commit {code['git_commit'][:8]}" if code.get("git_commit") else "")
            + (" with uncommitted changes" if code.get("git_dirty") else ""))


class TrialLog:
    """Trial rows appended to <stem>.jsonl and <stem>.csv as they finish (pass `add` to run_trials' on_result), so
    a failing or interrupted sweep keeps every finished trial. The folder is made if needed; a .csv, .json or .jsonl
    ending of `stem` is dropped. With resume, rows already in the JSONL without an error are kept in `saved` by
    config hash, for the caller to skip; without it both files start empty. A line cut short by an interrupted write
    is skipped. Each JSONL line also records the code that computed it (`code`: digitalfly's version, the git commit
    and whether the tracked files had changes), and resuming reports, through `log`, saved rows from other code: the
    config hash covers the settings and the circuit, not the code, so those rows are reused all the same."""

    def __init__(self, stem, resume=False, log=_log):
        self.jsonl, self.csv = with_ending(stem, ".jsonl"), with_ending(stem, ".csv")
        self.jsonl.parent.mkdir(parents=True, exist_ok=True)
        self.code = code_version()
        self.saved, self.rows, self.fields = {}, [], []
        if resume and self.jsonl.is_file():
            text, torn, codes = self.jsonl.read_text(), 0, {}
            for line in filter(str.strip, text.splitlines()):
                try:
                    row = json.loads(line)
                except ValueError:
                    torn += 1
                    continue
                code = row.pop("code", None)
                if row.get("config_hash") and not row.get("error"):
                    self.saved[row["config_hash"]] = row
                    codes[row["config_hash"]] = code
            if text and not text.endswith("\n"):  # rows added from now on start on a line of their own
                with self.jsonl.open("a") as handle:
                    handle.write("\n")
            other = [code for code in codes.values() if code != self.code]
            if torn and log:
                log(f"Skipped {torn} unreadable line{'s' * (torn > 1)} in {self.jsonl} (an interrupted write?).")
            if other and log:
                log(f"{len(other)} of {len(codes)} saved rows were computed by other code "
                    f"({'; '.join(dict.fromkeys(map(_describe_code, other)))}) and are reused because their settings "
                    f"match; this is {_describe_code(self.code)}. Run without --resume (resume=False) to compute them again.")
        elif not resume:
            self.jsonl.unlink(missing_ok=True)
        self.rows = list(self.saved.values())
        if self.rows:
            self.fields = write_csv(self.csv, self.rows)
        else:
            self.csv.unlink(missing_ok=True)

    def add(self, row):
        with self.jsonl.open("a") as handle:
            handle.write(json.dumps({**row, "code": self.code}, default=str) + "\n")
        self.rows.append(row)
        flat = {k: v for k, v in row.items() if not isinstance(v, (list, dict))}
        if not self.fields or set(flat) - set(self.fields):  # a new column: rewrite with the wider header
            self.fields = write_csv(self.csv, self.rows)
            return
        with self.csv.open("a", newline="") as handle:
            csv.DictWriter(handle, fieldnames=self.fields).writerow(flat)

    def rows_for(self, hashes) -> list[dict]:
        """The latest row, saved or added, for each config hash in `hashes`, in their order (hashes without a row are
        left out): the rows of one sweep, when the log also holds other seeds, durations or settings."""
        latest = {row.get("config_hash"): row for row in self.rows}
        return [latest[h] for h in hashes if h in latest]


def hold(parameters: ConnectomeParameters, left: float, right: float, ms: int = 500,
         interventions: Interventions | None = None, seed: int = 0, average_ms: int = 0) -> dict:
    """Open loop: clamp the two sensor values for `ms` milliseconds and report the circuit's output,
    averaged over the last `average_ms` (useful for spiking dynamics)."""
    model = ConnectomeCircuit(parameters)
    model.reset(seed)
    sensors, interventions = SensorState(left=left, right=right), interventions or Interventions()
    turns, readouts = [], []
    for step in range(ms):
        model.advance(sensors, interventions)
        if step >= ms - max(average_ms, 1):
            turns.append(model.turn())
            readouts.append(model.readout())
    return {"left": left, "right": right, "turn": float(np.mean(turns)), "forward": model.forward(),
            "readout": dict(zip(model.unit_names, np.mean(readouts, axis=0).round(6).tolist()))}


def bias_curve(parameters: ConnectomeParameters, levels=(.25, .5, .75, 1.), differences=(-.4, -.2, 0., .2, .4),
               ms: int = 500, average_ms: int = 0, seed: int = 0) -> dict:
    """Turn commands over a grid of sensor inputs, and the mirror test: a left-right symmetric circuit gives
    turn(a, b) = −turn(b, a), so turn(x, x) = 0. Positive turns are rightward."""
    rows = []
    for level, difference in itertools.product(levels, differences):
        left, right = level - difference / 2, level + difference / 2
        if 0 <= left <= 1 and 0 <= right <= 1:
            rows.append({"level": level, "right_minus_left": difference,
                         **hold(parameters, left, right, ms, seed=seed, average_ms=average_ms)})
    turn = {(r["level"], r["right_minus_left"]): r["turn"] for r in rows}
    mirror = [abs(turn[(lv, d)] + turn[(lv, -d)]) for lv, d in turn if d > 0 and (lv, -d) in turn]
    span = max(abs(t) for t in turn.values()) or 1.
    return {"rows": rows,
            "equal_input_turn": {lv: turn[(lv, 0.)] for lv, d in turn if d == 0},
            "mirror_asymmetry": float(np.mean(mirror) / span) if mirror else None,
            "note": "Positive turn = rightward. equal_input_turn ≠ 0 or mirror_asymmetry > 0 means a side bias."}


def _ablate(task):
    """(cell type, turn, error): one type's manipulation under clamped input, or none for the intact circuit. An
    exception becomes the error text, so one failing type never ends a scan."""
    parameters, cell_type, left, right, ms, average_ms, seed, mode, side, value = task
    try:
        parameters = ConnectomeParameters.model_validate(parameters)
        if cell_type is None:
            interventions = Interventions()
        elif mode == "silence" and side == "both":  # the v0.5 scan, unchanged
            interventions = Interventions.model_construct(**{**Interventions().model_dump(), "silence_types": [cell_type]})
        else:
            interventions = Interventions(cell_types=[CellTypeIntervention(name=cell_type, side=side, mode=mode, value=value)])
        return cell_type, hold(parameters, left, right, ms, interventions, seed, average_ms)["turn"], None
    except Exception as exc:
        return cell_type, None, f"{type(exc).__name__}: {exc}"


def ablation_scan(parameters: ConnectomeParameters, left: float = .5, right: float = .5, ms: int = 400,
                  cell_types: list[str] | None = None, workers: int = 1, average_ms: int = 0, seed: int = 0,
                  mode: str = "silence", value: float = 0., side: str = "both") -> dict:
    """Manipulate each cell type in turn under fixed sensor input, and rank the types by how much the turn
    command changes. The default silences all of a type's neurons (both sides); `mode` "scale" multiplies their
    output by `value` (0–2) and "activate" drives them at `value`, which must be above 0 (Hz in spiking dynamics,
    a clamped rate up to 1 in rate dynamics); `side` "left" or "right" manipulates one side only, and skips types
    with no neurons there.
    With equal input on both sides, silencing finds the types that create a side bias: a positive change means
    the type was pushing the fly to the left. A type whose run fails gets a row with an `error` text. The readout
    types are never scanned, and naming one in `cell_types` is refused."""
    if mode not in ("silence", "scale", "activate") or side not in ("both", "left", "right"):
        raise ValueError("Choose mode silence, scale or activate and side both, left or right.")
    if mode == "activate" and not value > 0:
        raise ValueError("Activation needs a value above 0: Hz in spiking dynamics, a clamped rate in rate dynamics.")
    # A value the mode or dynamics cannot take fails before the scan, naming the types it would manipulate.
    check = CellTypeIntervention(name="probe", side=side, mode=mode, value=value)
    named = [check.model_copy(update={"name": n}) for n in cell_types or ["every cell type"]]
    Interventions.model_construct(cell_types=named).for_dynamics(parameters.dynamics)
    data = load_circuit(parameters.circuit)
    unknown = [n for n in cell_types or [] if n not in data.type_members]
    if unknown:
        raise ValueError(f"Not a cell type in the {data.key} circuit: {', '.join(unknown)}.")
    readout = set(parameters.readout_types or data.defaults["readout_types"])
    if readout & set(cell_types or []):
        raise ValueError("Readout types are not scanned, since the turn is read from them: "
                         f"{', '.join(n for n in cell_types if n in readout)}.")
    absent = [n for n in cell_types or [] if side != "both" and not len(data.members(n, side))]
    if absent:
        raise ValueError(f"No {side} neurons in the {data.key} circuit: {', '.join(absent)}.")
    names = [n for n in (cell_types or data.type_names) if n not in readout]
    skipped = [n for n in names if side != "both" and not len(data.members(n, side))]
    names = [n for n in names if n not in skipped]
    tasks = [(parameters.model_dump(), name, left, right, ms, average_ms, seed, mode, side, value) for name in [None] + names]
    if workers > 1:
        with thread_limit(workers), _pool(workers) as pool:
            results = list(pool.map(_ablate, tasks, chunksize=16))
    else:
        results = [_ablate(task) for task in tasks]
    intact, error = results[0][1:]
    if error:
        raise RuntimeError(f"The intact circuit could not run: {error}")
    rows = []
    for name, turn, error in results[1:]:
        members = data.members(name)
        rows.append({"cell_type": name, "neurons": int(len(members)), "left": int((data.side[members] == "left").sum()),
                     "right": int((data.side[members] == "right").sum()), "turn": turn,
                     "change": None if error else turn - intact, "error": error})
    rows.sort(key=lambda r: (r["error"] is not None, -abs(r["change"] or 0)))
    done = {"silence": "silenced", "scale": f"output scaled ×{value:g}",
            "activate": f"activated at {value:g} Hz" if parameters.dynamics == "spiking" else f"clamped at rate {value:g}"}[mode]
    note = ("change = turn with the type silenced − intact turn; positive = the type pushed the fly to the left."
            if mode == "silence" and side == "both" else
            f"change = turn with the type {done}{'' if side == 'both' else f' on the {side}'} − intact turn; "
            "positive = a rightward shift.")
    return {"circuit": data.key, "dynamics": parameters.dynamics, "left": left, "right": right, "mode": mode,
            "side": side, "value": None if mode == "silence" else value, "intact_turn": intact,
            "types_scanned": len(rows), "errors": sum(r["error"] is not None for r in rows), "skipped": skipped,
            "rows": rows, "note": note}


def wilson_interval(successes: int, n: int, level: float = .95) -> tuple[float, float] | None:
    """Wilson score interval for a fraction successes/n; better than the normal approximation for small n
    and fractions near 0 or 1."""
    if n <= 0:
        return None
    z = NormalDist().inv_cdf(.5 + level / 2)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return 0. if successes == 0 else max(0., centre - half), 1. if successes == n else min(1., centre + half)


def bootstrap_interval(values, resamples: int = BOOTSTRAP["resamples"], level: float = BOOTSTRAP["level"],
                       seed: int = BOOTSTRAP["seed"]) -> tuple[float, float] | None:
    """Percentile bootstrap interval for the mean: `resamples` resamples with replacement from a generator
    seeded with `seed`, so the same values always give the same interval. None for fewer than 2 values."""
    values = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(resamples, len(values)))].mean(axis=1)
    low, high = np.quantile(means, [(1 - level) / 2, (1 + level) / 2])
    return float(low), float(high)


def summarize(rows: list[dict], by: list[str], match=("seed", "target_bearing_deg", "target_distance_mm"),
              metrics=("final_distance_mm", "mean_speed_mm_s", "net_turn_deg")) -> dict:
    """Per condition (the values of the `by` columns): trial and error counts, reaching and first turns
    toward lateral targets with Wilson intervals, and metric means with bootstrap intervals. Then, for every
    condition after the first, paired differences from the first over trials that share the `match` columns
    (matched seeds and targets): reaching (as 0/1) and each metric, with bootstrap intervals. Rows with an
    error are counted but left out of every statistic."""
    def key(row):
        return tuple(row.get(k) for k in by)

    match = [k for k in match if k not in by]
    groups = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    conditions = []
    for condition, group in groups.items():
        ok = [r for r in group if not r.get("error")]
        lateral = [r for r in ok if abs(r["target_bearing_deg"]) > 1e-6 and abs(abs(r["target_bearing_deg"]) - 180) > 1e-6]
        reached = sum(bool(r["reached"]) for r in ok)
        toward = sum(r["first_turn_toward"] is True for r in lateral)
        item = {"condition": dict(zip(by, condition)), "trials": len(group), "errors": len(group) - len(ok),
                "reached": reached, "reached_fraction": reached / len(ok) if ok else None,
                "reached_ci95": wilson_interval(reached, len(ok)),
                "first_turn_toward": toward, "lateral_trials": len(lateral),
                "first_turn_toward_ci95": wilson_interval(toward, len(lateral))}
        for metric in metrics:
            values = [r[metric] for r in ok if r.get(metric) is not None]
            item[metric] = {"mean": float(np.mean(values)) if values else None,
                            "median": float(np.median(values)) if values else None,
                            "ci95": bootstrap_interval(values)}
        conditions.append(item)
    paired = []
    if len(groups) > 1:
        names = list(groups)
        base = {tuple(r.get(k) for k in match): r for r in groups[names[0]] if not r.get("error")}
        for condition in names[1:]:
            pairs = [(base[m], r) for r in groups[condition] if not r.get("error")
                     if (m := tuple(r.get(k) for k in match)) in base]
            item = {"condition": dict(zip(by, condition)), "baseline": dict(zip(by, names[0])), "pairs": len(pairs)}
            for metric in ("reached",) + tuple(metrics):
                diffs = [float(b[metric]) - float(a[metric]) for a, b in pairs
                         if a.get(metric) is not None and b.get(metric) is not None]
                item[metric] = {"mean_difference": float(np.mean(diffs)) if diffs else None,
                                "ci95": bootstrap_interval(diffs)}
            paired.append(item)
    return {"by": list(by), "matched_on": list(match), "conditions": conditions, "paired_differences": paired,
            "methods": {"fractions": "Wilson score interval, 95%",
                        "means": f"percentile bootstrap, {BOOTSTRAP['resamples']} resamples, numpy default_rng seed "
                                 f"{BOOTSTRAP['seed']}, 95%",
                        "paired": "condition − first condition over trials with the same "
                                  f"{', '.join(match)}; reached counts as 1 or 0",
                        "errors": "rows with an error are excluded from every statistic"}}
