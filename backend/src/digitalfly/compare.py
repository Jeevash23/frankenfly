"""Compare the model with recorded flies: turning against the right − left readout difference.

Rayshubskiy et al. 2025 (eLife 13:RP102230) found that a walking fly's rotational velocity is a
linear function of the right − left difference in DNa02 firing rate, with turning lagging the
neurons. The same fit, applied to a recording and to a simulated run, compares the two on equal
terms: sign, lag, gain and the fraction of turning explained.

Recordings use one documented CSV format (or a NumPy archive with the same column names):

    t_s                       time in seconds, increasing
    rate_left_hz              firing rate of the left neuron(s) of the readout type
    rate_right_hz             firing rate of the right neuron(s)
    rotational_velocity_deg_s rightward (clockwise seen from above) positive
    forward_velocity_mm_s     optional
    valid                     optional, 1 or 0; samples marked 0 (such as stimulation epochs) are left out of fits

DigitalFly runs exported from the app are read directly from their telemetry.csv. Model rates are
dimensionless for rate dynamics; spiking runs are converted back to spikes/s with the run's rate
scale. `rayshubskiy_recording` converts the paired DNa02 recordings of Rayshubskiy et al. 2025
(Harvard Dataverse doi:10.7910/DVN/0NCLP1, CC0) to this format and, by default, marks the samples
during and shortly after the optogenetic stimulus as not valid; nothing here downloads data.
"""
import csv
import json
import math
from pathlib import Path
import numpy as np

COLUMNS = ["t_s", "rate_left_hz", "rate_right_hz", "rotational_velocity_deg_s"]


class Recording:
    """Uniformly resampled time series of one readout pair and turning. `valid` (optional, one flag per input
    sample) marks samples the fits must leave out; a resampled bin is valid only if both neighbours are."""

    def __init__(self, t, left, right, rotation, forward=None, source="", units="spikes/s", readout="DNa02",
                 bin_s=0.01, valid=None):
        t, left, right, rotation = (np.asarray(a, dtype=np.float64) for a in (t, left, right, rotation))
        if not (len(t) == len(left) == len(right) == len(rotation)) or len(t) < 3:
            raise ValueError("A recording needs at least three samples of time, both rates and rotation.")
        if not np.all(np.isfinite([t, left, right, rotation])) or np.any(np.diff(t) <= 0):
            raise ValueError("Times must increase and every value must be a finite number.")
        valid = np.ones(len(t), dtype=bool) if valid is None else np.asarray(valid, dtype=bool)
        if len(valid) != len(t):
            raise ValueError("The valid flags need one value per sample.")
        grid = np.arange(t[0], t[-1] + bin_s / 2, bin_s)
        self.t = grid
        self.left, self.right, self.rotation = (np.interp(grid, t, a) for a in (left, right, rotation))
        self.forward = None if forward is None else np.interp(grid, t, np.asarray(forward, dtype=np.float64))
        self.valid = np.interp(grid, t, valid.astype(np.float64)) > 1 - 1e-9
        self.source, self.units, self.readout, self.bin_s = source, units, readout, bin_s

    @property
    def difference(self):
        return self.right - self.left


def load_recording(path: str | Path, readout: str = "DNa02", bin_s: float = 0.01) -> Recording:
    """A recording in the documented CSV (or .npz) format."""
    path = Path(path)
    if path.suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            data = {key: archive[key] for key in archive.files}
    else:
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            raise ValueError(f"{path.name} has no rows.")
        data = {key: np.array([float(r[key]) for r in rows]) for key in rows[0]
                if key in COLUMNS + ["forward_velocity_mm_s", "valid"]}
    missing = [c for c in COLUMNS if c not in data]
    if missing:
        raise ValueError(f"{path.name} lacks the columns {', '.join(missing)}. Expected: {', '.join(COLUMNS)}.")
    return Recording(data["t_s"], data["rate_left_hz"], data["rate_right_hz"], data["rotational_velocity_deg_s"],
                     data.get("forward_velocity_mm_s"), source=path.name, readout=readout, bin_s=bin_s,
                     valid=None if data.get("valid") is None else np.asarray(data["valid"]) > 0)


