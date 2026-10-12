"""Bounded local throughput measurement with the actual application worker."""
import json
import argparse
import platform
from pathlib import Path
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly.api.models import RunConfig
from digitalfly.simulation.worker import SimulationWorker

parser = argparse.ArgumentParser()
parser.add_argument('--vision', action='store_true', help='Benchmark rendered compound-eye inputs')
args = parser.parse_args()
sensor_model = 'vision' if args.vision else 'geometric'
worker = SimulationWorker(RunConfig(speed=2, sensor_model=sensor_model), render=True)
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
        "controller": "engineered neural + upstream hybrid turning", "render_resolution": [640, 288],
        "sensor_model": sensor_model, "application_version": "0.2.0",
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
        "scope": "One local process, CPU, one fly. Startup excluded; no cross-device claims.",
    }
finally:
    worker.close()
result["worker_cleanly_stopped"] = not worker.thread.is_alive()
(ROOT / f"docs/evidence/research-performance-{sensor_model}.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
