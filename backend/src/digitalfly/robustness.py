"""Assumption sensitivity: rerun an analysis under several modelling assumptions and report which conclusions survive.

    from digitalfly import robustness
    from digitalfly.api.models import ConnectomeParameters
    variants = robustness.variants(ConnectomeParameters(circuit="fafb783-steering"),
                                   {"other_transmitters": ["excluded", "excitatory"], "synapse_threshold": [5, 10, 20]})
    rows = robustness.run(variants, analyses=("bias", "readouts"), workers=2)
    robustness.survival(rows, list(variants[0]["settings"]))

Each assumption varied here is an existing global parameter of the connectome model (the transmitter sign rule,
the synapse threshold, readout pooling and weights, rate or spiking dynamics, the circuit itself, the seed). The
analyses are the open-loop bias curve and mirror test (`toolkit.bias_curve`), the turn command for a target held
at fixed bearings (`readout_table`, the table "What the circuits compute") and, optionally, a short closed-loop
reach evaluation on the toy body. Each variant's results are reduced to qualitative conclusions (which way it
turns, whether it reaches targets) and compared with the first variant, the baseline. A conclusion that holds in
every variant is robust to the assumptions varied, and no more: it is still a property of this model on this
wiring, not evidence about flies.
"""
from collections import Counter
import hashlib
import itertools
import json
import numpy as np
from digitalfly import toolkit
from digitalfly.api.models import ConnectomeParameters, Interventions, Pose

ANALYSES = ("bias", "readouts", "reach")
DEFAULT_AXES = {"other_transmitters": ["excluded", "excitatory"], "synapse_threshold": [5, 10, 20],
                "dynamics": ["rate", "spiking"]}
# Milliseconds of clamped input and of the final averaging window, as in the published tables: the bias table's 500 ms
# (rate) and 800 ms averaged over the last 400 ms (spiking); "What the circuits compute" reads rates at 600 ms.
HOLD_MS = {"bias": {"rate": (500, 0), "spiking": (800, 400)}, "readouts": {"rate": (600, 0), "spiking": (800, 400)}}
BEARINGS = (45, 90, 0, -45, -90)  # positive = left, as in toolkit.target
TOLERANCE = .01  # a turn command smaller than this either way counts as no turn
REACH = {"bearings": (45, -45, 90, -90), "distance_mm": 12., "seeds": (1, 2, 3), "duration_s": 5.}
SCOPE = ("Properties of this model under each assumption, on FlyWire v783 wiring with assumed signs and engineered "
         "input and output; not evidence about flies.")


def direction(turn: float, tolerance: float = TOLERANCE) -> str:
    """'right' or 'left' (positive turn commands are rightward), or 'none' within the tolerance."""
    return "right" if turn > tolerance else "left" if turn < -tolerance else "none"


def target_label(bearing: float) -> str:
    bearing = (bearing + 180) % 360 - 180
    if bearing == 0:
        return "Ahead"
    if abs(bearing) == 180:
        return "Behind"
    return f"{abs(bearing):g}° {'left' if bearing > 0 else 'right'}"


