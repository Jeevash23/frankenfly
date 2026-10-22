"""Batch trials over seeds without the app: the DNa02 connectome circuit with rate and spiking dynamics, run
in parallel with digitalfly.toolkit, saved as each trial finishes and summarized with 95% intervals.

    backend/.venv/bin/python examples/batch_seeds.py
    backend/.venv/bin/python examples/batch_seeds.py --seeds 1-20 --workers 8 --out runs/toolkit/my-batch --resume

Run it as a script, not pasted into an interactive prompt: parallel workers are new processes that import
this file. Results describe this simulation, not flies.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly import toolkit  # noqa: E402


def percent(ci):
    return "n/a" if ci is None else f"{ci[0]:.0%} to {ci[1]:.0%}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", default="1-5", help="A range such as 1-5")
    parser.add_argument("--duration", type=float, default=10.0, help="Simulated seconds per trial")
    parser.add_argument("--workers", type=int, default=1, help="Parallel processes (results do not depend on it)")
    parser.add_argument("--out", default=str(ROOT / "runs/toolkit/batch-seeds"), help="Output stem (.jsonl and .csv)")
    parser.add_argument("--resume", action="store_true", help="Skip the trials already saved in --out")
    args = parser.parse_args()
    first, _, last = args.seeds.partition("-")
    base = toolkit.configure({"engine": "toy", "neural_model": "connectome"})
    configs = toolkit.grid(base, seed=list(range(int(first), int(last or first) + 1)),
                           stimulus=[toolkit.target(45, 12), toolkit.target(-45, 12)],
                           **{"connectome_parameters.dynamics": ["rate", "spiking"]})
    log = toolkit.TrialLog(args.out, resume=args.resume)  # every finished trial goes to .jsonl and .csv at once
    hashes = [toolkit.config_hash(c, duration_s=args.duration) for c in configs]
    todo = [c for c, h in zip(configs, hashes) if h not in log.saved]
    print(f"Running {len(todo)} of {len(configs)} trials; rows go to {log.jsonl}", flush=True)
    toolkit.run_trials(todo, workers=args.workers, on_result=lambda index, row: log.add(row), duration_s=args.duration)
    rows = log.rows_for(hashes)  # this batch only: the log can also hold earlier batches' seeds and durations
    summary = toolkit.summarize(rows, ["dynamics"])
    print("\n| Dynamics | Trials | Reached ≤2 mm (95% CI) | First turn toward (95% CI) | Final distance, mean (95% CI) "
          "| Motor clipped |\n| --- | --- | --- | --- | --- | --- |")
    for c in summary["conditions"]:
        dynamics = c["condition"]["dynamics"]
        final = c["final_distance_mm"]
        clipped = [r["motor_clipped_fraction"] for r in rows if r.get("dynamics") == dynamics and not r["error"]]
        ci = "n/a" if final["ci95"] is None else f"{final['ci95'][0]:.1f} to {final['ci95'][1]:.1f}"
        print(f"| {dynamics} | {c['trials']} | {c['reached']}/{c['trials'] - c['errors']} ({percent(c['reached_ci95'])}) | "
              f"{c['first_turn_toward']}/{c['lateral_trials']} ({percent(c['first_turn_toward_ci95'])}) | "
              + (f"{final['mean']:.1f} mm ({ci})" if final["mean"] is not None else "—")
              + f" | {sum(clipped) / max(len(clipped), 1):.0%} of steps |")
    errors = [r for r in rows if r["error"]]
    if errors:
        sys.exit(f"{len(errors)} trials failed (see the error column); rerun with --resume to retry them.")


if __name__ == "__main__":
    main()
