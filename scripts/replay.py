"""Replay the recorded step-indexed input schedule and compare numeric telemetry.

    python scripts/replay.py RUN_FOLDER [--allow-circuit-mismatch] [--save] [--progress]

As a library (the app's replay jobs run this file): replay() returns the comparison, verdict() the summary that
--save writes to RUN_FOLDER/replay.json and the run library shows as "verified".
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import numpy as np
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly.api.models import RunConfig, Stimulus, Interventions, NeuralParameters, ConnectomeParameters
from digitalfly.simulation.experiment import BACKEND, Experiment, dependency_versions

TOLERANCE = 1e-8
POSE = ["x_mm", "y_mm", "z_mm", "yaw_rad"]
# Up to v0.5 (export schema 3) every live connectome parameter edit restarted a spiking network from the run's seed.
RESTARTING_SCHEMA = 3


class CannotReplay(Exception):
    """The run cannot be replayed here (its circuit changed or is missing, or its files are unreadable)."""


def check_circuit(metadata: dict):
    """A connectome run records the SHA-256 of the circuit it ran; a rebuilt circuit of the same name cannot replay it."""
    neural = metadata.get("neural") or {}
    if not neural.get("circuit_sha256"):
        return
    from digitalfly.neural.connectome import DEFAULT_CIRCUIT, circuit_path
    circuit = neural.get("circuit") or metadata["initial_config"].get("connectome_parameters", {}).get("circuit", DEFAULT_CIRCUIT)
    try:
        current = hashlib.sha256(circuit_path(circuit).read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        raise CannotReplay(f"The run's circuit {circuit} is not available: {exc}") from exc
    if current != neural["circuit_sha256"]:
        raise CannotReplay(f"The {circuit} circuit has changed since this run was recorded (sha256 {neural['circuit_sha256'][:12]}… "
                           f"then, {current[:12]}… now). Restore the original circuit file to replay it, or pass "
                           "--allow-circuit-mismatch to try anyway.")


def software_differences(metadata: dict) -> list[str]:
    """How the installed Python, package versions and lockfiles differ from those the run recorded."""
    differences = []
    if metadata.get("python") not in (None, platform.python_version()):
        differences.append(f"Python {metadata['python']} → {platform.python_version()}")
    then, now = metadata.get("dependencies") or {}, dependency_versions()
    for name in sorted(set(then) | set(now)):
        if then.get(name) != now.get(name):
            differences.append(f"{name} {then.get(name, 'absent')} → {now.get(name, 'absent')}")
    locks = metadata.get("lockfiles")
    if locks is None:
        differences.append("the run recorded no lockfile hashes")
    else:
        current = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(BACKEND.glob("requirements*.lock"))}
        for name in sorted(set(locks) | set(current)):
            if locks.get(name) != current.get(name):
                differences.append(f"{name} {'changed' if name in locks and name in current else 'added' if name in current else 'removed'}")
    return differences


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan  # reported as "not a number in telemetry.csv"


def read_telemetry(run_directory: Path):
    """(header, values): the column names and the rows as numbers (text becomes NaN), or (None, a sentence saying
    why they cannot be compared). Read as CSV, so a quoted name (a readout cell type such as "LAL003,LAL044") keeps
    its one column."""
    try:
        with (run_directory / "telemetry.csv").open(newline="") as file:
            lines = list(csv.reader(file))
    except (OSError, ValueError, csv.Error) as exc:
        return None, f"telemetry.csv is unreadable: {' '.join(str(exc).split())[:300] or type(exc).__name__}"
    header = lines[0] if lines else []
    rows = [(number, row) for number, row in enumerate(lines[1:], 2) if row]
    ragged = next(((number, row) for number, row in rows if len(row) != len(header)), None)
    if ragged:
        return None, f"telemetry.csv is unreadable: line {ragged[0]} has {len(ragged[1])} fields, the header {len(header)}"
    missing = [name for name in ["step", *POSE, "motor_l", "motor_r"] if name not in header]
    if missing or not rows:
        return None, f"telemetry.csv lacks the column{'s' * (len(missing) > 1)} {', '.join(missing)}" if missing else "telemetry.csv has no rows"
    values = np.array([[_number(cell) for cell in row] for _, row in rows], dtype=float)
    steps = values[:, header.index("step")]
    if not (np.isfinite(steps).all() and (steps == np.round(steps)).all() and steps[0] >= 0 and (np.diff(steps) > 0).all()):
        return None, "telemetry.csv's step column is not an increasing sequence of whole numbers"
    return (header, values), None


def replay(run_directory: Path, allow_circuit_mismatch=False, progress=None) -> dict:
    """Re-run a saved run from its initial configuration and recorded input schedule, and compare body position, yaw,
    neural rates and motor output with its telemetry.csv at an absolute tolerance of 1e-8. Returns the comparison
    (passed False, with a message, when they differ or the telemetry is damaged). Raises CannotReplay when the run
    cannot be replayed here. progress(fraction) is called as the replay advances."""
    run_directory = Path(run_directory)
    try:
        metadata = json.loads((run_directory / "metadata.json").read_text())
        initial, events = metadata["initial_config"], metadata["events"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CannotReplay(f"The run's metadata.json is unreadable: {exc}") from exc
    try:
        config = RunConfig.model_validate(initial)
    except ValidationError as exc:
        raise CannotReplay("The run's configuration cannot be used here: "
                           + "; ".join(error["msg"] for error in exc.errors())) from exc
    if not allow_circuit_mismatch:
        check_circuit(metadata)
    recorded, problem = read_telemetry(run_directory)
    report = {"samples": 0 if recorded is None else len(recorded[1]), "neural_model": config.neural_model,
              "compared_rates": [], "maximum_absolute_error": 0., "tolerance": TOLERANCE, "passed": False,
              "column_errors": {}, "message": problem}
    if recorded is None:
        return report
    header, values = recorded
    # Rate columns differ by neural model: six engineered units, or the connectome model's readouts.
    rates = [index for index, name in enumerate(header) if name.startswith("rate_")]
    rate_columns = [header[index] for index in rates]
    columns = [*POSE, *rate_columns, "motor_l", "motor_r"]
    compared = values[:, [header.index(name) for name in POSE] + rates + [header.index("motor_l"), header.index("motor_r")]]
    steps = values[:, header.index("step")].astype(int).tolist()
    schema = metadata.get("schema_version", 0)
    restart_spiking = isinstance(schema, int) and schema <= RESTARTING_SCHEMA
    errors = np.zeros(len(columns))
    worst = None  # (error, column, step, recorded, replayed), the first largest difference
    exp = Experiment(config, render=False)
    try:
        if exp.status != "paused":
            raise CannotReplay(f"The run's configuration cannot start here: {exp.error}")
        if len(exp.sample.rates) != len(rate_columns):
            report["message"] = (f"telemetry.csv has {len(rate_columns)} rate columns, but the replayed model "
                                 f"records {len(exp.sample.rates)}")
            return report
        event_index, last_step, reported = 0, steps[-1], 0.
        for target_step, expected in zip(steps, compared):
            while exp.step_index < target_step:
                while event_index < len(events) and events[event_index]["step"] <= exp.step_index:
                    event = events[event_index]
                    payload = {k: v for k, v in event["payload"].items() if k != "source"}
                    if event["payload"].get("source") == "protocol":
                        event_index += 1
                        continue
                    if event["kind"] == "stimulus":
                        exp.set_stimulus(Stimulus.model_validate(payload))
                    elif event["kind"] == "interventions":
                        exp.set_interventions(Interventions.model_validate(payload))
                    elif event["kind"] == "parameters":
                        exp.set_parameters(NeuralParameters.model_validate(payload))
                    elif event["kind"] == "connectome_parameters":
                        exp.set_connectome_parameters(ConnectomeParameters.model_validate(payload))
                        if restart_spiking:
                            exp.circuit.restart_spiking()
                    event_index += 1
                exp.advance()
            s = exp.sample
            actual = np.asarray([s.pose.x, s.pose.y, s.pose.z, s.pose.yaw, *s.rates, *s.motor], dtype=float)
            difference = np.abs(actual - expected)
            # A value that is not a number never matches, and never counts as an error of 0.
            difference[~np.isfinite(difference)] = np.inf
            errors = np.maximum(errors, difference)
            i = int(np.argmax(difference))
            if worst is None or difference[i] > worst[0]:
                worst = (float(difference[i]), columns[i], target_step, float(expected[i]), float(actual[i]))
            if progress is not None and last_step and target_step / last_step >= reported + .01:
                reported = target_step / last_step
                progress(reported)
    finally:
        exp.close()
    finite = errors[np.isfinite(errors)]
    report.update(compared_rates=rate_columns, maximum_absolute_error=float(finite.max()) if len(finite) else 0.,
                  column_errors={c: float(e) if np.isfinite(e) else None for c, e in zip(columns, errors)})
    expected_rows = metadata.get("recorded_samples", len(steps))
    if worst is not None and worst[0] >= TOLERANCE:
        error, column, step, then, now = worst
        report["message"] = (f"{column} at step {step} is not a number in telemetry.csv" if not np.isfinite(then) else
                             f"the replay's {column} at step {step} is not finite" if not np.isfinite(now) else
                             f"{column} differs by {error:.3g} at step {step} (recorded {then:.10g}, replayed {now:.10g})")
    elif len(steps) != expected_rows:
        report["message"] = f"telemetry.csv has {len(steps)} rows, but the run recorded {expected_rows} samples"
    else:
        report.update(passed=True, message=f"Replayed {len(steps)} samples: maximum absolute error "
                                           f"{report['maximum_absolute_error']:g}, within the tolerance {TOLERANCE:g}")
    return report


def verdict(report: dict, metadata: dict) -> dict:
    """What replay.json records: the comparison's outcome, when it was checked and whether the software matched."""
    differences = software_differences(metadata)
    message = report["message"].rstrip(".") + "."
    if differences:
        message += f" The software differs from the recording's: {'; '.join(differences)}."
    return {"ok": report["passed"], "max_abs_error": report["maximum_absolute_error"], "tolerance": report["tolerance"],
            "checked": datetime.now(timezone.utc).isoformat(), "same_software": not differences, "message": message,
            "samples_compared": report["samples"] if report["column_errors"] else 0,
            "column_errors": report["column_errors"], "software_differences": differences}


