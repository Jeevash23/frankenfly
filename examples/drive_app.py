"""Drive a running DigitalFly app from Python: a target on the left, DNa02 silenced on one side and restored,
then a share-safe export.

Start the app first (./scripts/start.sh, or backend/.venv/bin/python scripts/launch.py --toy for the toy
body), then, from the repository root:

    backend/.venv/bin/python examples/drive_app.py
    backend/.venv/bin/python examples/drive_app.py --engine flygym --seconds 3

The browser shows the run while this script drives it. Net turn is positive to the left (counterclockwise).
Results describe this simulation, not flies.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/src"))
from digitalfly.client import Client  # noqa: E402


def advance(fly: Client, seconds: float, speed: float) -> dict:
    """Run for `seconds` of simulated time, then pause; returns the paused state."""
    start = fly.status()["sample"]["t"]
    fly.run()
    fly.wait_until(lambda s: s["sample"]["t"] >= start + seconds or s["status"] != "running",
                   timeout=seconds / speed * 4 + 30)
    return fly.pause()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="The app's address")
    parser.add_argument("--engine", choices=["toy", "flygym"], default="toy")
    parser.add_argument("--seconds", type=float, default=2.0, help="Simulated seconds per phase")
    parser.add_argument("--speed", type=float, default=1.0, help="Display speed, 0.05-2 times real time")
    args = parser.parse_args()
    fly = Client(args.url)
    fly.reset({"engine": args.engine, "neural_model": "connectome", "seed": 3, "speed": args.speed,
               "stimulus": {"x": 0, "y": 12, "intensity": 1}})  # 12 mm to the fly's left
    for label, change in [("intact", None), ("DNa02 left silenced", "left"), ("restored", "none")]:
        if change is not None:
            fly.interventions(silence_dna02=change)  # merged into the current interventions
        before = fly.status()["metrics"]["net_turn_deg"]
        state = advance(fly, args.seconds, args.speed)
        metrics = state["metrics"]
        print(f"{label}: until {state['sample']['t']:.2f} s, net turn {metrics['net_turn_deg'] - before:+.0f}°, "
              f"target {metrics['target_distance_mm']:.1f} mm away")
    saved = fly.export(share_safe=True)
    print(f"Exported {saved['samples']} samples to {saved['path']}")


if __name__ == "__main__":
    main()
