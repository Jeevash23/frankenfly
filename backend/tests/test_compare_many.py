"""Comparisons across several recorded flies and runs: per-recording fits plus their mean and spread."""
import csv
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
from digitalfly import compare, toolkit

ROOT = Path(__file__).resolve().parents[2]


def run_compare(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "compare", *args], capture_output=True,
                          text=True, timeout=120, cwd=ROOT)


def synthetic(gain, lag_s=0., seconds=20, noise=0., seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(0, seconds, .01)
    left = 30 + 12 * np.sin(2 * np.pi * .23 * t) + rng.normal(0, noise / 4, len(t))
    right = 30 + 12 * np.sin(2 * np.pi * .31 * t + 1) + rng.normal(0, noise / 4, len(t))
    rotation = gain * np.interp(t - lag_s, t, right - left, left=(right - left)[0]) + rng.normal(0, noise, len(t))
    return t, left, right, rotation


def write_fly(path, gain, lag_s, seed):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(compare.COLUMNS)
        writer.writerows(zip(*synthetic(gain, lag_s, seconds=40, noise=4, seed=seed)))


def test_compare_reports_each_recording_and_the_spread_across_them(tmp_path):
    flies = []
    for k, (gain, lag) in enumerate([(2., .10), (2.5, .12), (3., .14)]):
        flies += ["--recording", str(tmp_path / f"fly{k}.csv")]
        write_fly(tmp_path / f"fly{k}.csv", gain, lag, k)
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 2})
    model = toolkit.jumping_target_run(config, duration_s=2, every_s=1, seed=5, export_dir=tmp_path)["path"]
    done = run_compare(*flies, "--run", model, "--out", str(tmp_path / "fit"))
    assert done.returncode == 0, done.stderr
    assert "| fly 1: fly0.csv |" in done.stdout and "| fly 3: fly2.csv |" in done.stdout and "| model: " in done.stdout
    assert "| fly | 3 | 120 ± 20 ms (100–140 ms) |" in done.stdout and "Same sign in every fit: True" in done.stdout
    saved = json.loads((tmp_path / "fit.json").read_text())
    across = saved["across"]["fly"]
    assert across["recordings"] == 3 and across["gain"]["mean"] == pytest.approx(2.5, rel=.03)
    assert across["gain"]["sd"] == pytest.approx(.5, rel=.1) and across["heldout_r2"]["n"] == 3
    assert across["signs"] == {"positive": 3, "negative": 0} and "model" not in saved["across"]
    assert set(saved["conversions"]) == {"fly 1", "fly 2", "fly 3"} and saved["run"]["path"] == model
    assert saved["comparison"]["flies"] == 3 and saved["comparison"]["lag_difference_s"] == pytest.approx(
        saved["fits"]["model"]["lag_s"] - .12, abs=.011)
    refused = run_compare(*flies[:4], "--save-recording", str(tmp_path / "x.csv"))
    assert refused.returncode == 1 and "single --recording" in refused.stderr


def test_one_recording_keeps_the_single_source_report(tmp_path):
    write_fly(tmp_path / "fly.csv", 2.5, .12, 0)
    done = run_compare("--recording", str(tmp_path / "fly.csv"), "--out", str(tmp_path / "fit"))
    assert done.returncode == 0, done.stderr
    assert "| fly: fly.csv |" in done.stdout and "Across" not in done.stdout
    saved = json.loads((tmp_path / "fit.json").read_text())
    assert list(saved) == ["command", "rotation", "fits", "filters", "rates", "conversion", "provenance"]
    assert saved["fits"]["model"] is None and saved["conversion"] is None


def test_fit_summaries_pool_gains_only_in_one_unit():
    fly = compare.fit_turning(compare.Recording(*synthetic(2.)))
    rate = {**fly, "gain_units": "deg/s per dimensionless rate", "correlation_sign": -1}
    summary = compare.summarize_fits([fly, rate])
    assert summary["gain"] is None and summary["gain_units"].startswith("mixed") and summary["heldout_r2"] is None
    assert summary["signs"] == {"positive": 1, "negative": 1} and summary["lag_s"]["sd"] == 0
    assert compare.spread([1, None, 3]) == {"n": 2, "mean": 2., "sd": pytest.approx(2 ** .5), "min": 1., "max": 3.}
    assert compare.spread([None]) is None and not compare.compare_groups([fly], [rate])["same_sign"]
