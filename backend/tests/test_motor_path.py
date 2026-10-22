"""The engineered motor path: readout weights and pooling, descending delay, low-pass, and the clipping diagnostic."""
import math
import numpy as np
import pytest
from pydantic import ValidationError
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, SensorState, Stimulus
from digitalfly.neural.connectome import MOTOR_SCALE, ConnectomeCircuit
from digitalfly.simulation.experiment import Experiment

NONE = Interventions()
# v0.5.0 output (commit c929052) for the default run below: {control step: [motor L, motor R, turn]}, final x, y, yaw.
# The final yaw integrates every motor command of the run. On the reference stack the match is exact (bit for bit).
V05 = {
    ("fafb783-dna02", "rate"): ({10: [0.21009675800327096, 0.7699032419967289, -0.1999308871405207], 30: [0.2103357706848146, 0.7696642293151854, -0.19976016379656097], 60: [0.16213737106583906, 0.8178626289341607, -0.2341875920958292]}, [2.5888056302190168, 1.928592180784775, 1.3873536686113535]),
    ("fafb783-dna02", "spiking"): ({10: [0.0, 1.0777409394349742, -0.4198149567392673], 30: [0.0, 0.9871512110069071, -0.3551080078620765], 60: [0.0, 1.2725924801928759, -0.5589946287091971]}, [0.4256302528777335, 3.032295436285111, 2.859630725681421]),
    ("fafb783-steering", "rate"): ({10: [0.20309592475668078, 0.7769040752433192, -0.20493148231665656], 30: [0.07984749893860037, 0.9001525010613995, -0.292966072186714], 60: [0.08056812003615504, 0.8994318799638448, -0.2924513428313178]}, [2.43608339803751, 1.922844992745521, 1.6459828978818796]),
    ("fafb783-steering", "spiking"): ({10: [0.0, 1.4, -2.428606731700221], 30: [0.0, 1.4, -1.322676531910977], 60: [0.0, 1.4, -0.8645773701746533]}, [-0.22098888285594892, 2.9811455151235173, -3.011592866797655]),
}


@pytest.mark.parametrize("circuit, dynamics", list(V05))
def test_default_motor_path_reproduces_v05(circuit, dynamics):
    expected, final = V05[(circuit, dynamics)]
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome", seed=42,
                               connectome_parameters={"circuit": circuit, "dynamics": dynamics}), render=False)
    try:
        assert exp.status == "paused", exp.error
        for step in range(1, 61):
            if step == 26:
                exp.set_stimulus(Stimulus(x=-10, y=14))  # an observation between steps must not count or shift anything
            exp.advance()
            if step in expected:
                assert [*exp.sample.motor, exp.circuit.turn()] == pytest.approx(expected[step], rel=1e-12, abs=1e-15)
        pose = exp.sample.pose
        assert [pose.x, pose.y, pose.yaw] == pytest.approx(final, rel=1e-12, abs=1e-15)
        assert exp.circuit._history is None and 0 <= exp.circuit.motor_clipped_fraction <= 1
    finally:
        exp.close()


def v05_motor(model):
    """The v0.5 motor equation, from the circuit's current activity."""
    r, p = model.activity, model.parameters
    turn = p.output_gain * float(sum(r[right].mean() - r[left].mean() for _, left, right in model.readouts))
    forward = p.tonic_drive if model.speed is None else p.tonic_drive + p.speed_gain * float(r[model.speed].mean())
    return np.clip(np.array([forward + turn, forward - turn]), 0, 1) * 1.4


@pytest.mark.parametrize("dynamics", ["rate", "spiking"])
def test_neutral_settings_change_nothing(dynamics):
    """Weights of 1, a single type pooled by mean, and a zero delay and low-pass are the v0.5 command exactly."""
    base = ConnectomeParameters(circuit="fafb783-steering", dynamics=dynamics)
    neutral = base.model_copy(update={"readout_weights": {"DNa01": 1., "DNa02": 1., "DNp09": 1.}})
    single = base.model_copy(update={"readout_types": ["DNp09"], "readout_pool": "mean"})
    rng = np.random.default_rng(5)
    sensors = [SensorState(left=a, right=b) for a, b in rng.uniform(0, 1, size=(150, 2))]
    models = [ConnectomeCircuit(p) for p in (base, neutral, single.model_copy(update={"readout_pool": "sum"}), single)]
    for model in models:
        model.reset(3)
    for s in sensors:
        commands = []
        for model in models:
            model.advance(s, NONE)
            commands.append(model.motor())
            assert np.array_equal(commands[-1], v05_motor(model))
        assert np.array_equal(commands[0], commands[1]) and np.array_equal(commands[2], commands[3])