def readout_table(parameters: ConnectomeParameters, bearings=BEARINGS, distance_mm: float = 12., intensity: float = 1.,
                  ms: int = 600, average_ms: int = 0, seed: int = 0, tolerance: float = TOLERANCE) -> dict:
    """Open loop, as in "What the circuits compute": the fly at the origin facing +x, the target held still at each
    bearing (positive = left) and distance; the geometric sensor's two values are clamped for `ms` milliseconds,
    then each readout type's right − left activity and the turn command are read (averaged over the last
    `average_ms`). A lateral target's turn is "toward" when it goes to the target's side."""
    from digitalfly.neural.connectome import load_circuit
    from digitalfly.neural.model import encode
    types = parameters.readout_types or load_circuit(parameters.circuit).defaults["readout_types"]
    still = Pose(x=0, y=0, z=.7, yaw=0, velocity=0)
    rows = []
    for bearing in bearings:
        sensors = encode(still, toolkit.target(bearing, distance_mm, intensity), Interventions())
        held = toolkit.hold(parameters, sensors.left, sensors.right, ms, seed=seed, average_ms=average_ms)
        way = direction(held["turn"], tolerance)
        lateral = target_label(bearing) not in ("Ahead", "Behind")
        rows.append({"bearing_deg": bearing, "target": target_label(bearing), "sensor_left": sensors.left,
                     "sensor_right": sensors.right,
                     "right_minus_left": {t: held["readout"][f"{t} R"] - held["readout"][f"{t} L"] for t in types},
                     "turn": held["turn"], "direction": way,
                     "toward": ((way == "left") == (bearing > 0)) if lateral and way != "none" else None})
    return {"circuit": parameters.circuit, "dynamics": parameters.dynamics, "readout_types": list(types),
            "distance_mm": distance_mm, "intensity": intensity, "ms": ms, "average_ms": average_ms, "seed": seed,
            "rows": rows, "note": "Positive turn = rightward; positive bearing = left. Open loop: the fly does not move."}


def variants(base: ConnectomeParameters, axes: dict | None = None, seed: int = 0) -> list[dict]:
    """Every combination of the axes' values on top of `base`, the first value of each axis first (that combination
    is the baseline). Axis names are ConnectomeParameters fields, dotted for nested ones (spiking.rate_scale_hz),
    or `seed`: the seed of spiking open-loop analyses and, when it is an axis, the only seed of the reach trials."""
    axes = DEFAULT_AXES if axes is None else axes
    names = list(axes)
    result = []
    for values in itertools.product(*(axes[n] for n in names)):
        data, variant_seed = base.model_dump(), seed
        for name, value in zip(names, values):
            if name == "seed":
                variant_seed = int(value)
            else:
                toolkit.set_setting(data, name, value)  # readout_weights.DNa02 fills an unset readout_weights
        result.append({"settings": dict(zip(names, values)), "parameters": ConnectomeParameters.model_validate(data),
                       "seed": variant_seed, "seed_axis": "seed" in names})
    return result


