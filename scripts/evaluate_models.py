"""Matched-seed behavior of the engineered and connectome models.

Targets sit ahead, at ±45°, at ±90° and directly behind the starting heading, at 12 mm and
30 mm. Each trial records whether the fly came within 2 mm of the target and when, whether
its first clear turn went toward the target, and its final distance. A second set silences
DNa02 left, right or both in the connectome model and measures the change in turning.

    backend/.venv/bin/python scripts/evaluate_models.py --engine toy
    backend/.venv/bin/python scripts/evaluate_models.py --engine flygym --quick

Every run starts from the default configuration and changes only the target, seed, model and
silencing. Results describe this simulation, not fly behavior. A JSON report goes to the
ignored docs/evidence/ folder; Markdown tables are printed.
"""
import argparse
import json
import math
from pathlib import Path
import platform
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly.api.models import Interventions, RunConfig, Stimulus  # noqa: E402
from digitalfly.simulation.engines import CONTROL_DT  # noqa: E402
from digitalfly.simulation.experiment import Experiment  # noqa: E402

MODELS = {"engineered": "Engineered", "connectome_dna02": "Connectome"}
BEARINGS = [0, 45, -45, 90, -90, 180]
DISTANCES = [12, 30]
SEEDS = [1, 2, 3, 4, 5]
REACH_MM = 2.0
TURN_DEG = 10.0  # A turn counts once heading has changed this much from the start.


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def trial(exp, engine, model, bearing, distance, seed, duration, silence="none"):
    angle = math.radians(bearing)
    target = Stimulus(x=round(distance * math.cos(angle), 6), y=round(distance * math.sin(angle), 6))
    exp.reset(RunConfig(engine=engine, seed=seed, neural_model=model, stimulus=target,
                        initial_interventions=Interventions(silence_dna02=silence)))
    if exp.status != "paused":
        raise RuntimeError(exp.error)
    start_yaw, previous = exp.sample.pose.yaw, exp.sample.pose.yaw
    heading_change = reach_time = first_turn = None
    net = 0.
    yaw_rates = []
    for _ in range(round(duration / CONTROL_DT)):
        exp.advance()
        pose = exp.sample.pose
        step = wrap(pose.yaw - previous)
        previous = pose.yaw
        net += step
        if exp.t <= 2 + 1e-9:
            yaw_rates.append(step / CONTROL_DT)
        if reach_time is None and math.hypot(target.x - pose.x, target.y - pose.y) <= REACH_MM:
            reach_time = exp.t
        heading_change = wrap(pose.yaw - start_yaw)
        if first_turn is None and abs(math.degrees(heading_change)) >= TURN_DEG:
            first_turn = "left" if heading_change > 0 else "right"
    pose = exp.sample.pose
    toward = None if bearing in (0, 180) or first_turn is None else (first_turn == "left") == (bearing > 0)
    return {"engine": engine, "model": model, "bearing_deg": bearing, "distance_mm": distance, "seed": seed,
            "silence_dna02": silence, "duration_s": duration, "reached": reach_time is not None,
            "reach_time_s": reach_time, "first_turn": first_turn, "first_turn_toward": toward,
            "final_distance_mm": math.hypot(target.x - pose.x, target.y - pose.y),
            "net_turn_deg": math.degrees(net), "mean_yaw_rate_first_2s_deg_s": math.degrees(float(np.mean(yaw_rates))),
            "mean_speed_mm_s": exp.metrics["mean_speed_mm_s"]}


def describe(bearing):
    return {0: "Ahead", 180: "Behind"}.get(bearing, f"{'+' if bearing > 0 else '−'}{abs(bearing)}° ({'left' if bearing > 0 else 'right'})")


