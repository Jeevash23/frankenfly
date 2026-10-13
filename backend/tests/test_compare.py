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
    saved = json.loads(out.with_suffix(".json").read_text())
    assert "| model:" in printed.stdout and saved["fits"]["model"]["r2"] > .9 and saved["filters"]["model"] is None  # 3 s: too short


def test_steering_curve_bins_turning_by_target_bearing():
    t = np.linspace(0, 2, 201)
    x, y, yaw = t * 5, np.zeros_like(t), np.zeros_like(t)  # straight at a target dead ahead
    rows = compare.steering_curve(t, x, y, yaw, (20, 0))
    ahead = next(r for r in rows if r["bearing_from_deg"] == 0)
    assert ahead["samples"] == len(t) and ahead["mean_rightward_deg_s"] == 0
    assert sum(r["samples"] for r in rows) == len(t)


def synthetic_dual_mat(path, seconds=60, fs=10000, lag_s=.15, gain=2.0, positive_yaw="right", seed=1):
    """A labeled fixture in the layout of the Rayshubskiy et al. dual recordings: two voltage traces with
    2.5 mV spikes at known Poisson times, and yaw following gain × (R − L true rate) after lag_s."""
    import scipy.io
    rng = np.random.default_rng(seed)
    t_ephys = np.arange(seconds * fs) / fs
    t_ball = np.arange(seconds * 100) / 100 + .005
    rate = {"left": 40 + 30 * np.sin(2 * np.pi * .21 * t_ephys), "right": 40 + 30 * np.sin(2 * np.pi * .33 * t_ephys + 1)}
    shape = 2.5 * np.exp(-.5 * (np.arange(-30, 31) / 6) ** 2)
    traces, truth = {}, {}
    for side, key in (("left", "ephys_A"), ("right", "ephys_B")):
        spikes = np.flatnonzero(rng.random(len(t_ephys)) < rate[side] / fs)
        spikes = spikes[np.concatenate([[True], np.diff(spikes) > 40])]  # no overlapping spikes
        v = rng.normal(0, .05, len(t_ephys)) - 45  # spikes about 30 noise SDs tall, like the real recordings
        for s in spikes[(spikes > 30) & (spikes < len(v) - 31)]:
            v[s - 30:s + 31] += shape
        traces[key], truth[side] = v, spikes
    true_difference = np.interp(t_ball - lag_s, t_ephys, rate["right"] - rate["left"])
    rightward = gain * true_difference + rng.normal(0, 5, len(t_ball))
    yaw = (rightward if positive_yaw == "right" else -rightward) / compare.RAYSHUBSKIY_YAW_TO_DEG_S
    scipy.io.savemat(path, {"ephys_A": traces["ephys_A"][:, None], "ephys_B": traces["ephys_B"][:, None],
                            "ephys_SR": float(fs), "ball_SR": 100.0, "t_ephys": t_ephys[:, None], "t_ball": t_ball[:, None],
                            "yaw": yaw[:, None], "fwd": np.zeros((len(t_ball), 1)), "lat": np.zeros((len(t_ball), 1)),
                            "stim": np.zeros((1, len(t_ephys)), dtype=np.uint8)})
    return truth


def test_dual_recordings_convert_to_rates_and_rightward_turning(tmp_path):
    path = tmp_path / "dual.mat"
    truth = synthetic_dual_mat(path)
    recording, summary = compare.rayshubskiy_recording(path)
    for side in ("left", "right"):
        assert summary["spikes"][side] == pytest.approx(len(truth[side]), rel=.05)
    assert summary["conversion"]["left"] == "ephys_A" and summary["conversion"]["positive_yaw"] == "right"
    for side, rates in (("left", recording.left), ("right", recording.right)):  # injected spikes per second
        assert rates.mean() == pytest.approx(len(truth[side]) / 60, rel=.05)
    fit = compare.fit_turning(recording)
    # Rates estimated from ~40 spikes/s with 25 ms smoothing are noisy: that attenuates the fitted gain and
    # flattens the lag optimum of these slow signals, but not the sign.
    assert fit["correlation_sign"] == 1 and .03 <= fit["lag_s"] <= .25 and .4 * 2 < fit["gain"] <= 2.1
    assert compare.fit_filter(recording)["heldout_r2"] > .5
    flipped, _ = compare.rayshubskiy_recording(path, positive_yaw="left")
    assert compare.fit_turning(flipped)["correlation_sign"] == -1
    out = tmp_path / "dual.csv"
    compare.save_recording(recording, out)
    assert compare.fit_turning(compare.load_recording(out))["lag_s"] == fit["lag_s"]
    with pytest.raises(ValueError):
        compare.rayshubskiy_recording(path, positive_yaw="up")


def test_the_linear_filter_predicts_held_out_turning():
    recording = compare.Recording(*synthetic_fly())
    filt = compare.fit_filter(recording, max_lag_s=.3)
    assert filt["heldout_r2"] > .9 and filt["peak_lag_s"] == pytest.approx(.12, abs=.011)
    assert filt["summed_gain"] == pytest.approx(2.5, rel=.05) and len(filt["kernel"]) == 31
    noise = compare.Recording(*synthetic_fly(gain=0))
    assert compare.fit_filter(noise, max_lag_s=.3)["heldout_r2"] < .05


def test_jumping_target_runs_export_for_comparison(tmp_path):
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 2})
    result = toolkit.jumping_target_run(config, duration_s=3, every_s=1, seed=5, export_dir=tmp_path)
    run = Path(result["path"])
    events = json.loads((run / "metadata.json").read_text())["events"]
    assert sum(e["kind"] == "stimulus" for e in events) == 3 and result["samples"] == 301
    assert compare.model_recording(run).readout == "DNa02"


def test_recorded_downloads_are_complete_and_verified(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fetch_recording", ROOT / "scripts/fetch_recording.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    for record in json.loads((ROOT / "data/recordings/downloads.json").read_text()):
        assert record["url"].startswith("https://") and record["bytes"] > 0 and "CC0" in record["license"]
        assert len(record["sha256"]) == 64 and len(record["md5"]) == 32 and record["retrieved_utc"]
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"fly")
    import hashlib
    good = {"bytes": 3, "md5": hashlib.md5(b"fly").hexdigest(), "sha256": hashlib.sha256(b"fly").hexdigest()}
    assert fetch.verify(sample, good) == []
    assert len(fetch.verify(sample, {**good, "bytes": 4, "sha256": "0" * 64})) == 2


@pytest.mark.skipif(not (ROOT / ".cache/recordings/rayshubskiy2025-a2_d_13.mat").is_file(),
                    reason="needs the downloaded recording (scripts/fetch_recording.py)")
def test_the_downloaded_recording_converts_as_documented():
    recording, summary = compare.rayshubskiy_recording(ROOT / ".cache/recordings/rayshubskiy2025-a2_d_13.mat")
    assert summary["duration_s"] == 575 and summary["spikes"] == {"left": 571, "right": 1888}
    fit = compare.fit_turning(recording)
    assert fit["lag_s"] == pytest.approx(.18) and fit["gain"] == pytest.approx(3.359, abs=.001)
    assert compare.fit_filter(recording)["heldout_r2"] == pytest.approx(.097, abs=.001)