def variant_hash(variant: dict, analyses, settings: dict) -> str:
    """A short identity of one variant's computation, including the circuit file's SHA-256 (for --resume)."""
    p = variant["parameters"]
    text = json.dumps({"parameters": p.model_dump(mode="json"), "seed": variant["seed"],
                       "seed_axis": variant["seed_axis"], "analyses": sorted(analyses), "settings": settings,
                       "circuit_sha256": toolkit.circuit_sha256(p.circuit)}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _share(count: int, n: int) -> str:
    return "n/a" if not n else "none" if count == 0 else "all" if count == n else "most" if count > n / 2 else "some"


def _hold_ms(analysis: str, dynamics: str, settings: dict):
    """The analysis's documented hold for these dynamics, unless `ms` (and `average_ms`) override it."""
    if settings.get("ms"):
        return settings["ms"], settings.get("average_ms") or 0
    return HOLD_MS[analysis][dynamics]


def evaluate(variant: dict, analyses=("bias",), **settings) -> dict:
    """One variant: its measures (numbers) and conclusions (categories) for each analysis. `settings`: tolerance,
    ms and average_ms (instead of HOLD_MS), bearings and distance_mm (readouts), and reach_bearings,
    reach_distance_mm, reach_seeds and reach_duration_s (reach)."""
    p, seed = variant["parameters"], variant["seed"]
    tolerance = settings.get("tolerance", TOLERANCE)
    result = {}
    if "bias" in analyses:
        ms, average = _hold_ms("bias", p.dynamics, settings)
        curve = toolkit.bias_curve(p, ms=ms, average_ms=average, seed=seed)
        turn = {(r["level"], r["right_minus_left"]): r["turn"] for r in curve["rows"]}
        result.update({"equal_input_turn": turn[(.5, 0.)], "turn_target_right": turn[(.5, .4)],
                       "turn_target_left": turn[(.5, -.4)], "mirror_asymmetry": curve["mirror_asymmetry"],
                       "equal_input_direction": direction(turn[(.5, 0.)], tolerance),
                       "target_right_direction": direction(turn[(.5, .4)], tolerance),
                       "target_left_direction": direction(turn[(.5, -.4)], tolerance)})
    if "readouts" in analyses:
        ms, average = _hold_ms("readouts", p.dynamics, settings)
        table = readout_table(p, settings.get("bearings", BEARINGS), settings.get("distance_mm", 12.), ms=ms,
                              average_ms=average, seed=seed, tolerance=tolerance)
        turns = {r["bearing_deg"]: r["turn"] for r in table["rows"]}
        result["readouts"] = table["rows"]
        for b, t in turns.items():
            result[f"turn_at_{b:g}"] = t
            result[f"direction_at_{b:g}"] = direction(t, tolerance)
        if 0 in turns and any(b not in (0, 180, -180) for b in turns):
            # Moving the target off the midline shifts the command toward its side: lower (more leftward) for left.
            result["shifts_toward_target"] = "yes" if all((t < turns[0]) == (b > 0) for b, t in turns.items()
                                                           if b not in (0, 180, -180)) else "no"
    if "reach" in analyses:
        seeds = [seed] if variant["seed_axis"] else list(settings.get("reach_seeds", REACH["seeds"]))
        configs = [toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": s,
                                      "connectome_parameters": p.model_dump(),
                                      "stimulus": toolkit.target(b, settings.get("reach_distance_mm", REACH["distance_mm"]))})
                   for b in settings.get("reach_bearings", REACH["bearings"]) for s in seeds]
        rows = toolkit.run_trials(configs, duration_s=settings.get("reach_duration_s", REACH["duration_s"]))
        failed = [r["error"] for r in rows if r["error"]]
        if failed:
            raise RuntimeError(f"{len(failed)} of {len(rows)} reach trials failed: {failed[0]}")
        lateral = [r for r in rows if abs(r["target_bearing_deg"]) > 1e-6 and abs(abs(r["target_bearing_deg"]) - 180) > 1e-6]
        reached, toward = sum(r["reached"] for r in rows), sum(r["first_turn_toward"] is True for r in lateral)
        result.update({"reached": reached, "reach_trials": len(rows), "first_turns_toward": toward,
                       "lateral_trials": len(lateral),
                       "median_final_distance_mm": float(np.median([r["final_distance_mm"] for r in rows])),
                       "reaching": _share(reached, len(rows)), "first_turn_toward": _share(toward, len(lateral))})
    return result


CONCLUSIONS = {
    "equal_input_direction": "Turn with equal input (0.5 / 0.5)",
    "target_right_direction": "Turn with the target on the right (input 0.3 / 0.7)",
    "target_left_direction": "Turn with the target on the left (input 0.7 / 0.3)",
    "shifts_toward_target": "Moving the target off the midline shifts the turn toward its side",
    "reaching": "Share of reach trials ending within 2 mm",
    "first_turn_toward": "Share of first turns toward lateral targets",
}


def conclusion_names(rows: list[dict]) -> list[str]:
    """The conclusions the rows hold, in a fixed order: the bias curve's, then each bearing's, then the rest."""
    present = list(dict.fromkeys(k for r in rows for k in r if k in CONCLUSIONS or k.startswith("direction_at_")))
    order = list(CONCLUSIONS)
    return sorted(present, key=lambda k: (order.index(k) if k in order else 2.5, present.index(k)))


def describe(name: str) -> str:
    if name.startswith("direction_at_"):
        return f"Turn with the target {target_label(float(name.removeprefix('direction_at_'))).lower()}"
    return CONCLUSIONS[name]


