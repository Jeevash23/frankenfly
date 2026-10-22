"""Bounded local performance measurements; each writes a JSON report to docs/evidence/ (or --out).

    backend/.venv/bin/python scripts/benchmark.py                          # the app's worker: real-time factor and memory
    backend/.venv/bin/python scripts/benchmark.py --vision                 # with rendered compound-eye input
    backend/.venv/bin/python scripts/benchmark.py --model connectome_dna02 # the connectome model, DNa02 circuit
    backend/.venv/bin/python scripts/benchmark.py --neural                 # wall time per 1 ms neural step
    backend/.venv/bin/python scripts/benchmark.py --flyvis                 # FlyVis eyes, alone and in closed loop

The worker benchmark and the FlyVis closed loop need FlyGym graphics; the neural-step timing does not.
--neural times every committed circuit with rate and spiking dynamics, plus any local whole-brain build
(scripts/build_circuit.py build --whole-brain), or the circuits named with --circuit. --flyvis needs the
optional vision lock and scripts/fetch_flyvis.py, and reports why it was skipped otherwise.
"""
import argparse
import json
import platform
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly import __version__ as APPLICATION_VERSION  # noqa: E402
SCOPE = "One local process, CPU, one fly. Startup excluded; no cross-device claims."


def write(result, name, out):
    path = Path(out) if out else ROOT / "docs/evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


def worker_benchmark(args):
    """The app's own worker for 2 simulated seconds with the body camera rendering."""
    import psutil
    from digitalfly.api.models import RunConfig
    from digitalfly.simulation.worker import SimulationWorker
    sensor_model = 'vision' if args.vision else 'geometric'
    worker = SimulationWorker(RunConfig(speed=2, sensor_model=sensor_model, neural_model=args.model), render=True)
    worker.start()
    try:
        assert worker.ready.wait(30), "Worker initialization timed out"
        assert worker.get_snapshot()["status"] == "paused", worker.get_snapshot()["error"]
        assert worker.get_snapshot()["rendering"], worker.get_snapshot()["render_error"]
        start_rss = psutil.Process().memory_info().rss / 1e6
        peak_rss = start_rss
        worker.submit("run").result(5)
        started = time.perf_counter()
        while worker.get_snapshot()["sample"]["t"] < 2 and time.perf_counter() - started < 25:
            time.sleep(.1)
            peak_rss = max(peak_rss, psutil.Process().memory_info().rss / 1e6)
        state = worker.submit("pause").result(5)
        assert state["status"] == "paused", state["error"]
        result = {
            "platform": platform.platform(), "python": platform.python_version(), "engine": "FlyGym 2.1.0",
            "controller": f"{args.model} neural model + upstream hybrid turning", "render_resolution": [640, 288],
            "sensor_model": sensor_model, "neural_model": args.model, "application_version": APPLICATION_VERSION,
            "eye_ommatidia_per_eye": state['vision'].get('ommatidia_per_eye'),
            "vertical_field_of_view_degrees": 35,
            "render_target_wall_hz": 10, "requested_speed": 2,
            "simulated_s": state["sample"]["t"], "active_wall_s": state["wall_s"],
            "measured_real_time_factor": state["real_time_factor"],
            "compute_real_time_factor": state["compute_real_time_factor"],
            "start_rss_mb": start_rss, "peak_sampled_rss_mb": peak_rss,
            "final_rss_mb": psutil.Process().memory_info().rss / 1e6,
            "physics_steps": state["sample"]["step"] * 100,
            "rendered_frames": state["frame_revision"], "finite": True,
            "scope": SCOPE,
        }
    finally:
        worker.close()
    result["worker_cleanly_stopped"] = not worker.thread.is_alive()
    write(result, f"research-performance-{sensor_model}-{args.model}.json", args.out)


def neural_circuits():
    """Every committed circuit, then local whole-brain builds."""
    from digitalfly.neural.connectome import list_circuits
    return [c["name"] for c in list_circuits() if "error" not in c and (c["committed"] or c["build"].get("whole_brain"))]


def time_neural_step(circuit: str, dynamics: str, steps: int = 1000, warmup: int = 100) -> dict:
    """Wall time of one 1 ms neural step of a circuit under constant, equal sensor input, after a warm-up."""
    from digitalfly.api.models import ConnectomeParameters, Interventions, SensorState
    from digitalfly.neural.connectome import ConnectomeCircuit
    sensors, none = SensorState(left=.5, right=.5), Interventions()
    model = ConnectomeCircuit(ConnectomeParameters(circuit=circuit, dynamics=dynamics))
    model.reset(0)
    for _ in range(warmup):
        model.advance(sensors, none)
    start = time.perf_counter()
    for _ in range(steps):
        model.advance(sensors, none)
    elapsed = time.perf_counter() - start
    return {"circuit": circuit, "circuit_sha256": model.data.sha256, "neurons": len(model.data.ids),
            "whole_brain": bool(model.data.info["build"].get("whole_brain")), "dynamics": dynamics,
            "steps": steps, "warmup_steps": warmup, "ms_per_step": elapsed / steps * 1000,
            "real_time_factor": 1 / (elapsed / steps * 1000) if elapsed else None}