def save_verdict(run_directory: Path, result: dict):
    """Write replay.json atomically: a hidden partial file, renamed into place."""
    path = Path(run_directory) / "replay.json"
    part = path.with_name(f".replay.json.{os.getpid()}.part")
    try:
        part.write_text(json.dumps(result, indent=2, allow_nan=False))
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--allow-circuit-mismatch", action="store_true",
                        help="Replay even if the circuit file differs from the one the run recorded")
    parser.add_argument("--save", action="store_true",
                        help="Save the verdict as replay.json in the run folder (the run library shows it) and print it as one JSON line")
    parser.add_argument("--progress", action="store_true", help="Print '@progress FRACTION' lines while replaying")
    args = parser.parse_args()
    show = (lambda fraction: print(f"@progress {fraction:.3f}", flush=True)) if args.progress else None
    try:
        report = replay(args.run_directory, args.allow_circuit_mismatch, show)
    except CannotReplay as exc:
        sys.exit(str(exc))
    if args.save:
        result = verdict(report, json.loads((args.run_directory / "metadata.json").read_text()))
        save_verdict(args.run_directory, result)
        print(json.dumps(result, allow_nan=False), flush=True)
    else:
        print(json.dumps(report, indent=2))
    if not report["passed"]:
        sys.exit(f"Replay mismatch: {report['message']}")


if __name__ == "__main__":
    main()
