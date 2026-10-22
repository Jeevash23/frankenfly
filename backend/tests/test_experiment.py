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


@pytest.mark.flygym
def test_fast_flygym_path_matches_upstream_controller_bitwise():
    # The adapter precomputes FlyGym's per-step lookups; the physics must not change at all.
    from digitalfly.simulation.engines import FlyGymBody
    fast, upstream = FlyGymBody(11, render=False), FlyGymBody(11, render=False, upstream=True)
    try:
        rng = np.random.default_rng(0)
        for _ in range(40):
            motor = rng.uniform(-.2, 1.4, size=2)
            fast.advance(motor)
            upstream.advance(motor)
            assert np.array_equal(fast.sim.mj_data.qpos, upstream.sim.mj_data.qpos)
            assert np.array_equal(fast.sim.mj_data.qvel, upstream.sim.mj_data.qvel)
            assert fast.body_signals() == upstream.body_signals()
            assert fast.pose() == upstream.pose()
    finally:
        fast.close()
        upstream.close()


@pytest.mark.flygym
@pytest.mark.render
def test_closing_a_replaced_body_leaves_the_new_body_rendering():
    # A reset builds the new body before closing the old one, so closing must not free the new body's GL objects.
    from digitalfly.simulation.engines import FlyGymBody

    def frame(body):
        body.renderer.update_scene(body.sim.mj_data, camera=body.camera.name)
        return body.renderer.render().astype(int)

    old = FlyGymBody(42, render=True)
    new = None
    try:
        old.advance(np.array([1., 1.]))
        old.frame()
        new = FlyGymBody(42, render=True)
        old.close()
        for _ in range(5):
            new.advance(np.array([1., 1.]))
        replaced = frame(new)
    finally:
        old.close()
        if new is not None:
            new.close()
    fresh = FlyGymBody(42, render=True)
    try:
        for _ in range(5):
            fresh.advance(np.array([1., 1.]))
        assert np.abs(replaced - frame(fresh)).mean() < 1
    finally:
        fresh.close()
