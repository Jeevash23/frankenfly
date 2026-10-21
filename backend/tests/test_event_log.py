"""The run log keeps a bounded number of bookkeeping events (run, pause, step, speed, export), never changing replay."""
import json
import subprocess
import sys
from pathlib import Path
from digitalfly.api.models import RunConfig, Stimulus
from digitalfly.simulation import experiment
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]


def test_bookkeeping_events_are_capped_with_one_marker_without_changing_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "BOOKKEEPING_LIMIT", 6)
    exp = Experiment(RunConfig(engine="toy", seed=3), render=False)
    try:
        for i in range(30):
            exp.event("run", "Simulation started")
            exp.event("speed", "Requested speed 1×", {"speed": 1})
            exp.event("pause", "Simulation paused")
            exp.advance()
            if i == 15:
                exp.set_stimulus(Stimulus(x=3, y=-7))
        kinds = [event.kind for event in exp.events]
        assert sum(kind in experiment.BOOKKEEPING_KINDS for kind in kinds) == 6 and kinds.count("log_limit") == 1
        assert exp.events[kinds.index("log_limit")].message.endswith("(6 logged); they do not affect replay")
        assert kinds.count("stimulus") == 1 and [event.seq for event in exp.events] == list(range(len(kinds)))
        run = Path(exp.export(tmp_path)["path"])
        exp.reset(RunConfig(engine="toy"))
        exp.event("run", "Simulation started")
        assert [event.kind for event in exp.events] == ["reset", "run"]  # each run starts its own count
    finally:
        exp.close()
    done = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["passed"] and report["maximum_absolute_error"] == 0