def test_readout_weights_and_pooling(toy_brain):
    parameters = ConnectomeParameters(circuit="toy-brain", global_gain=.05, readout_types=["DNx", "DNy"], output_gain=1.5,
                                      readout_weights={"DNx": 2, "DNy": -.5}, readout_pool="mean")
    model = ConnectomeCircuit(parameters)
    for _ in range(300):
        model.advance(SensorState(left=1, right=.2), NONE)
    r = model.rates
    assert r[0] != r[1] and r[6] != r[7]
    assert model.turn() == pytest.approx(1.5 * (2 * (r[1] - r[0]) - .5 * (r[7] - r[6])) / 2)
    assert "turn = output gain × mean (right − left) over 2 × DNx, -0.5 × DNy" in model.description()["output_mapping"]
    for bad in [{"readout_weights": {"DNx": 6}}, {"readout_weights": {"DNx": float("nan")}}, {"readout_pool": "max"},
                {"motor_delay_ms": 501}, {"motor_delay_ms": -1}, {"motor_tau_ms": 1001}]:
        with pytest.raises(ValidationError):
            ConnectomeParameters(circuit="toy-brain", **bad)
    for readout in (None, ["DNx"]):  # None: the circuit's default readout, DNx
        stray = ConnectomeParameters(circuit="toy-brain", readout_types=readout, readout_weights={"DNy": 1})
        with pytest.raises(ValueError, match="not read out: DNy"):
            stray.check_against_circuit()
        with pytest.raises(ValueError, match="not read out: DNy"):
            ConnectomeCircuit(stray)
    with pytest.raises(ValidationError, match="not read out: DNy"):
        RunConfig(neural_model="connectome", connectome_parameters={"circuit": "toy-brain", "readout_weights": {"DNy": 1}})


def commands(model, sensors):
    """The undelayed command after each step, with the motor actually sent."""
    rows, sent = [model.command()], []
    for s in sensors:
        model.advance(s, NONE)
        rows.append(model.command())
        sent.append(model.motor())
    return np.array(rows), np.array(sent)


def varying(steps=120, seed=2):
    return [SensorState(left=a, right=b) for a, b in np.random.default_rng(seed).uniform(0, 1, size=(steps, 2))]


def test_delay_shifts_the_descending_command(toy_brain):
    base = ConnectomeParameters(circuit="toy-brain", global_gain=.05, output_gain=3)
    sensors = varying()
    reference, _ = commands(ConnectomeCircuit(base), sensors)
    delayed = ConnectomeCircuit(base.model_copy(update={"motor_delay_ms": 20}))
    own, sent = commands(delayed, sensors)
    assert np.array_equal(own, reference)  # the delay is downstream of the circuit
    # Step k sends the command of step k − 20; before that, the command at the start of the run.
    expected = np.clip(reference[np.maximum(np.arange(1, len(sensors) + 1) - 20, 0)], 0, 1) * MOTOR_SCALE
    assert np.array_equal(sent, expected)
    assert "delayed by 20 ms" in delayed.description()["output_mapping"]


def test_low_pass_follows_its_equation(toy_brain):
    tau, delay = 30, 5
    base = ConnectomeParameters(circuit="toy-brain", global_gain=.05, output_gain=3)
    sensors = varying()
    reference, _ = commands(ConnectomeCircuit(base), sensors)
    model = ConnectomeCircuit(base.model_copy(update={"motor_delay_ms": delay, "motor_tau_ms": tau}))
    _, sent = commands(model, sensors)
    alpha, filtered, expected = 1 - math.exp(-1 / tau), reference[0], []
    for k in range(1, len(sensors) + 1):
        filtered = filtered + alpha * (reference[max(k - delay, 0)] - filtered)
        expected.append(np.clip(filtered, 0, 1) * MOTOR_SCALE)
    assert np.allclose(sent, expected, rtol=0, atol=1e-12)
    text = model.description()["output_mapping"]
    assert "delayed by 5 ms" in text and "low-passed with tau 30 ms" in text
    assert model.description()["labels"]["motor_path"].startswith("engineered")


