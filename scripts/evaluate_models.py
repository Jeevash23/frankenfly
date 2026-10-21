"""Matched-seed behavior of the engineered model and the connectome model on both committed circuits.

Targets sit ahead, at ±45°, at ±90° and directly behind the starting heading, at 12 mm and
30 mm. Each trial records whether the fly came within 2 mm of the target and when, whether
its first clear turn went toward the target, and its final distance. A second set silences
DNa02 left, right or both in each connectome model and measures the change in turning.

    backend/.venv/bin/python scripts/evaluate_models.py --engine toy --workers 8
    backend/.venv/bin/python scripts/evaluate_models.py --engine flygym --quick --workers 4

Every run starts from the default configuration and changes only the target, seed, model,
circuit, dynamics and silencing. Results describe this simulation, not fly behavior. A JSON
report goes to the ignored docs/evidence/ folder; Markdown tables are printed. Only a run of every
model at the default duration writes evaluation-<engine>[-quick].json; a partial run (--models or
--duration) adds those to the name, so it never replaces the full report. The trials run through
the research toolkit (digitalfly.toolkit), so the worker count does not change them; a trial that
fails is listed in the report's "errors" and left out of the tables.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly import toolkit  # noqa: E402

# Label → settings; the connectome variants differ only in circuit and dynamics.
MODELS = {
    "engineered": ("Engineered", {"neural_model": "engineered"}),
    "connectome": ("Connectome, DNa02 circuit", {"neural_model": "connectome"}),
    "steering": ("Connectome, steering circuit", {"neural_model": "connectome",
                                                    "connectome_parameters": {"circuit": "fafb783-steering"}}),
    "steering_spiking": ("Connectome, steering circuit, spiking", {
        "neural_model": "connectome", "connectome_parameters": {"circuit": "fafb783-steering", "dynamics": "spiking"}}),
}
BEARINGS = [0, 45, -45, 90, -90, 180]
DISTANCES = [12, 30]
SEEDS = [1, 2, 3, 4, 5]
DURATION_S = {"toy": 10., "flygym": 6.}


def report_name(engine, quick, models, duration):
    """The canonical file name for the full set of models at the default duration; a partial run names what it ran."""
    name = f"evaluation-{engine}{'-quick' if quick else ''}"
    if set(models) != set(MODELS):
        name += "-" + "+".join(models)
    if duration != DURATION_S[engine]:
        name += f"-{duration:g}s"
    return name + ".json"


def config(engine, model, bearing, distance, seed, silence="none"):
    return toolkit.configure({"engine": engine, "seed": seed, **MODELS[model][1]},
                             stimulus=toolkit.target(bearing, distance),
                             initial_interventions={"silence_dna02": silence})


def describe(bearing):
    return {0: "Ahead", 180: "Behind"}.get(bearing, f"{'+' if bearing > 0 else '−'}{abs(bearing)}° ({'left' if bearing > 0 else 'right'})")


def behavior_table(rows):
    lines = ["| Target | Distance | Model | Reached ≤2 mm | Median time to reach | First turn toward target | Final distance (mean ± SD) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for bearing in BEARINGS:
        for distance in DISTANCES:
            for model, (label, _) in MODELS.items():
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
    lines = ["| Model | Target | DNa02 silenced | Mean yaw rate, first 2 s | Net turn | Reached ≤2 mm | Final distance |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for model in dict.fromkeys(r["model"] for r in rows):
        for bearing in sorted({r["bearing_deg"] for r in rows}, key=BEARINGS.index):
            for silence in ["none", "left", "right", "both"]:
                group = [r for r in rows if r["model"] == model and r["bearing_deg"] == bearing and r["silence_dna02"] == silence]
                if not group:
                    continue
                rate = np.array([r["mean_yaw_rate_first_2s_deg_s"] for r in group])
                net = np.array([r["net_turn_deg"] for r in group])
                final = np.array([r["final_distance_mm"] for r in group])
                lines.append(f"| {MODELS[model][0]} | {describe(bearing)}, {group[0]['distance_mm']} mm | {silence} | "
                             f"{rate.mean():+.1f} °/s | {net.mean():+.0f}° | {sum(r['reached'] for r in group)}/{len(group)} | "
                             f"{final.mean():.1f} mm |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Matched-seed evaluation of the neural models.")
    parser.add_argument("--engine", choices=["toy", "flygym"], default="toy")
    parser.add_argument("--quick", action="store_true", help="Smaller set: 12 mm targets, 3 seeds")
    parser.add_argument("--duration", type=float, help="Simulated seconds per trial (default 10 toy, 6 FlyGym)")
    parser.add_argument("--models", default=",".join(MODELS), help=f"Comma-separated, from {', '.join(MODELS)}")
    parser.add_argument("--workers", type=int, default=1, help="Parallel processes (results do not depend on it)")
    args = parser.parse_args()
    duration = args.duration or DURATION_S[args.engine]
    seeds = SEEDS[:3] if args.quick else SEEDS
    distances = [12] if args.quick else DISTANCES
    models = [m for m in args.models.split(",") if m]
    unknown = set(models) - set(MODELS)
    if unknown:
        sys.exit(f"Unknown models: {', '.join(sorted(unknown))}. Choose from {', '.join(MODELS)}.")
    started = time.perf_counter()
    # Behavior for every model; DNa02 silencing for the rate-based connectome models.
    plan = [("behavior", model, bearing, distance, seed, "none") for model in models for bearing in BEARINGS
            for distance in distances for seed in seeds]
    plan += [("silencing", model, bearing, 12, seed, silence) for model in models
             if model in ("connectome", "steering") for bearing in [45, -45, 90, -90]
             for silence in ["none", "left", "right", "both"] for seed in seeds]
    results = toolkit.run_trials([config(args.engine, *item[1:]) for item in plan], workers=args.workers,
                                 duration_s=duration)
    rows, silencing, errors = [], [], []
    for (part, model, bearing, distance, seed, silence), result in zip(plan, results):
        row = {**result, "model": model, "bearing_deg": bearing, "distance_mm": distance, "silence_dna02": silence}
        (errors if row["error"] else rows if part == "behavior" else silencing).append(row)
    circuits = [MODELS[m][1].get("connectome_parameters", {}).get("circuit", "fafb783-dna02")
                for m in models if MODELS[m][1]["neural_model"] == "connectome"]
    report = {"engine": args.engine, "duration_s": duration, "seeds": seeds, "reach_threshold_mm": toolkit.REACH_MM,
              "turn_threshold_deg": toolkit.TURN_DEG, "models": {m: MODELS[m] for m in models},
              "wall_s": time.perf_counter() - started, "python": platform.python_version(),
              "trials": rows, "silencing": silencing, "errors": errors,
              "scope": "Simulated behavior of engineered or connectome-constrained controllers; no biological validation.",
              "provenance": toolkit.provenance(circuits)}
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    path = evidence / report_name(args.engine, args.quick, models, duration)
    path.write_text(json.dumps(report, indent=1))
    print(f"## {args.engine} · {duration:g} simulated s per trial · seeds {', '.join(map(str, seeds))}\n")
    print(behavior_table(rows) + "\n")
    if silencing:
        print(silencing_table(silencing))
    print(f"\nSaved {path.relative_to(ROOT)}")
    if errors:
        sys.exit(f"{len(errors)} trials failed and are left out of the tables: "
                 + "; ".join(sorted({e['error'] for e in errors})[:3]))


if __name__ == "__main__":
    main()
