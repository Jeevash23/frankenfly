"""An example DigitalFly plugin (plugin API 1): one of each contribution, small enough to read in one sitting.

    backend/.venv/bin/python -m pip install --no-deps -e examples/plugins/digitalfly-example-plugin
    backend/.venv/bin/python scripts/toolkit.py plugins

- metric `example:straightness`: net displacement ÷ path length of a saved run (1 = a straight line);
- scorecard test `example:target_side`: the fly turns toward a target placed 45° to its left or right;
- sensor `example:crossed`: the geometric encoder's values with left and right swapped (crossed wiring);
- stimulus program `example:zigzag`: the target jumps from side to side at a fixed interval;
- toolkit command `example:straightness`: prints the metric for saved run folders.

Everything here is engineered for demonstration. The scorecard test is not a published result.
"""
import argparse
import math
from pathlib import Path

from digitalfly.plugins import Command, Metric, Plugin, ScorecardTest, Sensor, StimulusProgram

DISTANCE_MM = 12.0


# A metric reads a saved run (digitalfly.plugins.ExportedRun): its metadata and telemetry.csv columns.
def straightness(run):
    x, y = run.columns.get("x_mm", []), run.columns.get("y_mm", [])
    if len(x) < 2:
        return None
    path = sum(math.hypot(x[k + 1] - x[k], y[k + 1] - y[k]) for k in range(len(x) - 1))
    if path < 1e-9:
        return None  # the fly did not move
    return {"straightness": math.hypot(x[-1] - x[0], y[-1] - y[0]) / path, "path_mm": path}


# A scorecard test: conditions (label, stimulus, interventions) run on matched seeds, then a fixed rule.
def target_side_conditions(names, dynamics):
    from digitalfly.api.models import Interventions, Stimulus
    conditions = []
    for bearing in (45, -45):
        angle = math.radians(bearing)
        stimulus = Stimulus(x=DISTANCE_MM * math.cos(angle), y=DISTANCE_MM * math.sin(angle), intensity=1)
        conditions.append((f"target {bearing:+d}°", stimulus, Interventions()))
    return conditions


def target_side_score(names, trials):
    toward = [(1 if row["condition"] == "target +45°" else -1) * row["early_yaw_rate_deg_s"] for row in trials]
    mean = sum(toward) / len(toward)
    status = "pass" if all(v > 2 for v in toward) else "partial" if mean > 0 else "fail"
    return status, {"value": mean, "unit": "°/s toward the target",
                    "text": f"{mean:+.1f} °/s toward the target (mean of {len(toward)} trials)"}


# A sensor replaces the geometric encoder's two values; it must depend only on the reading, so runs replay.
def crossed(reading):
    return reading.geometric_right, reading.geometric_left


# A stimulus program writes a protocol (step-indexed events); the run keeps the protocol, not the program.
def zigzag(every_steps=100, jumps=4, distance_mm=DISTANCE_MM, bearing_deg=60.0):
    every_steps, jumps = int(every_steps), int(jumps)
    events = []
    for k in range(jumps):
        angle = math.radians(bearing_deg if k % 2 == 0 else -bearing_deg)
        events.append({"step": k * every_steps, "stimulus": {"x": distance_mm * math.cos(angle),
                                                             "y": distance_mm * math.sin(angle), "intensity": 1}})
    return {"name": f"Zigzag every {every_steps * 10} ms", "duration_steps": jumps * every_steps, "events": events}


def straightness_command(args: argparse.Namespace):
    from digitalfly.plugins import read_run
    for folder in args.runs:
        value = straightness(read_run(Path(folder)))
        print(f"{folder}: " + ("no movement" if value is None else f"straightness {value['straightness']:.3f} over "
                                                                    f"{value['path_mm']:.1f} mm"))


def straightness_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("runs", nargs="+", help="Saved run folders (runs/<id>)")


plugin = Plugin(
    api_version=1,
    title="DigitalFly example plugin",
    description="One of each plugin contribution, for reading and testing.",
    url="https://github.com/Jeevash23/frankenfly/tree/main/examples/plugins",
    license="MIT",
    metrics=(Metric("straightness", "Path straightness", straightness, unit="ratio",
                    description="Net displacement ÷ path length over the run (1 = a straight line)."),),
    scorecard_tests=(ScorecardTest(
        id="target_side", title="Target 45° to one side → turning toward it",
        source={"citation": "Example test for the plugin API; not a published result.", "doi": None,
                "finding": "A fly steering toward a visual target turns toward the side the target is on."},
        manipulation="A target 12 mm away at +45° and at −45°; no intervention.",
        measure="Early yaw rate (0.2-1 s), °/s, signed positive toward the target.",
        rule="pass: every trial turns toward the target faster than 2 °/s; partial: the mean is toward it; fail: "
             "otherwise.",
        conditions=target_side_conditions, score=target_side_score, needs=["walk", "turn"],
        caveats=["An example of the API: the rule was not fixed against data."]),),
    sensors=(Sensor("crossed", "Crossed eyes", crossed,
                    description="The geometric encoder with left and right swapped."),),
    stimuli=(StimulusProgram("zigzag", "Zigzag target", zigzag,
                             parameters={"every_steps": 100, "jumps": 4, "distance_mm": DISTANCE_MM, "bearing_deg": 60.0},
                             description="The target jumps between ±bearing at a fixed interval."),),
    commands=(Command("straightness", "Print the path straightness of saved runs", straightness_command,
                      straightness_arguments),),
)
