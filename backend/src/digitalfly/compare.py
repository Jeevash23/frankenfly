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

DigitalFly runs exported from the app are read directly from their telemetry.csv. Model rates are
dimensionless for rate dynamics; spiking runs are converted back to spikes/s with the run's rate
scale. Converters for published datasets write this format; nothing here downloads data.
"""
import csv
import json
import math
from pathlib import Path
import numpy as np

COLUMNS = ["t_s", "rate_left_hz", "rate_right_hz", "rotational_velocity_deg_s"]


class Recording:
    """Uniformly resampled time series of one readout pair and turning."""

    def __init__(self, t, left, right, rotation, forward=None, source="", units="spikes/s", readout="DNa02",
                 bin_s=0.01):
        t, left, right, rotation = (np.asarray(a, dtype=np.float64) for a in (t, left, right, rotation))
        if not (len(t) == len(left) == len(right) == len(rotation)) or len(t) < 3:
            raise ValueError("A recording needs at least three samples of time, both rates and rotation.")
        if not np.all(np.isfinite([t, left, right, rotation])) or np.any(np.diff(t) <= 0):
            raise ValueError("Times must increase and every value must be a finite number.")
        grid = np.arange(t[0], t[-1] + bin_s / 2, bin_s)
        self.t = grid
        self.left, self.right, self.rotation = (np.interp(grid, t, a) for a in (left, right, rotation))
        self.forward = None if forward is None else np.interp(grid, t, np.asarray(forward, dtype=np.float64))
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
        data = {key: np.array([float(r[key]) for r in rows]) for key in rows[0] if key in COLUMNS + ["forward_velocity_mm_s"]}
    missing = [c for c in COLUMNS if c not in data]
    if missing:
        raise ValueError(f"{path.name} lacks the columns {', '.join(missing)}. Expected: {', '.join(COLUMNS)}.")
    return Recording(data["t_s"], data["rate_left_hz"], data["rate_right_hz"], data["rotational_velocity_deg_s"],
                     data.get("forward_velocity_mm_s"), source=path.name, readout=readout, bin_s=bin_s)


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
    """rotation(t + lag) ≈ gain × (right − left)(t) + offset, choosing the lag (0..max) with the best r²."""
    x, y = recording.difference, recording.rotation
    best = None
    for k in range(0, int(round(max_lag_s / recording.bin_s)) + 1):
        xs, ys = x[:len(x) - k] if k else x, y[k:]
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
