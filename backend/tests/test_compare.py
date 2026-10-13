"""Comparing turning with right − left readout activity, on labeled synthetic recordings and real runs."""
import csv
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
from digitalfly import compare
from digitalfly.simulation.experiment import Experiment
from digitalfly import toolkit

ROOT = Path(__file__).resolve().parents[2]


def synthetic_fly(gain=2.5, lag_s=.12, offset=3., seconds=60, rate_hz=100, seed=0):
    """A labeled fixture: rotation follows 2.5 deg/s per spike/s of (R − L), 120 ms later, plus noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, 1 / rate_hz)
    left = 30 + 12 * np.sin(2 * np.pi * .23 * t) + rng.normal(0, 1, len(t))
    right = 30 + 12 * np.sin(2 * np.pi * .31 * t + 1) + rng.normal(0, 1, len(t))
    lagged = np.interp(t - lag_s, t, right - left, left=(right - left)[0])
    rotation = gain * lagged + offset + rng.normal(0, 4, len(t))
    return t, left, right, rotation


def test_fit_recovers_a_known_gain_lag_and_offset():
    fit = compare.fit_turning(compare.Recording(*synthetic_fly()))
    assert fit["gain"] == pytest.approx(2.5, rel=.03) and fit["lag_s"] == pytest.approx(.12, abs=.011)
    assert fit["offset_deg_s"] == pytest.approx(3, abs=.5) and fit["r2"] > .9 and fit["correlation_sign"] == 1
    flipped = compare.fit_turning(compare.Recording(*synthetic_fly(gain=-1.5)))
    assert flipped["correlation_sign"] == -1 and flipped["gain"] == pytest.approx(-1.5, rel=.05)


def test_recordings_load_from_the_documented_csv_and_reject_bad_files(tmp_path):
    t, left, right, rotation = synthetic_fly(seconds=20)
    path = tmp_path / "fly.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(compare.COLUMNS)
        writer.writerows(zip(t, left, right, rotation))
    loaded = compare.load_recording(path)
    assert loaded.source == "fly.csv" and loaded.units == "spikes/s"
    assert compare.fit_turning(loaded)["lag_s"] == pytest.approx(.12, abs=.011)
    np.savez(tmp_path / "fly.npz", t_s=t, rate_left_hz=left, rate_right_hz=right, rotational_velocity_deg_s=rotation)
    assert compare.fit_turning(compare.load_recording(tmp_path / "fly.npz"))["gain"] == pytest.approx(2.5, rel=.05)
    (tmp_path / "bad.csv").write_text("t_s,rate_left_hz\n0,1\n")
    with pytest.raises(ValueError, match="rate_right_hz"):
        compare.load_recording(tmp_path / "bad.csv")
    with pytest.raises(ValueError, match="increase"):
        compare.Recording([0, 2, 1], [1, 2, 3], [1, 2, 3], [0, 0, 0])
    with pytest.raises(ValueError, match="never changes"):
        compare.fit_turning(compare.Recording([0, 1, 2, 3], [1] * 4, [1] * 4, [0, 1, 0, 1]))


def test_a_model_run_turns_with_its_readout_by_construction(tmp_path):
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 4}, stimulus=toolkit.target(60, 10))
    exp = Experiment(config, render=False)
    try:
        for _ in range(300):
            exp.advance()
        result = exp.export(tmp_path)
    finally:
        exp.close()
    run = Path(result["path"])
    model = compare.model_recording(run)
    assert model.readout == "DNa02" and model.units == "dimensionless rate"
    fit = compare.fit_turning(model)
    # The toy body turns at 4 × 1.4 × 2 × turn rad/s, so the fit is exact up to motor clipping.
    assert fit["correlation_sign"] == 1 and fit["lag_s"] <= .02 and fit["r2"] > .9
    side_by_side = compare.compare(compare.Recording(*synthetic_fly()), model)
    assert side_by_side["same_sign"] and side_by_side["gain_ratio_model_to_fly"] is None
    with pytest.raises(ValueError, match="not a readout"):
        compare.model_recording(run, "DNa01")
    out = tmp_path / "cli"
    printed = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "compare", "--run", str(run),
                              "--out", str(out)], capture_output=True, text=True, timeout=120)
    assert printed.returncode == 0, printed.stderr
    assert "| model:" in printed.stdout and json.loads(out.with_suffix(".json").read_text())["model"]["r2"] > .9


def test_steering_curve_bins_turning_by_target_bearing():
    t = np.linspace(0, 2, 201)
    x, y, yaw = t * 5, np.zeros_like(t), np.zeros_like(t)  # straight at a target dead ahead
    rows = compare.steering_curve(t, x, y, yaw, (20, 0))
    ahead = next(r for r in rows if r["bearing_from_deg"] == 0)
    assert ahead["samples"] == len(t) and ahead["mean_rightward_deg_s"] == 0
    assert sum(r["samples"] for r in rows) == len(t)
