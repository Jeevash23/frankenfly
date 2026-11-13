"""Does the torch backend compute what the CPU backend computes? (scripts/benchmark.py --check, tests/test_gpu.py)

Rate dynamics are deterministic, so the two backends are run side by side through the same input schedule and
interventions and every neuron's rate is compared at every step: they must agree within float rounding.

Spiking dynamics draw their Poisson input from different generators, so single spike trains differ by design.
They are compared in distribution, in the style of the Eon Systems fly-brain harness (each simulator backend
against Brian2): for several seeds per backend, under the same constant input,
  - per-neuron firing rates: the correlation across neurons between a CPU run and a torch run must reach the
    correlation between two CPU runs with different seeds, less a margin;
  - the population rate (mean over neurons), of all neurons and of the recurrent ones (not driven by the sensors,
    so their rates follow the weights): the backends' means over seeds must differ by less than Welch's t at the
    99.9 % level times the standard error of the difference, plus 1 % of the rate;
  - the readout neurons' spike counts, per readout type and side, judged the same way.
With the defaults (eight seeds, 2 s) on the DNa02 circuit, a weight per synapse 5 % too large on the torch side fails
the recurrent rate test (+0.34 Hz against a bound of 0.20 Hz) and 2 % too large passes (+0.15 Hz). Four seeds were
too few: a noisy standard error made a correct backend fail now and then.
"""
import math
import numpy as np
from digitalfly.api.models import ConnectomeParameters, Interventions, SensorState

RATE_TOLERANCE = 1e-9  # largest |torch − CPU| rate allowed (dimensionless rates in [0, 1])
CORRELATION_MARGIN = 0.03  # torch-CPU per-neuron rate correlation may fall this far below CPU-CPU
RELATIVE_SLACK = 0.01  # population and readout means may also differ by 1 % (beyond the t bound)
CONFIDENCE = 0.001  # two-sided level of the t bound: a correct backend fails one metric in 1,000 by chance
SEEDS = tuple(range(8))


def _circuit(circuit: str | None, dynamics: str, backend: str, path=None, **changes):
    from digitalfly.neural.connectome import ConnectomeCircuit
    parameters = ConnectomeParameters(**({"circuit": circuit} if circuit else {}), dynamics=dynamics, backend=backend,
                                      **changes)
    return ConnectomeCircuit(parameters, path=path)


def rate_agreement(circuit: str | None = None, steps: int = 600, path=None, interventions: list | None = None) -> dict:
    """Rate dynamics on both backends through a changing input and, from the middle on, the interventions given
    (by default none). Returns the largest difference in any neuron's rate and in the readout."""
    cpu, gpu = _circuit(circuit, "rate", "cpu", path), _circuit(circuit, "rate", "torch", path)
    later = Interventions(cell_types=interventions or [])
    worst = readout_worst = 0.
    for k in range(steps):
        sensors = SensorState(left=.5 + .4 * math.sin(k / 37), right=.5 + .4 * math.cos(k / 53))
        applied = later if k >= steps // 2 else Interventions()
        if k == steps // 2:
            cpu.apply_silencing(applied)
            gpu.apply_silencing(applied)
        cpu.advance(sensors, applied)
        gpu.advance(sensors, applied)
        if k % 10 == 9 or k == steps - 1:  # as the app reads them: once per control interval
            worst = max(worst, float(np.abs(cpu.activity - gpu.activity).max()))
            readout_worst = max(readout_worst, float(np.abs(np.subtract(cpu.readout(), gpu.readout())).max()))
    return {"circuit": cpu.data.key, "neurons": len(cpu.data.ids), "steps": steps,
            "max_abs_difference": worst, "max_readout_difference": readout_worst,
            "tolerance": RATE_TOLERANCE, "passed": worst <= RATE_TOLERANCE and readout_worst <= RATE_TOLERANCE}