def _row(index: int, variant: dict, h: str) -> dict:
    p = variant["parameters"]
    shown = {k: json.dumps(v) if isinstance(v, (list, dict)) or v is None else v for k, v in variant["settings"].items()}
    return {"variant": index, **shown, "circuit": p.circuit, "dynamics": p.dynamics, "seed": variant["seed"],
            "config_hash": h, "parameters": p.model_dump(mode="json")}


def _evaluate_task(task):
    index, data, analyses, settings = task
    variant = {**data, "parameters": ConnectomeParameters.model_validate(data["parameters"])}
    try:
        h = variant_hash(variant, analyses, settings)
    except Exception:
        h = None
    row = _row(index, variant, h)
    try:
        row["circuit_sha256"] = toolkit.circuit_sha256(variant["parameters"].circuit)
        return index, {**row, **evaluate(variant, analyses, **settings), "error": None}
    except Exception as exc:
        return index, {**row, "error": f"{type(exc).__name__}: {exc}"}


def run(variants: list[dict], analyses=("bias",), workers: int = 1, on_result=None, **settings) -> list[dict]:
    """Evaluate every variant; rows follow the order of `variants`. A variant that raises becomes a row with its
    settings and an `error` text, and the rest still run; a worker process that dies costs no variants (as in
    `toolkit.run_trials`). `on_result(index, row)` is called as each finishes."""
    unknown = set(analyses) - set(ANALYSES)
    if unknown or not analyses:
        raise ValueError(f"Choose analyses from {', '.join(ANALYSES)}.")
    tasks = [(k, {**v, "parameters": v["parameters"].model_dump(mode="json")}, tuple(analyses), settings)
             for k, v in enumerate(variants)]
    rows = [None] * len(tasks)

    def finished(index, row):
        rows[index] = row
        if on_result is not None:
            on_result(index, row)
    if workers <= 1:
        for task in tasks:
            finished(*_evaluate_task(task))
        return rows
    def failed(task, error):  # the worker process died running it twice, or could not return it
        index, data, _, _ = task
        return {**_row(index, {**data, "parameters": ConnectomeParameters.model_validate(data["parameters"])}, None),
                "error": error}
    with toolkit.thread_limit(workers):
        toolkit._parallel(_evaluate_task, tasks, workers, finished, failed)
    return rows


def survival(rows: list[dict], axes: list[str]) -> list[dict]:
    """For each conclusion: its value in the baseline (the first variant), how many variants share it, which
    differ and, when every differing variant shares an axis value, that value (`differs_only_with`). Failed
    variants are left out; with a failed baseline nothing can be compared."""
    ok = [r for r in rows if not r.get("error")]
    baseline = rows[0] if rows and not rows[0].get("error") else None
    result = []
    for name in conclusion_names(ok):
        base = baseline.get(name) if baseline else None
        differ = [r for r in ok if r.get(name) != base]
        common = {a: differ[0][a] for a in axes if differ and len({json.dumps(r.get(a), default=str) for r in differ}) == 1}
        # Only an axis value that the agreeing variants never take explains the difference.
        common = {a: v for a, v in common.items() if all(r.get(a) != v for r in ok if r.get(name) == base)}
        result.append({"conclusion": name, "description": describe(name), "baseline": base,
                       "holds": len(ok) - len(differ), "variants": len(ok),
                       "survives": baseline is not None and not differ,
                       "values": dict(Counter(str(r.get(name)) for r in ok)),
                       "differs_in": [r["variant"] for r in differ], "differs_only_with": common})
    return result


def report(rows: list[dict], axes: list[str], **context) -> dict:
    return {"command": "robustness", **context, "axes": axes, "baseline_variant": 0,
            "errors": sum(bool(r.get("error")) for r in rows), "survival": survival(rows, axes), "variants": rows,
            "hold_ms": HOLD_MS, "scope": SCOPE,
            "method": "Each conclusion is a category (turn direction with a tolerance on the turn command; share of trials "
                      "as none/some/most/all) compared with the baseline variant's."}
