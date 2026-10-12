import json
import numpy as np
import pytest
from digitalfly.api.models import RunConfig, Stimulus, Interventions
from digitalfly.simulation.experiment import Experiment


def run_schedule(exp, n=100):
    for i in range(n):
        if i == 20:
            exp.set_stimulus(Stimulus(x=5, y=-9))
        if i == 50:
            exp.set_interventions(Interventions(zero_left=True))
        exp.advance()
    return np.array([exp.sample.pose.x, exp.sample.pose.y, exp.sample.pose.yaw, *exp.sample.rates])


@pytest.mark.parametrize("engine", ["toy", pytest.param("flygym", marks=pytest.mark.flygym)])
def test_real_stepping_finite_reset_repeatable(engine):
    exp = Experiment(RunConfig(engine=engine), render=False)
    try:
        assert exp.status == "paused", exp.error
        initial = exp.sample.model_dump()
        first = run_schedule(exp, 60)
        assert np.isfinite(first).all()
        assert abs(exp.sample.pose.x - initial["pose"]["x"]) > .1
        exp.reset(RunConfig(engine=engine))
        assert exp.sample.model_dump() == initial
        second = run_schedule(exp, 60)
        np.testing.assert_allclose(first, second, atol=1e-8, rtol=0)
    finally:
        exp.close()


@pytest.mark.parametrize("engine", ["toy", pytest.param("flygym", marks=pytest.mark.flygym)])
def test_interventions_change_behavior_and_direct_signals(engine):
    exp = Experiment(RunConfig(engine=engine), render=False)
    try:
        assert exp.status == "paused", exp.error
        for _ in range(50):
            exp.advance()
        normal = np.array([exp.sample.pose.x, exp.sample.pose.y])
        exp.reset(RunConfig(engine=engine))
        exp.set_interventions(Interventions(silence="descending"))
        for _ in range(50):
            exp.advance()
        assert exp.sample.motor == [0, 0]
        assert exp.sample.rates[4:] == [0, 0]
        assert np.linalg.norm(normal - [exp.sample.pose.x, exp.sample.pose.y]) > .1
        exp.reset(RunConfig(engine=engine))
        exp.set_interventions(Interventions(zero_left=True))
        for _ in range(50):
            exp.advance()
        assert exp.sample.sensors.left == 0
        assert exp.sample.rates[0] == 0
        assert np.linalg.norm(normal - [exp.sample.pose.x, exp.sample.pose.y]) > .02
    finally:
        exp.close()


def test_export_schedule_and_seed(tmp_path):
    exp = Experiment(RunConfig(engine="toy", seed=15), render=False)
    try:
        run_schedule(exp)
        result = exp.export(tmp_path)
        from pathlib import Path
        metadata = json.loads((Path(result["path"]) / "metadata.json").read_text())
        assert metadata["initial_config"]["seed"] == 15
        assert metadata["complete_from_reset"]
        assert [(e["kind"], e["step"]) for e in metadata["events"] if e["kind"] in {"stimulus", "interventions"}] == [("stimulus", 20), ("interventions", 50)]
        assert result["samples"] == 101
        assert (Path(result["path"]) / "telemetry.csv").read_text().count("\n") == 102
    finally:
        exp.close()