def behavior_table(rows):
    lines = ["| Target | Distance | Model | Reached ≤2 mm | Median time to reach | First turn toward target | Final distance (mean ± SD) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for bearing in BEARINGS:
        for distance in DISTANCES:
            for model, label in MODELS.items():
                group = [r for r in rows if r["model"] == model and r["bearing_deg"] == bearing
                         and r["distance_mm"] == distance and r["silence_dna02"] == "none"]
                if not group:
                    continue
                reached = [r["reach_time_s"] for r in group if r["reached"]]
                turns = [r["first_turn_toward"] for r in group]
                if bearing in (0, 180):
                    turn_text = "n/a (" + ", ".join(f"{n} {d}" for d in ["left", "right"]
                                                     if (n := sum(r["first_turn"] == d for r in group))) + ")" \
                        if any(r["first_turn"] for r in group) else "n/a (no turn)"
                else:
                    turn_text = f"{sum(t is True for t in turns)}/{len(group)}"
                final = np.array([r["final_distance_mm"] for r in group])
                lines.append(f"| {describe(bearing)} | {distance} mm | {label} | {len(reached)}/{len(group)} | "
                             f"{f'{np.median(reached):.2f} s' if reached else '—'} | {turn_text} | "
                             f"{final.mean():.1f} ± {final.std(ddof=1) if len(final) > 1 else 0:.1f} mm |")
    return "\n".join(lines)


def silencing_table(rows):
    lines = ["| Target | DNa02 silenced | Mean yaw rate, first 2 s | Net turn | Reached ≤2 mm | Final distance |",
             "| --- | --- | --- | --- | --- | --- |"]
    for bearing in sorted({r["bearing_deg"] for r in rows}, key=BEARINGS.index):
        for silence in ["none", "left", "right", "both"]:
            group = [r for r in rows if r["bearing_deg"] == bearing and r["silence_dna02"] == silence]
            if not group:
                continue
            rate = np.array([r["mean_yaw_rate_first_2s_deg_s"] for r in group])
            net = np.array([r["net_turn_deg"] for r in group])
            final = np.array([r["final_distance_mm"] for r in group])
            lines.append(f"| {describe(bearing)}, {group[0]['distance_mm']} mm | {silence} | {rate.mean():+.1f} °/s | "
                         f"{net.mean():+.0f}° | {sum(r['reached'] for r in group)}/{len(group)} | {final.mean():.1f} mm |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Matched-seed evaluation of both neural models.")
    parser.add_argument("--engine", choices=["toy", "flygym"], default="toy")
    parser.add_argument("--quick", action="store_true", help="Smaller set: 12 mm targets, 3 seeds")
    parser.add_argument("--duration", type=float, help="Simulated seconds per trial (default 10 toy, 6 FlyGym)")
    args = parser.parse_args()
    duration = args.duration or (10. if args.engine == "toy" else 6.)
    seeds = SEEDS[:3] if args.quick else SEEDS
    distances = [12] if args.quick else DISTANCES
    started = time.perf_counter()
    exp = Experiment(RunConfig(engine=args.engine), render=False)
    rows = []
    try:
        for model in MODELS:
            for bearing in BEARINGS:
                for distance in distances:
                    for seed in seeds:
                        rows.append(trial(exp, args.engine, model, bearing, distance, seed, duration))
        silencing = []
        for bearing in [45, -45, 90, -90]:
            for silence in ["none", "left", "right", "both"]:
                for seed in seeds:
                    silencing.append(trial(exp, args.engine, "connectome_dna02", bearing, 12, seed, duration, silence))
        parameters = exp.config.connectome_parameters.model_dump()
    finally:
        exp.close()
    report = {"engine": args.engine, "duration_s": duration, "seeds": seeds, "reach_threshold_mm": REACH_MM,
              "turn_threshold_deg": TURN_DEG, "connectome_parameters": parameters,
              "wall_s": time.perf_counter() - started, "python": platform.python_version(),
              "trials": rows, "silencing": silencing,
              "scope": "Simulated behavior of engineered or connectome-constrained controllers; no biological validation."}
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"evaluation-{args.engine}{'-quick' if args.quick else ''}.json").write_text(json.dumps(report, indent=1))
    print(f"## {args.engine} · {duration:g} simulated s per trial · seeds {', '.join(map(str, seeds))}\n")
    print(behavior_table(rows) + "\n")
    print(silencing_table(silencing))


if __name__ == "__main__":
    main()