def model_recording(run: str | Path, readout: str | None = None, bin_s: float = 0.01) -> Recording:
    """An exported DigitalFly run (its folder) as a recording of one readout type and turning."""
    run = Path(run)
    metadata = json.loads((run / "metadata.json").read_text())
    neural = metadata["neural"]
    if neural.get("kind") not in ("connectome", "connectome_dna02"):
        raise ValueError("Only connectome runs have a readout to compare.")
    names = [item["cell_type"] for item in neural.get("readout", [])] or ["DNa02"]
    readout = readout or names[0]
    if readout not in names:
        raise ValueError(f"{readout} is not a readout of this run; it read out {', '.join(names)}.")
    with (run / "telemetry.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    key = readout.lower().replace(" ", "_")
    t = np.array([float(r["time_s"]) for r in rows])
    yaw = np.unwrap(np.array([float(r["yaw_rad"]) for r in rows]))
    left = np.array([float(r[f"rate_{key}_l"]) for r in rows])
    right = np.array([float(r[f"rate_{key}_r"]) for r in rows])
    spiking = neural.get("dynamics") == "spiking"
    scale = float(neural["parameters"]["spiking"]["rate_scale_hz"]) if spiking else 1.0
    # Yaw is counterclockwise; rightward rotation is its negative rate.
    rotation = -np.degrees(np.gradient(yaw, t))
    return Recording(t, left * scale, right * scale, rotation,
                     [float(r["speed_mm_s"]) for r in rows], source=f"DigitalFly run {metadata['run_id']}",
                     units="spikes/s" if spiking else "dimensionless rate", readout=readout, bin_s=bin_s)


def fit_turning(recording: Recording, max_lag_s: float = 0.5) -> dict:
    """rotation(t + lag) ≈ gain × (right − left)(t) + offset, choosing the lag (0..max) with the best r².
    A pair of samples counts only when both are valid."""
    x, y, valid = recording.difference, recording.rotation, recording.valid
    best = None
    for k in range(0, int(round(max_lag_s / recording.bin_s)) + 1):
        xs, ys = x[:len(x) - k] if k else x, y[k:]
        keep = valid[:len(valid) - k] & valid[k:] if k else valid
        if not keep.all():
            xs, ys = xs[keep], ys[keep]
        if len(xs) < 3 or np.ptp(xs) == 0:
            continue
        gain, offset = np.polyfit(xs, ys, 1)
        residual = ys - (gain * xs + offset)
        total = float(np.sum((ys - ys.mean()) ** 2))
        r2 = 1 - float(np.sum(residual ** 2)) / total if total > 0 else 0.0
        if best is None or r2 > best["r2"]:
            best = {"lag_s": round(k * recording.bin_s, 6), "gain": float(gain), "offset_deg_s": float(offset),
                    "r2": r2, "samples": int(len(xs))}
    if best is None:
        raise ValueError("The right − left difference never changes, so turning cannot be fitted to it.")
    return {**best, "gain_units": f"deg/s per {recording.units}", "readout": recording.readout,
            "source": recording.source, "correlation_sign": int(math.copysign(1, best["gain"])) if best["gain"] else 0}


def fit_filter(recording: Recording, max_lag_s: float = 0.5, ridge: float = 1.0, folds: int = 5) -> dict:
    """A linear filter from the right − left difference to rotation (lags 0..max_lag_s), fitted by ridge
    regression, with r² measured on held-out contiguous blocks (k-fold), as a fairer measure of how much
    turning the readout predicts than the single-lag fit. Rayshubskiy et al. used linear filters this way.
    A row counts only when its rotation and every lagged input are valid."""
    x, y, valid = recording.difference, recording.rotation, recording.valid
    lags = int(round(max_lag_s / recording.bin_s)) + 1
    if len(x) < lags * folds * 2:
        raise ValueError("The recording is too short for this many lags and folds.")
    design = np.stack([np.concatenate([np.zeros(k), x[:len(x) - k]]) for k in range(lags)], axis=1)[lags:]
    target = y[lags:]
    usable = np.all([valid[lags - k:len(valid) - k] for k in range(lags)], axis=0)
    if usable.sum() < lags * folds * 2:
        raise ValueError("Too few valid samples for this many lags and folds.")
    edges = np.linspace(0, len(target), folds + 1).astype(int)
    predicted = np.empty_like(target)

    def solve(a, b):
        mean_a, mean_b = a.mean(axis=0), b.mean()
        a0 = a - mean_a
        scale = np.trace(a0.T @ a0) / a0.shape[1] or 1.0
        kernel = np.linalg.solve(a0.T @ a0 + ridge * scale * np.eye(a.shape[1]), a0.T @ (b - mean_b))
        return kernel, mean_b - mean_a @ kernel

    for k in range(folds):
        test = np.zeros(len(target), dtype=bool)
        test[edges[k]:edges[k + 1]] = True
        kernel, intercept = solve(design[~test & usable], target[~test & usable])
        predicted[test] = design[test] @ kernel + intercept
    kernel, intercept = solve(design[usable], target[usable])
    target, predicted = target[usable], predicted[usable]
    total = float(np.sum((target - target.mean()) ** 2))
    r2 = 1 - float(np.sum((target - predicted) ** 2)) / total if total > 0 else 0.0
    peak = int(np.argmax(np.abs(kernel)))
    return {"heldout_r2": r2, "folds": folds, "ridge": ridge, "lag_s": [round(k * recording.bin_s, 6) for k in range(lags)],
            "kernel": kernel.tolist(), "kernel_units": f"deg/s per {recording.units} per bin",
            "summed_gain": float(kernel.sum()), "peak_lag_s": round(peak * recording.bin_s, 6),
            "source": recording.source, "readout": recording.readout}


def compare(fly: Recording, model: Recording, max_lag_s: float = 0.5) -> dict:
    """The same fit on a recorded fly and a simulated run, side by side."""
    a, b = fit_turning(fly, max_lag_s), fit_turning(model, max_lag_s)
    same_units = fly.units == model.units
    return {
        "fly": a, "model": b,
        "same_sign": a["correlation_sign"] == b["correlation_sign"],
        "lag_difference_s": round(b["lag_s"] - a["lag_s"], 6),
        "gain_ratio_model_to_fly": b["gain"] / a["gain"] if same_units and a["gain"] else None,
        "note": ("Gains compare directly only when both rates are in spikes/s (spiking dynamics). Rate-model "
                 "activity is dimensionless, so compare sign, lag and r² instead. A matching fit is not "
                 "validation: the model's turning is wired to its readout by construction."),
    }


def steering_curve(t, x, y, yaw, target, bins=np.arange(-180, 181, 30)) -> list[dict]:
    """Mean rightward turning rate by the target's bearing from the heading (positive = target on the left):
    a common way to compare steering between animals and models on target-directed walks."""
    t, x, y, yaw = (np.asarray(a, dtype=np.float64) for a in (t, x, y, yaw))
    yaw = np.unwrap(yaw)
    rotation = -np.degrees(np.gradient(yaw, t))
    bearing = np.degrees(np.arctan2(target[1] - y, target[0] - x) - yaw)
    bearing = (bearing + 180) % 360 - 180
    rows = []
    for low, high in zip(bins[:-1], bins[1:]):
        inside = (bearing >= low) & (bearing < high)
        rows.append({"bearing_from_deg": float(low), "bearing_to_deg": float(high), "samples": int(inside.sum()),
                     "mean_rightward_deg_s": float(rotation[inside].mean()) if inside.any() else None})
    return rows


# Rayshubskiy et al. 2025 recordings, following the authors' secondary analysis code
# (github.com/wilson-lab/rayshubskiy_elife_102230_secondary_analysis_code, MIT): ephys_A is the left
# and ephys_B the right neuron of a dual recording, and yaw in the file × 0.000395 / 0.000436 is deg/s.
# The sign of yaw is not documented for these files. One of the authors' MATLAB scripts, working from
# their raw data, labels positive yaw as left turns; in the dual DNa02 file we checked, positive yaw
# instead follows right − left DNa02 firing, which the paper's main result (the left DNa02 bursts and the
# fly turns left) makes rightward. The default follows that inference; it is a setting, and the sign of
# a fit made with it is therefore not an independent test of turning direction.
RAYSHUBSKIY_YAW_TO_DEG_S = 0.000395 / 0.000436
RAYSHUBSKIY_SPIKES = {"height": 2.5, "prominence": 15.0, "window_s": 10.0, "bin_s": .0125, "sigma_s": .025}
# Samples while the optogenetic stimulus is on, and this long after it, are left out of fits by default
# (engineered choice: the fits' default longest lag, so no lag pairs a stimulated sample with a later one).
STIMULUS_MARGIN_S = 0.5


def stimulus_mask(stim, t_stim, t, margin_s: float = STIMULUS_MARGIN_S) -> np.ndarray:
    """True at each time in `t` when the stimulus was on then or within the preceding `margin_s` seconds."""
    on = np.concatenate([[0], np.cumsum(np.asarray(stim, dtype=np.float64).ravel() > 0)])
    t_stim, t = np.asarray(t_stim, dtype=np.float64).ravel(), np.asarray(t, dtype=np.float64)
    return on[np.searchsorted(t_stim, t, side="right")] > on[np.searchsorted(t_stim, t - margin_s, side="left")]


def detect_spikes(voltage, fs: int, height: float = 2.5, prominence: float = 15.0, window_s: float = 10.0) -> np.ndarray:
    """Spike sample indices in a whole-cell voltage trace, after the authors' `process_voltage_spike_detection`
    and `detect_spikes`: a zero-phase first-order Butterworth high-pass (~100 Hz), division by a rolling
    1 s median absolute deviation (averaged over three offset chunkings), then scipy's find_peaks.
    As in their code, the rolling MAD (not the median) is subtracted before dividing; a high-passed trace's
    median is near zero, so this only shifts the height threshold by about one MAD."""
    from scipy.signal import butter, buttord, filtfilt, find_peaks
    v = np.asarray(voltage, dtype=np.float64)
    fs = int(fs)
    order, wn = buttord(wp=100, ws=.05, gpass=3, gstop=30, fs=fs)
    b, a = butter(order, wn, btype="high", fs=fs)
    v = filtfilt(b, a, v)
    usable = len(v) - len(v) % fs
    if usable < fs:
        raise ValueError("A voltage trace needs at least one second of samples.")
    mads = []
    for shift in (-fs // 2, 0, fs // 2):
        chunks = np.roll(v[:usable], shift).reshape(-1, fs)
        mads.append(np.median(np.abs(chunks - np.median(chunks, axis=1, keepdims=True)), axis=1) * 1.4826)
    mad = np.mean(mads, axis=0)
    centres = (np.arange(len(mad)) + .5) * fs
    rolling = np.maximum(np.interp(np.arange(len(v)), centres, mad), 1e-12)
    z = (v - rolling) / rolling
    peaks, _ = find_peaks(z, height=height, wlen=int(window_s * fs), prominence=prominence)
    return peaks


def firing_rate(spikes: np.ndarray, fs: int, t_out, t0: float = 0.0, bin_s: float = .0125, sigma_s: float = .025) -> np.ndarray:
    """Spikes/s at the times t_out: counts in bins, smoothed with a normalized Gaussian, as in the authors'
    `bin_spikes` and `estimate_fr` (they upsample with cubic interpolation; here it is linear)."""
    t_out = np.asarray(t_out, dtype=np.float64)
    times = t0 + np.asarray(spikes, dtype=np.float64) / fs
    edges = np.arange(t0, t_out[-1] + 2 * bin_s, bin_s)
    counts, _ = np.histogram(times, edges)
    tau = np.arange(-5 * sigma_s, 5 * sigma_s + bin_s / 2, bin_s)
    kernel = np.exp(-.5 * (tau / sigma_s) ** 2)
    rate = np.convolve(counts, kernel / kernel.sum(), mode="same") / bin_s
    return np.maximum(np.interp(t_out, edges[:-1] + bin_s / 2, rate), 0)


def rayshubskiy_recording(path: str | Path, readout: str = "DNa02", bin_s: float = 0.01,
                          positive_yaw: str = "right", exclude_stimulus: bool = True,
                          stimulus_margin_s: float = STIMULUS_MARGIN_S) -> tuple[Recording, dict]:
    """A dual (left + right) recording from the Rayshubskiy et al. 2025 dataset, and a summary of the conversion.
    `positive_yaw` says which way the file's positive yaw turns ("right", inferred; or "left"). With
    `exclude_stimulus` (default) the samples during the optogenetic stimulus and `stimulus_margin_s` after it
    are marked not valid, so fits use spontaneous walking only; False keeps them, as before v0.6."""
    if positive_yaw not in ("right", "left"):
        raise ValueError("positive_yaw is 'right' or 'left'.")
    import scipy.io
    data = scipy.io.loadmat(path, squeeze_me=True)
    for key in ["ephys_A", "ephys_B", "ephys_SR", "ball_SR", "t_ball", "t_ephys", "yaw"]:
        if key not in data:
            raise ValueError(f"{Path(path).name} lacks {key}; it is not a dual recording from this dataset.")
    fs = int(data["ephys_SR"])
    t_ball = np.asarray(data["t_ball"], dtype=np.float64)
    t0 = float(np.asarray(data["t_ephys"], dtype=np.float64)[0])
    p = RAYSHUBSKIY_SPIKES
    spikes = {side: detect_spikes(data[key], fs, p["height"], p["prominence"], p["window_s"])
              for side, key in (("left", "ephys_A"), ("right", "ephys_B"))}
    rates = {side: firing_rate(idx, fs, t_ball, t0, p["bin_s"], p["sigma_s"]) for side, idx in spikes.items()}
    rotation = (1 if positive_yaw == "right" else -1) * np.asarray(data["yaw"], dtype=np.float64) * RAYSHUBSKIY_YAW_TO_DEG_S
    duration = len(np.asarray(data["ephys_A"])) / fs
    stim = np.asarray(data.get("stim", np.zeros(1)), dtype=np.float64).ravel()
    excluded = np.zeros(len(t_ball), dtype=bool)
    if exclude_stimulus and "stim" in data:
        t_ephys = np.asarray(data["t_ephys"], dtype=np.float64).ravel()
        t_stim = t_ephys if len(stim) == len(t_ephys) else t_ball if len(stim) == len(t_ball) else None
        if t_stim is None:
            raise ValueError(f"The stim channel has {len(stim)} samples, matching neither the ephys nor the ball clock; "
                             "pass exclude_stimulus=False (--include-stimulus) to fit without masking it.")
        excluded = stimulus_mask(stim, t_stim, t_ball, stimulus_margin_s)
    summary = {"source": Path(path).name, "duration_s": duration, "ephys_hz": fs, "ball_hz": int(data["ball_SR"]),
               "spikes": {side: int(len(idx)) for side, idx in spikes.items()},
               "mean_rate_hz": {side: len(idx) / duration for side, idx in spikes.items()},
               "stimulus_fraction": float((stim > 0).mean()),
               "stimulus": {"excluded": bool(exclude_stimulus), "margin_s": stimulus_margin_s if exclude_stimulus else None,
                            "excluded_fraction": float(excluded.mean()),
                            "rule": ("ball samples with the stimulus on, or on within the margin before them, are "
                                     "left out of fits" if exclude_stimulus else "stimulus epochs included in fits")},
               "conversion": {"left": "ephys_A", "right": "ephys_B",
                              "rotation_deg_s": f"{'' if positive_yaw == 'right' else '−'}yaw × 0.000395 / 0.000436 "
                                                f"(positive = rightward; the file's positive yaw taken as {positive_yaw}ward)",
                              "positive_yaw": positive_yaw,
                              "spike_detection": p}}
    recording = Recording(t_ball, rates["left"], rates["right"], rotation, source=Path(path).name,
                          readout=readout, bin_s=bin_s, valid=~excluded)
    return recording, summary


def rate_summary(recording: Recording) -> dict:
    """Mean, median and 99th percentile of each side's rate over the valid samples."""
    valid = recording.valid
    return {side: {"mean": float(np.mean(r[valid])), "median": float(np.median(r[valid])),
                   "p99": float(np.percentile(r[valid], 99))} if valid.any() else None
            for side, r in (("left", recording.left), ("right", recording.right))} | {"units": recording.units}


def save_recording(recording: Recording, path: str | Path):
    """Write a recording in the documented CSV format (with the valid column when any sample is excluded)."""
    flagged = not recording.valid.all()
    with Path(path).open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS + ["valid"] * flagged)
        for row in zip(recording.t, recording.left, recording.right, recording.rotation, recording.valid):
            writer.writerow([f"{row[0]:.4f}", f"{row[1]:.4f}", f"{row[2]:.4f}", f"{row[3]:.4f}"] + [int(row[4])] * flagged)
