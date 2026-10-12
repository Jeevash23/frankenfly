"""Replay the recorded step-indexed input schedule and compare numeric telemetry."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly.api.models import RunConfig, Stimulus, Interventions, NeuralParameters, ConnectomeParameters
from digitalfly.simulation.experiment import Experiment

parser = argparse.ArgumentParser()
parser.add_argument("run_directory", type=Path)
args = parser.parse_args()
metadata = json.loads((args.run_directory / "metadata.json").read_text())
recorded = np.genfromtxt(args.run_directory / "telemetry.csv", delimiter=",", names=True)
recorded = np.atleast_1d(recorded)
events = metadata["events"]
# Rate columns differ by neural model: six engineered units, or the connectome model's readouts.
rate_columns = [name for name in recorded.dtype.names if name.startswith("rate_")]
exp = Experiment(RunConfig.model_validate(metadata["initial_config"]), render=False)
try:
    assert exp.status == "paused", exp.error
    event_index = 0
    max_error = 0.
    for row in recorded:
        target_step = int(row["step"])
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
                event_index += 1
            exp.advance()
        s = exp.sample
        actual = [s.pose.x, s.pose.y, s.pose.z, s.pose.yaw, *s.rates, *s.motor]
        expected = [row[k] for k in ["x_mm", "y_mm", "z_mm", "yaw_rad", *rate_columns, "motor_l", "motor_r"]]
        error = float(np.max(np.abs(np.asarray(actual) - expected)))
        max_error = max(max_error, error)
    assert max_error < 1e-8, f"Replay mismatch: {max_error:g}"
    print(json.dumps({"samples": len(recorded), "neural_model": exp.config.neural_model, "compared_rates": rate_columns,
                      "maximum_absolute_error": max_error, "tolerance": 1e-8, "passed": True}, indent=2))
finally:
    exp.close()