def _spike_run(circuit, backend, seed, steps, left, right, path):
    model = _circuit(circuit, "spiking", backend, path)
    model.reset(seed)
    n = len(model.data.ids)
    model.record_spikes(np.arange(n))
    sensors, none = SensorState(left=left, right=right), Interventions()
    for _ in range(steps):
        model.advance(sensors, none)
    spikes, _ = model.spike_record()
    counts = np.bincount(np.concatenate([hit for _, hit in spikes]) if spikes else np.array([], dtype=np.int64),
                         minlength=n).astype(np.float64)
    readout = {f"{name} {side}": float(counts[members].sum()) for name, left_, right_ in model.readouts
               for side, members in (("L", left_), ("R", right_))}
    return model, counts / (steps / 1000), readout


def _same_mean(a: list[float], b: list[float]) -> tuple[bool, float, float]:
    """(whether two sets of per-seed values share a mean, difference, bound). The bound is Welch's t at the 99.9 %
    two-sided level times the standard error of the difference, plus RELATIVE_SLACK of the larger mean."""
    from scipy import stats
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    va, vb = (a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)) if len(a) > 1 and len(b) > 1 else (0., 0.)
    se = math.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)) if va + vb > 0 else 1.
    bound = float(stats.t.ppf(1 - CONFIDENCE / 2, df)) * se + RELATIVE_SLACK * max(abs(a.mean()), abs(b.mean())) + 1e-9
    difference = float(b.mean() - a.mean())
    return bool(abs(difference) <= bound), difference, float(bound)


def spiking_agreement(circuit: str | None = None, seconds: float = 2.0, seeds=SEEDS, left: float = .6,
                      right: float = .4, path=None) -> dict:
    """Spiking dynamics on both backends, `seeds` runs each of `seconds` under constant sensor input."""
    steps = round(seconds * 1000)
    cpu = [_spike_run(circuit, "cpu", s, steps, left, right, path) for s in seeds]
    gpu = [_spike_run(circuit, "torch", s, steps, left, right, path) for s in seeds]
    model = cpu[0][0]
    inputs = np.zeros(len(model.data.ids), dtype=bool)
    inputs[model.input_left] = inputs[model.input_right] = True

    def corr(x, y):
        return float(np.corrcoef(x, y)[0, 1]) if x.std() and y.std() else float("nan")
    within = [corr(cpu[k][1], cpu[(k + 1) % len(seeds)][1]) for k in range(len(seeds))]
    across = [corr(cpu[k][1], gpu[k][1]) for k in range(len(seeds))]
    correlation_ok = bool(np.mean(across) >= np.mean(within) - CORRELATION_MARGIN)

    def compare(values) -> dict:
        a, b = [values(c) for c in cpu], [values(g) for g in gpu]
        ok, diff, bound = _same_mean(a, b)
        return {"cpu": float(np.mean(a)), "torch": float(np.mean(b)), "difference": diff, "bound": bound, "passed": ok}
    population = {"all": compare(lambda run: run[1].mean()),
                  # the neurons the sensors do not drive directly: their rates depend on the weights
                  "recurrent": compare(lambda run: run[1][~inputs].mean())}
    readout = {name: compare(lambda run, name=name: run[2][name]) for name in cpu[0][2]}
    active = [float((c[1] > 0).mean()) for c in cpu], [float((g[1] > 0).mean()) for g in gpu]
    return {
        "circuit": model.data.key, "neurons": len(model.data.ids), "seconds": seconds, "seeds": list(seeds),
        "input": {"left": left, "right": right},
        "per_neuron_rate_correlation": {"cpu_vs_cpu": float(np.mean(within)), "cpu_vs_torch": float(np.mean(across)),
                                        "margin": CORRELATION_MARGIN, "passed": correlation_ok},
        "population_rate_hz": population,
        "fraction_active": {"cpu": float(np.mean(active[0])), "torch": float(np.mean(active[1]))},
        "readout_spikes": readout,
        "passed": correlation_ok and all(p["passed"] for p in population.values())
        and all(r["passed"] for r in readout.values()),
    }
