"""Toolkit trials without a recording, motor clipping in trial rows, and streamed, resumable evaluations."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from digitalfly import toolkit
from digitalfly.simulation import experiment

ROOT = Path(__file__).resolve().parents[2]
CONNECTOME = {"engine": "toy", "neural_model": "connectome", "seed": 1}


def run(script, *args, timeout=300):
    return subprocess.run([sys.executable, str(ROOT / script), *args], capture_output=True, text=True, timeout=timeout,
                          cwd=ROOT)


def test_trials_keep_no_recording_so_they_run_past_the_recording_limit(monkeypatch, tmp_path):
    config = toolkit.configure(CONNECTOME, stimulus=toolkit.target(45, 12))
    recorded = experiment.Experiment(config, render=False)  # how every trial ran before v0.6
    try:
        expected = toolkit.run_trial(config, duration_s=.6, experiment=recorded)
    finally:
        recorded.close()
    monkeypatch.setattr(experiment, "RECORD_LIMIT", 50)  # 0.5 simulated seconds instead of 300
    assert toolkit.run_trial(config, duration_s=.6) == expected  # recording never changes the numbers
    row = toolkit.run_trials([config], duration_s=.6)[0]
    assert row["error"] is None and row["final_distance_mm"] == expected["final_distance_mm"]
    # A recording experiment, and the exported jumping-target run, are checked before anything runs.
    recorded = experiment.Experiment(config, render=False)
    try:
        with pytest.raises(ValueError, match="at most 0.49 s"):
            toolkit.run_trial(config, duration_s=.6, experiment=recorded)
        assert recorded.step_index == 0
    finally:
        recorded.close()
    with pytest.raises(ValueError, match="recording limit of 50 samples"):
        toolkit.jumping_target_run(config, duration_s=.6, export_dir=tmp_path)
    assert not any(tmp_path.iterdir())


def test_the_recording_limit_check_and_the_jump_command():
    assert toolkit.recorded_steps(299.99) == 29999
    with pytest.raises(ValueError, match="at most 299.99 s"):
        toolkit.recorded_steps(300)
    refused = run("scripts/toolkit.py", "jump", "--duration", "300", timeout=60)
    assert refused.returncode == 1 and "ValueError: 300 simulated s does not fit" in refused.stderr
    assert "Traceback" not in refused.stderr


def test_connectome_trial_rows_report_motor_clipping():
    config = toolkit.configure(CONNECTOME, **{"connectome_parameters.dynamics": "spiking"})
    exp = experiment.Experiment(config, render=False, record=False)
    try:
        row = toolkit.run_trial(config, duration_s=.5, experiment=exp)
        assert row["motor_clipped_fraction"] == exp.circuit.motor_clipped_fraction
    finally:
        exp.close()
    assert 0 < row["motor_clipped_fraction"] < 1  # the default spiking calibration clips often
    assert "motor_clipped_fraction" not in toolkit.run_trial({"engine": "toy"}, duration_s=.2)


def test_trial_logs_reload_saved_rows_from_python(tmp_path):
    log = toolkit.TrialLog(tmp_path / "sweep")
    for row in toolkit.run_trials(toolkit.grid(CONNECTOME, seed=[1, 2]), duration_s=.2, on_result=lambda i, r: log.add(r)):
        assert row["config_hash"] in {r["config_hash"] for r in log.rows}
    resumed = toolkit.TrialLog(tmp_path / "sweep", resume=True)
    assert len(resumed.saved) == 2 and (tmp_path / "sweep.csv").read_text().count("\n") == 3


def test_evaluations_stream_their_trials_and_resume(tmp_path):
    out = tmp_path / "evaluation.json"
    args = ["scripts/evaluate_models.py", "--engine", "toy", "--quick", "--models", "connectome", "--duration", ".2",
            "--out", str(out)]
    first = run(*args)
    assert first.returncode == 0, first.stderr
    # 18 behavior and 48 silencing trials, of which 12 repeat behavior trials and run once.
    assert "Running 54 trials" in first.stdout and f"Saved {out}" in first.stdout
    lines = out.with_suffix(".jsonl").read_text().splitlines()
    report = json.loads(out.read_text())
    assert len(lines) == 54 and len(report["trials"]) == 18 and len(report["silencing"]) == 48 and not report["errors"]
    assert all(0 <= r["motor_clipped_fraction"] <= 1 for r in report["trials"])
    out.with_suffix(".jsonl").write_text("\n".join(lines[:50]) + "\n")  # as if interrupted
    resumed = run(*args, "--resume")
    assert resumed.returncode == 0, resumed.stderr
    assert "Running 4 trials on 1 worker(s); 50 already saved" in resumed.stdout
    again = json.loads(out.read_text())
    assert again["trials"] == report["trials"] and again["silencing"] == report["silencing"]
    assert len(out.with_suffix(".jsonl").read_text().splitlines()) == 54