def neural_benchmark(args):
    from importlib.metadata import version
    circuits = args.circuit or neural_circuits()
    rows = []
    for circuit in circuits:
        for dynamics in ("rate", "spiking"):
            row = time_neural_step(circuit, dynamics, args.steps, args.warmup)
            rows.append(row)
            print(f"{circuit} ({row['neurons']:,} neurons) {dynamics}: {row['ms_per_step']:.3f} ms of wall time "
                  f"per 1 ms neural step", flush=True)
    write({"platform": platform.platform(), "python": platform.python_version(),
           "application_version": APPLICATION_VERSION,
           "packages": {name: version(name) for name in ("numpy", "scipy", "numba")},
           "measurement": "ConnectomeCircuit.advance with both sensors at 0.5, no interventions, seed 0; wall time "
                          "per 1 ms step after the warm-up steps",
           "rows": rows, "scope": SCOPE}, "neural-step.json", args.out)


def flyvis_benchmark(args):
    from digitalfly.vision.flyvis_eyes import available
    ok, reason = available()
    result = {"platform": platform.platform(), "python": platform.python_version(),
              "application_version": APPLICATION_VERSION, "available": ok, "scope": SCOPE}
    if not ok:
        print(f"Skipped: {reason}")
        write({**result, "skipped": reason}, "flyvis-timing.json", args.out)
        return
    import numpy as np
    from digitalfly import toolkit
    from digitalfly.simulation.experiment import Experiment
    from digitalfly.vision.flyvis_eyes import FlyVisEyes
    eyes, grey = FlyVisEyes(), np.full(721, .5)
    eyes.step(grey, grey)
    start = time.perf_counter()
    for _ in range(100):
        eyes.step(grey, grey)
    result["eyes_ms_per_10ms_step"] = (time.perf_counter() - start) * 10
    print(f"FlyVis: {result['eyes_ms_per_10ms_step']:.1f} ms per 10 ms step, both eyes", flush=True)
    result["closed_loop"] = []
    for circuit in args.circuit or ["fafb783-dna02", "fafb783-steering"]:
        try:
            exp = Experiment(toolkit.configure({"engine": "flygym", "neural_model": "connectome", "sensor_model": "flyvis",
                                                "connectome_parameters": {"circuit": circuit}}), render=False, record=False)
            if exp.status != "paused":
                raise RuntimeError(exp.error)
            try:
                for _ in range(10):
                    exp.advance()  # first observation and adaptation
                start = time.perf_counter()
                for _ in range(round(args.seconds * 100)):
                    exp.advance()
                factor = args.seconds / (time.perf_counter() - start)
            finally:
                exp.close()
            result["closed_loop"].append({"circuit": circuit, "simulated_s": args.seconds, "real_time_factor": factor})
            print(f"{circuit} with FlyVis eyes: {factor:.2f}x real time, without the body camera", flush=True)
        except Exception as exc:  # usually missing graphics or a circuit without a FlyVis bridge
            result["closed_loop"].append({"circuit": circuit, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{circuit} with FlyVis eyes: not measured ({type(exc).__name__}: {exc})", flush=True)
    write(result, "flyvis-timing.json", args.out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--neural', action='store_true', help='Time the neural step alone (no physics or graphics)')
    mode.add_argument('--flyvis', action='store_true', help='Time the FlyVis eyes, alone and in FlyGym closed loop')
    parser.add_argument('--vision', action='store_true', help='Benchmark rendered compound-eye inputs')
    parser.add_argument('--model', choices=['engineered', 'connectome_dna02'], default='engineered', help='Neural model to drive the body')
    parser.add_argument('--circuit', action='append', default=[],
                        help='--neural/--flyvis: a circuit to time (repeatable; default: see above)')
    parser.add_argument('--steps', type=int, default=1000, help='--neural: timed 1 ms steps per circuit and dynamics')
    parser.add_argument('--warmup', type=int, default=100, help='--neural: untimed steps first')
    parser.add_argument('--seconds', type=float, default=2.0, help='--flyvis: simulated seconds of closed loop per circuit')
    parser.add_argument('--out', help='JSON report path (default: a file in docs/evidence/)')
    args = parser.parse_args(argv)
    if (args.neural or args.flyvis) and (args.vision or args.model != 'engineered'):
        parser.error("--vision and --model apply to the worker benchmark, not --neural or --flyvis")
    (neural_benchmark if args.neural else flyvis_benchmark if args.flyvis else worker_benchmark)(args)


if __name__ == "__main__":
    main()
