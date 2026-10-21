"""Assumption sensitivity (digitalfly.robustness) and the readout table, in Python and from the command line."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from digitalfly import robustness, toolkit
from digitalfly.api.models import ConnectomeParameters

ROOT = Path(__file__).resolve().parents[2]
TOY = ConnectomeParameters(circuit="toy-brain", global_gain=.05)


def test_variants_put_the_baseline_first_and_reach_nested_settings():
    found = robustness.variants(ConnectomeParameters(), {"other_transmitters": ["excluded", "excitatory"],
                                                         "spiking.rate_scale_hz": [100, 50], "seed": [3, 4]})
    assert len(found) == 8 and found[0]["settings"] == {"other_transmitters": "excluded", "spiking.rate_scale_hz": 100, "seed": 3}
    assert found[0]["parameters"] == ConnectomeParameters() and found[0]["seed"] == 3 and found[0]["seed_axis"]
    assert found[-1]["parameters"].spiking.rate_scale_hz == 50 and found[-1]["parameters"].other_transmitters == "excitatory"
    defaults = robustness.variants(ConnectomeParameters(circuit="fafb783-steering"))
    assert len(defaults) == 12 and {v["parameters"].circuit for v in defaults} == {"fafb783-steering"}
    assert not defaults[0]["seed_axis"] and defaults[0]["parameters"].dynamics == "rate"
    with pytest.raises(ValueError):
        robustness.variants(ConnectomeParameters(), {"synapse_threshold": [0]})
    h = robustness.variant_hash(found[0], ["bias"], {})
    assert h == robustness.variant_hash(found[0], ["bias"], {}) != robustness.variant_hash(found[1], ["bias"], {})
    assert h != robustness.variant_hash(found[0], ["bias", "reach"], {})


def test_readout_table_reads_each_readout_side_and_judges_the_turn(toy_brain):
    table = robustness.readout_table(TOY, bearings=(45, 0, -45), ms=200)
    rows = {r["bearing_deg"]: r for r in table["rows"]}
    assert table["readout_types"] == ["DNx"] and [r["target"] for r in table["rows"]] == ["45° left", "Ahead", "45° right"]
    assert rows[0]["sensor_left"] == pytest.approx(rows[0]["sensor_right"]) and rows[45]["sensor_left"] > rows[45]["sensor_right"]
    for row in table["rows"]:
        # One readout type at output gain 1; toolkit.hold rounds activities to 6 decimals.
        assert row["turn"] == pytest.approx(row["right_minus_left"]["DNx"], abs=2e-6)
        assert row["direction"] == robustness.direction(row["turn"])
    assert rows[0]["toward"] is None
    assert rows[45]["toward"] == (rows[45]["direction"] == "left") and rows[-45]["toward"] == (rows[-45]["direction"] == "right")
    doubled = robustness.readout_table(TOY.model_copy(update={"output_gain": 2}), bearings=(45,), ms=200)["rows"][0]
    assert doubled["turn"] == pytest.approx(2 * rows[45]["turn"])
    assert robustness.direction(.005) == "none" and robustness.direction(-.02) == "left" and robustness.direction(.5, 1) == "none"


def test_evaluate_reduces_each_analysis_to_conclusions(toy_brain):
    variant = robustness.variants(TOY, {"seed": [0]})[0]
    result = robustness.evaluate(variant, ("bias", "readouts", "reach"), ms=200, reach_bearings=(45,),
                                 reach_duration_s=.2)
    curve = toolkit.bias_curve(TOY, ms=200)
    assert result["equal_input_turn"] == pytest.approx(curve["equal_input_turn"][.5])
    assert result["mirror_asymmetry"] == pytest.approx(curve["mirror_asymmetry"])
    assert result["equal_input_direction"] == robustness.direction(result["equal_input_turn"])
    assert result["direction_at_45"] == robustness.direction(result["turn_at_45"]) and len(result["readouts"]) == 5
    assert result["shifts_toward_target"] in ("yes", "no")
    assert result["reach_trials"] == 1 and result["lateral_trials"] == 1  # the seed axis gives the only reach seed
    assert result["reaching"] in ("none", "all") and result["first_turn_toward"] in ("none", "all")
    calm = robustness.evaluate(variant, ("bias",), ms=200, tolerance=10)
    assert {calm[k] for k in ("equal_input_direction", "target_right_direction", "target_left_direction")} == {"none"}


def test_a_failing_variant_becomes_an_error_row_and_the_rest_run(toy_brain):
    found = robustness.variants(TOY, {"readout_types": [["DNx"], ["Solo"], ["LCa"]]})  # Solo has no right neuron
    seen = []
    rows = robustness.run(found, ("bias",), on_result=lambda index, row: seen.append(index), ms=100)
    assert sorted(seen) == [0, 1, 2] and [r["variant"] for r in rows] == [0, 1, 2]
    assert rows[0]["error"] is None and rows[2]["error"] is None and "both sides" in rows[1]["error"]
    assert rows[1]["readout_types"] == '["Solo"]' and rows[1]["config_hash"]
    assert rows[0]["circuit"] == "toy-brain" and len(rows[0]["circuit_sha256"]) == 64
    with pytest.raises(ValueError, match="analyses"):
        robustness.run(found, ("fit",))


def test_parallel_variants_give_the_same_rows_as_serial_ones():
    found = robustness.variants(ConnectomeParameters(), {"synapse_threshold": [5, 20]})
    serial = robustness.run(found, ("bias",), ms=30)
    assert robustness.run(found, ("bias",), workers=2, ms=30) == serial and serial[1]["synapse_threshold"] == 20


def test_survival_compares_every_variant_with_the_baseline():
    rows = [{"variant": 0, "dynamics": "rate", "threshold": 5, "equal_input_direction": "left", "reaching": "all", "error": None},
            {"variant": 1, "dynamics": "rate", "threshold": 20, "equal_input_direction": "left", "reaching": "most", "error": None},
            {"variant": 2, "dynamics": "spiking", "threshold": 5, "equal_input_direction": "right", "reaching": "all", "error": None},
            {"variant": 3, "dynamics": "spiking", "threshold": 20, "equal_input_direction": "right", "reaching": "most", "error": None},
            {"variant": 4, "dynamics": "spiking", "threshold": 10, "error": "ValueError: broken"}]
    found = {s["conclusion"]: s for s in robustness.survival(rows, ["dynamics", "threshold"])}
    bias = found["equal_input_direction"]
    assert (bias["baseline"], bias["holds"], bias["variants"], bias["survives"]) == ("left", 2, 4, False)
    assert bias["differs_in"] == [2, 3] and bias["differs_only_with"] == {"dynamics": "spiking"}
    assert found["reaching"]["differs_only_with"] == {"threshold": 20} and list(found) == ["equal_input_direction", "reaching"]
    same = robustness.survival([r for r in rows if r["dynamics"] == "rate"][:1] * 2, ["dynamics"])
    assert all(s["survives"] for s in same)
    assert not any(s["survives"] for s in robustness.survival([rows[4], rows[0]], ["dynamics"]))  # failed baseline


def run_cli(*args, check=True):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), *args], capture_output=True, text=True,
                            timeout=600, cwd=ROOT)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def test_readouts_command_reproduces_the_published_table(tmp_path):
    out = tmp_path / "readouts"
    text = run_cli("readouts", "--out", str(out)).stdout
    assert "| 45° left | 0.735 / 0.368 | -0.238 | -0.238 | Left, toward |" in text
    report = json.loads(out.with_suffix(".json").read_text())
    # "What the circuits compute" in docs/RESEARCH.md: DNa02 R − L at 0.6 s, target 12 mm away.
    assert [round(r["right_minus_left"]["DNa02"], 3) for r in report["rows"]] == [-.238, -.262, -.178, -.056, .060]
    assert [(r["direction"], r["toward"]) for r in report["rows"]] == [
        ("left", True), ("left", True), ("left", None), ("left", False), ("right", True)]
    assert report["provenance"]["circuits"][0]["name"] == "fafb783-dna02" and report["ms"] == 600
    assert out.with_suffix(".csv").read_text().startswith("bearing_deg,target,sensor_left,sensor_right,turn,")


def test_robustness_command_saves_survival_with_provenance_and_resumes(tmp_path):
    assert "--analyses" in run_cli("robustness", "--analyses", "fit", check=False).stderr
    assert "--resume needs --out" in run_cli("robustness", "--resume", check=False).stderr
    out = tmp_path / "robust"
    args = ["robustness", "--vary", "connectome_parameters.other_transmitters=excluded,excitatory", "--ms", "50",
            "--out", str(out)]
    text = run_cli(*args).stdout
    assert "| Turn with equal input (0.5 / 0.5) |" in text and "not evidence about flies" in text
    report = json.loads(out.with_suffix(".json").read_text())
    assert report["axes"] == ["other_transmitters"] and report["errors"] == 0 and len(report["variants"]) == 2
    assert report["settings"] == {"tolerance": .01, "ms": 50, "average_ms": 0} and report["analyses"] == ["bias"]
    assert {s["conclusion"] for s in report["survival"]} == {"equal_input_direction", "target_right_direction",
                                                            "target_left_direction"}
    assert report["provenance"]["command"][1] == "robustness" and report["provenance"]["circuits"][0]["name"] == "fafb783-dna02"
    lines = out.with_suffix(".jsonl").read_text().splitlines()
    out.with_suffix(".jsonl").write_text(lines[0] + "\n")  # as if stopped after one variant
    resumed = run_cli(*args, "--resume").stdout
    assert "Evaluating 1 of 2 variants" in resumed
    assert json.loads(out.with_suffix(".json").read_text())["survival"] == report["survival"]
