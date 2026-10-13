"""The research toolkit: configurations, trials, worker-independence, bias curves, ablation and the CLI."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from digitalfly import toolkit
from digitalfly.api.models import ConnectomeParameters, RunConfig

ROOT = Path(__file__).resolve().parents[2]


def test_configure_and_grid_reach_nested_settings():
    config = toolkit.configure({"engine": "toy"}, neural_model="connectome",
                               **{"connectome_parameters.dynamics": "spiking", "stimulus": toolkit.target(90, 10)})
    assert isinstance(config, RunConfig) and config.connectome_parameters.dynamics == "spiking"
    assert config.stimulus.x == pytest.approx(0, abs=1e-6) and config.stimulus.y == 10
    configs = toolkit.grid(config, seed=[1, 2], **{"connectome_parameters.output_gain": [1, 3]})
    assert [(c.seed, c.connectome_parameters.output_gain) for c in configs] == [(1, 1), (1, 3), (2, 1), (2, 3)]
    with pytest.raises(ValueError):
        toolkit.configure({"engine": "toy"}, **{"connectome_parameters.global_gain": -1})


def test_trials_report_behavior_and_do_not_depend_on_workers():
    configs = toolkit.grid({"engine": "toy", "neural_model": "connectome"}, seed=[1, 2],
                           stimulus=[toolkit.target(45, 12), toolkit.target(-90, 12)])
    serial = toolkit.run_trials(configs, workers=1, duration_s=1.0)
    parallel = toolkit.run_trials(configs, workers=2, duration_s=1.0)
    assert serial == parallel and len(serial) == 4
    first = serial[0]
    assert first["circuit"] == "fafb783-dna02" and first["readout_types"] == "DNa02" and first["dynamics"] == "rate"
    assert first["target_bearing_deg"] == pytest.approx(45) and first["first_turn_toward"] in (True, None)
    with_trace = toolkit.run_trial(configs[0], duration_s=.5, trajectory_every=10)
    assert len(with_trace["trajectory"]) == 5 and with_trace["final_distance_mm"] == pytest.approx(
        toolkit.run_trial(configs[0], duration_s=.5)["final_distance_mm"])


def test_bias_curve_and_ablation_on_the_toy_circuit(toy_brain):
    parameters = ConnectomeParameters(circuit="toy-brain", global_gain=.05)
    curve = toolkit.bias_curve(parameters, levels=(.5,), differences=(-.4, 0., .4), ms=200)
    turns = {row["right_minus_left"]: row["turn"] for row in curve["rows"]}
    assert turns[-.4] < 0 < turns[.4] and set(curve["equal_input_turn"]) == {.5}
    assert curve["mirror_asymmetry"] is not None and curve["mirror_asymmetry"] >= 0
    scan = toolkit.ablation_scan(parameters, left=.8, right=.2, ms=200)
    rows = {row["cell_type"]: row for row in scan["rows"]}
    assert "DNx" not in rows and scan["types_scanned"] == 5  # the readout is never silenced
    assert rows["LCa"]["turn"] == pytest.approx(0) and rows["LCa"]["change"] == pytest.approx(-scan["intact_turn"])
    assert rows["Solo"]["change"] == 0 and scan["rows"][0]["cell_type"] == "LCa"


def run_cli(*args):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), *args], capture_output=True, text=True,
                            timeout=300, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_command_line_tool(tmp_path):
    assert "fafb783-steering" in run_cli("circuits") and "| fafb783-dna02 | committed | 3,000 |" in run_cli("circuits")
    paths = run_cli("paths", "--source", "DNa03", "--target", "DNa02", "--hops", "2")
    assert "DNa03 → DNa02" in paths
    out = tmp_path / "bias"
    text = run_cli("bias", "--levels", ".5", "--differences=-.2,0,.2", "--ms", "50", "--out", str(out))
    assert "Mirror asymmetry" in text
    report = json.loads(out.with_suffix(".json").read_text())
    assert report["parameters"]["circuit"] == "fafb783-dna02" and len(report["rows"]) == 3
    assert out.with_suffix(".csv").read_text().startswith("level,right_minus_left")
