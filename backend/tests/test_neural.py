import numpy as np
import pytest
from pydantic import ValidationError
from digitalfly.api.models import Interventions, Pose, Stimulus, RunConfig
from digitalfly.neural.model import RateCircuit, encode
from digitalfly.data.research import GraphEdge

POSE = Pose(x=0, y=0, z=.7, yaw=0, velocity=0)


def output(stimulus=Stimulus(), interventions=Interventions()):
    model = RateCircuit()
    sensors = encode(POSE, stimulus, interventions)
    for _ in range(500):
        model.advance(sensors, interventions)
    return sensors, model.rates, model.motor()


def test_closed_sensor_neural_motor_direction():
    left, rates, motor = output(Stimulus(x=10, y=10))
    assert left.left > left.right
    assert rates[2] > rates[3]
    assert motor[1] > motor[0]
    assert output(Stimulus(x=10, y=-10))[2][0] > output(Stimulus(x=10, y=-10))[2][1]


def test_interventions_affect_computed_signals():
    normal = output()
    sensors, rates, motor = output(interventions=Interventions(zero_left=True))
    assert sensors.raw_left > 0 and sensors.left == 0
    assert rates[0] == 0
    assert not np.allclose(normal[2], motor)
    _, rates, motor = output(interventions=Interventions(silence="descending"))
    assert np.all(motor == 0) and np.all(rates[4:] == 0)
    assert np.any(rates[:4] > 0)


def test_reset_and_baseline():
    model = RateCircuit()
    model.rates.fill(.5)
    model.reset()
    assert not model.rates.any()
    assert np.all(model.motor(baseline=True) == 1)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 99])
def test_invalid_stimulus(bad):
    with pytest.raises(ValidationError):
        Stimulus(x=bad)


def test_model_numerical_failure():
    model = RateCircuit()
    model.rates[0] = np.nan
    with pytest.raises(FloatingPointError):
        model.advance(encode(POSE, Stimulus(), Interventions()), Interventions())


def test_no_implicit_extra_inputs_or_lossy_ids():
    with pytest.raises(ValidationError):
        RunConfig(target_secret=10)
    edge = GraphEdge(pre_id="720575940123456789", post_id="2", synapse_count=1)
    assert edge.model_dump()["pre_id"] == "720575940123456789"
    with pytest.raises(ValidationError):
        GraphEdge(pre_id=720575940123456789, post_id="2", synapse_count=1)