def test_live_edits_keep_and_resize_the_delay_line(toy_brain):
    base = ConnectomeParameters(circuit="toy-brain", global_gain=.05, output_gain=3, motor_delay_ms=5)
    sensors = varying(80)
    reference, _ = commands(ConnectomeCircuit(base), sensors)
    model = ConnectomeCircuit(base)
    sent = []

    def run(chunk):
        for s in chunk:
            model.advance(s, NONE)
            sent.append(model.motor())
    run(sensors[:40])
    history = model._history
    model.configure(base)  # a live edit (here to the same values) keeps the delay line
    assert model._history is history and len(history) == 6
    model.configure(base.model_copy(update={"motor_delay_ms": 15}))  # longer: hold the oldest command, then go on
    run(sensors[40:60])
    model.configure(base.model_copy(update={"motor_delay_ms": 2}))  # shorter: jump to the newer command
    run(sensors[60:])
    # The command of step k is sent at step source[k − 1].
    source = [max(k - 5, 0) for k in range(1, 41)] + [max(35, k - 15) for k in range(41, 61)] + [k - 2 for k in range(61, 81)]
    assert np.array_equal(np.array(sent), np.clip(reference[source], 0, 1) * MOTOR_SCALE)
    model.configure(base.model_copy(update={"motor_delay_ms": 0}))  # off: the live command again
    assert model._history is None and np.array_equal(model.motor(), np.clip(model.command(), 0, 1) * MOTOR_SCALE)
    model.configure(base)
    model.reset()
    assert len(model._history) == 1 and model._history[0].tolist() == pytest.approx([.35, .35])
    assert model.motor_clipped_fraction == 0


def test_motor_clipped_fraction_counts_control_intervals(toy_brain):
    model = ConnectomeCircuit(ConnectomeParameters(circuit="toy-brain", global_gain=.05, output_gain=20))
    assert model.motor_clipped_fraction == 0 and model.description()["motor_clipped_fraction"] == 0
    clipped = []
    for k in range(40):
        sensors = SensorState(left=1, right=0) if k % 4 else SensorState(left=.5, right=.5)
        for _ in range(10):
            model.advance(sensors, NONE)
        command = model.command()
        clipped.append(bool((command < 0).any() or (command > 1).any()))
        model.motor()
        model.motor()  # an observation without a step (a stimulus edit) is not another interval
        model.motor(baseline=True)
    assert 0 < sum(clipped) < 40
    assert model.motor_clipped_fraction == sum(clipped) / 40 == model.description()["motor_clipped_fraction"]
    assert model.description()["labels"]["motor_clipped_fraction"] == "engineered diagnostic"
    model.reset()
    assert model.motor_clipped_fraction == 0


def test_motor_path_is_live_editable_in_a_run():
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome", seed=4,
                               connectome_parameters={"circuit": "fafb783-steering", "dynamics": "spiking"}), render=False)
    try:
        for _ in range(20):
            exp.advance()
        assert exp.circuit.motor_clipped_fraction == np.mean([0 in s.motor or 1.4 in s.motor for s in exp.records[1:]])
        assert exp.connectome_snapshot()["motor_clipped_fraction"] == exp.circuit.motor_clipped_fraction
        state, step = exp.circuit.spiking, exp.circuit.spiking.step_index
        parameters = exp.config.connectome_parameters
        exp.set_connectome_parameters(parameters.model_copy(update={"motor_delay_ms": 180, "motor_tau_ms": 50,
                                                                    "readout_weights": {"DNp09": .5}}))
        assert exp.circuit.spiking is state and state.step_index == step and exp.circuit._history is not None
        for _ in range(5):
            exp.advance()
        assert state.step_index == step + 500 and np.isfinite(exp.sample.motor).all()  # 100 substeps per interval
        assert exp.events[-1].payload["motor_delay_ms"] == 180
    finally:
        exp.close()
