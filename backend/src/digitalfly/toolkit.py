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
"""
from concurrent.futures import ProcessPoolExecutor
import itertools
import math
import multiprocessing
import numpy as np
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, SensorState, Stimulus
from digitalfly.neural.connectome import ConnectomeCircuit, load_circuit
from digitalfly.simulation.engines import CONTROL_DT

REACH_MM = 2.0
TURN_DEG = 10.0  # a turn counts once the heading has changed this much from the start


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
        node = data
        *parents, last = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value.model_dump() if hasattr(value, "model_dump") else value
    return RunConfig.model_validate(data)


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
           "target_distance_mm": round(math.hypot(config.stimulus.x, config.stimulus.y), 6)}
    if config.neural_model == "connectome":
        row.update({"circuit": p.circuit, "dynamics": p.dynamics,
                    "readout_types": "+".join(p.readout_types or load_circuit(p.circuit).defaults["readout_types"]),
                    "speed_types": "+".join(p.speed_types), "output_gain": p.output_gain, "global_gain": p.global_gain})
    i = config.initial_interventions
    row["silenced"] = "+".join([f"DNa02 {i.silence_dna02}"] * (i.silence_dna02 != "none") + i.silence_types
                               + [f"{i.silence} units"] * (i.silence != "none")) or "none"
    return row


def run_trial(config: RunConfig | dict, duration_s: float = 10.0, reach_mm: float = REACH_MM, turn_deg: float = TURN_DEG,
              trajectory_every: int = 0, experiment=None) -> dict:
    """One closed-loop trial from a reset: the configuration, behavior metrics and, if asked, a trajectory
    sampled every `trajectory_every` control steps (10 ms each)."""
    from digitalfly.simulation.experiment import Experiment
    config = config if isinstance(config, RunConfig) else RunConfig.model_validate(config)
    exp = experiment or Experiment(config, render=False)
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
        if trajectory_every:
            result["trajectory"] = trajectory
        return result
    finally:
        if experiment is None:
            exp.close()


def jumping_target_run(config: RunConfig | dict, duration_s: float = 60.0, every_s: float = 2.0, distance_mm: float = 10.0,
                       max_bearing_deg: float = 120.0, seed: int = 0, export_dir=None) -> dict:
    """A run whose target jumps to a new random bearing (±max_bearing_deg from the current heading) every
    `every_s` seconds, so turning varies in both directions; exported like an app run (for `compare`)."""
    from digitalfly.simulation.experiment import Experiment
    config = config if isinstance(config, RunConfig) else RunConfig.model_validate(config)
    rng = np.random.default_rng(seed)
    exp = Experiment(config, render=False)
    try:
        if exp.status != "paused":
            raise RuntimeError(exp.error or "The experiment did not start.")
        steps_per_jump = max(1, round(every_s / CONTROL_DT))
        for step in range(round(duration_s / CONTROL_DT)):
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


def _run_in_worker(task):
    config, kwargs = task
    config = RunConfig.model_validate(config)
    exp = _experiments.get(config.engine)
    if exp is None:
        from digitalfly.simulation.experiment import Experiment
        exp = _experiments[config.engine] = Experiment(config, render=False)
    return run_trial(config, experiment=exp, **kwargs)


def _limit_threads(threads: int):
    # Before PyTorch (FlyVis) or BLAS start their thread pools in a worker process.
    import os
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = str(threads)


def run_trials(configs: list[RunConfig | dict], workers: int = 1, **kwargs) -> list[dict]:
    """Many trials, in order. With workers > 1 they run in separate processes; every trial starts from its
    own reset, so the results do not depend on the number of workers."""
    tasks = [((c if isinstance(c, RunConfig) else RunConfig.model_validate(c)).model_dump(), kwargs) for c in configs]
    if workers <= 1:
        try:
            return [_run_in_worker(task) for task in tasks]
        finally:
            for exp in _experiments.values():
                exp.close()
            _experiments.clear()
    import os
    threads = max(1, (os.cpu_count() or 1) // workers)
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=_limit_threads, initargs=(threads,)) as pool:
        return list(pool.map(_run_in_worker, tasks, chunksize=max(1, len(tasks) // (workers * 4))))


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
    parameters, cell_type, left, right, ms, average_ms, seed = task
    parameters = ConnectomeParameters.model_validate(parameters)
    silence = Interventions.model_construct(**{**Interventions().model_dump(), "silence_types": [cell_type] if cell_type else []})
    return cell_type, hold(parameters, left, right, ms, silence, seed, average_ms)["turn"]


def ablation_scan(parameters: ConnectomeParameters, left: float = .5, right: float = .5, ms: int = 400,
                  cell_types: list[str] | None = None, workers: int = 1, average_ms: int = 0, seed: int = 0) -> dict:
    """Silence each cell type in turn (all of its neurons, both sides) under fixed sensor input, and rank
    the types by how much the turn command changes. With equal input on both sides this finds the types
    that create a side bias: a positive change means the type was pushing the fly to the left."""
    data = load_circuit(parameters.circuit)
    readout = set(parameters.readout_types or data.defaults["readout_types"])
    names = [n for n in (cell_types or data.type_names) if n not in readout]
    tasks = [(parameters.model_dump(), name, left, right, ms, average_ms, seed) for name in [None] + names]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(_ablate, tasks, chunksize=16))
    else:
        results = [_ablate(task) for task in tasks]
    intact = results[0][1]
    rows = []
    for name, turn in results[1:]:
        members = data.members(name)
        rows.append({"cell_type": name, "neurons": int(len(members)), "left": int((data.side[members] == "left").sum()),
                     "right": int((data.side[members] == "right").sum()), "turn": turn, "change": turn - intact})
    rows.sort(key=lambda r: -abs(r["change"]))
    return {"circuit": data.key, "dynamics": parameters.dynamics, "left": left, "right": right, "intact_turn": intact,
            "types_scanned": len(rows), "rows": rows,
            "note": "change = turn with the type silenced − intact turn; positive = the type pushed the fly to the left."}
