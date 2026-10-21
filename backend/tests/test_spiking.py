"""Spiking dynamics: Shiu et al. 2024 constants, synaptic delay, refractoriness, Poisson input, seeds."""
import numpy as np
import pytest
from digitalfly.api.models import ConnectomeParameters, Interventions, SensorState
from digitalfly.neural.connectome import LIF, CircuitData, ConnectomeCircuit, SpikingState, transmitter_signs

SPIKING = ConnectomeParameters(dynamics="spiking")


def state_for(path, parameters=SPIKING):
    data = CircuitData(path)
    signs = transmitter_signs(data, parameters.other_transmitters)
    inputs = (np.array([2]), np.array([3]))  # the LCa pair
    state = SpikingState(data, np.ones(len(data.synapses), dtype=bool), signs, parameters, inputs)
    state.substeps = 1  # step 0.1 ms at a time
    return state


def test_constants_follow_shiu_et_al():
    assert LIF == {"v_rest_mv": -52.0, "v_reset_mv": -52.0, "v_threshold_mv": -45.0, "tau_membrane_ms": 20.0,
                   "tau_synapse_ms": 5.0, "refractory_ms": 2.2, "delay_ms": 1.8, "poisson_scale": 250, "dt_ms": 0.1}
    assert SPIKING.spiking.synapse_weight_mv == .275 and SPIKING.spiking.input_rate_hz == 150


def test_a_spike_reaches_its_targets_after_1_8_ms(toy_brain):
    state = state_for(toy_brain)
    none = np.array([], dtype=np.int64)
    state.v[2] = -40.0  # LCa left fires in the first substep
    assert state.advance(0, 0, none) == 1
    for _ in range(17):
        state.advance(0, 0, none)
    assert state.g[0] == 0 and state.v[0] == LIF["v_rest_mv"]
    state.advance(0, 0, none)  # substep 18: delivered after the state update, as in Brian2
    assert state.g[0] == pytest.approx(10 * .275) and state.g[6] == pytest.approx(8 * .275)
    assert state.v[0] == LIF["v_rest_mv"]
    state.advance(0, 0, none)
    assert state.v[0] > LIF["v_rest_mv"]


def test_refractory_period_freezes_a_neuron_for_2_2_ms(toy_brain):
    state = state_for(toy_brain)
    none = np.array([], dtype=np.int64)
    state.v[0] = -40.0
    assert state.advance(0, 0, none) == 1 and state.v[0] == LIF["v_reset_mv"]
    state.g[0] = 100.0
    for _ in range(21):
        state.advance(0, 0, none)
        assert state.v[0] == LIF["v_reset_mv"] and state.g[0] == 100.0
    state.advance(0, 0, none)  # 22 substeps after the spike
    assert state.v[0] == pytest.approx(-52 + .005 * 100) and state.g[0] == pytest.approx(98)
    # Neurons with Poisson input have no refractory period (Shiu et al.).
    assert state.refractory[2] == 0 and state.refractory[0] == 22


def test_poisson_input_rate_follows_the_sensor():
    model = ConnectomeCircuit(SPIKING)
    model.reset(3)
    for _ in range(1000):
        model.advance(SensorState(left=.6, right=0), Interventions())
    rates = model.spiking.rate_hz
    assert rates[model.input_left].mean() == pytest.approx(.6 * 150, rel=.1)
    assert rates[model.input_right].mean() < 10 and np.isfinite(model.spiking.v).all()


def test_spiking_runs_repeat_by_seed_and_silencing_holds(toy_brain):
    def trace(seed, interventions=Interventions(), circuit=None):
        # The toy circuit has one input per neuron, so it needs a strong sensor drive to fire.
        model = ConnectomeCircuit(SPIKING if circuit is None else SPIKING.model_copy(update={"circuit": circuit, "input_gain": 10}))
        model.reset(seed)
        rows = []
        for _ in range(150):
            model.advance(SensorState(left=.8, right=.2), interventions)
            rows.append(model.readout() + [model.turn()])
        return np.array(rows), model
    a, _ = trace(1)
    b, _ = trace(1)
    c, _ = trace(2)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    silenced, model = trace(1, Interventions(silence_dna02="left", silence_types=["DNa03"]))
    assert (silenced[:, 0] == 0).all() and silenced[:, 1].max() > 0
    assert (model.spiking.rate_hz[model.data.members("DNa03")] == 0).all()
    toy, model = trace(4, circuit="toy-brain")
    assert toy[-1, 0] > toy[-1, 1] and model.turn() < 0  # left input → left DNx → left turn
    assert model.activity[0] == pytest.approx(model.spiking.rate_hz[0] / 100)


def test_live_edits_keep_the_spiking_state():
    """A parameter edit mid-run continues the network instead of restarting it (it used to reset v, g, the delay
    queue, rates, the step count and the random generator). A readout-only edit then gives exactly the spike trains
    of a run that had the new value from the start."""
    sensors, none = SensorState(left=.6, right=.4), Interventions()
    edited = ConnectomeCircuit(SPIKING)
    edited.reset(7)
    for _ in range(100):
        edited.advance(sensors, none)
    state = edited.spiking
    before = {key: getattr(state, key).copy() for key in ["v", "g", "blocked", "queue", "rate_hz"]}
    rng = state.rng.bit_generator.state
    gained = SPIKING.model_copy(update={"output_gain": 1.5})
    edited.configure(gained)
    assert edited.spiking is state and state.step_index == 1000 and state.rng.bit_generator.state == rng
    assert all(np.array_equal(getattr(state, key), value) for key, value in before.items())
    assert state.queue.any() and state.rate_hz.any()
    fresh = ConnectomeCircuit(gained)
    fresh.reset(7)
    for _ in range(100):
        fresh.advance(sensors, none)
    for _ in range(100):
        edited.advance(sensors, none)
        fresh.advance(sensors, none)
    for key in ["v", "g", "queue", "rate_hz"]:
        assert np.array_equal(getattr(edited.spiking, key), getattr(fresh.spiking, key)), key
    assert edited.turn() == fresh.turn() != 0
    # Network parameters take effect on the same state; a new input population, or a reset, starts afresh.
    weights = state.weights.copy()
    edited.configure(ConnectomeParameters(dynamics="spiking", input_gain=1.2, motor_delay_ms=50,
                                          spiking={"synapse_weight_mv": .55, "rate_window_ms": 100}))
    assert edited.spiking is state and state.step_index == 2000
    assert np.allclose(state.weights, 2 * weights) and state.kick == 250 * .55 and state.rate_jump == 10
    edited.advance(sensors, none)
    assert state.step_index == 2010
    edited.configure(ConnectomeParameters(dynamics="spiking", input_types=["LC10a"]))
    assert edited.spiking is not state and edited.spiking.step_index == 0
    assert (edited.spiking.v == LIF["v_rest_mv"]).all() and edited.spiking.refractory[edited.input_left].max() == 0
    edited.reset()
    assert edited.spiking.rng.bit_generator.state == np.random.default_rng([7, 0x5B1]).bit_generator.state


def test_a_live_edit_in_a_run_does_not_restart_the_network():
    from digitalfly.api.models import RunConfig
    from digitalfly.simulation.experiment import Experiment
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome", seed=7,
                               connectome_parameters={"dynamics": "spiking"}), render=False)
    try:
        for _ in range(30):
            exp.advance()
        state, readout = exp.circuit.spiking, exp.sample.rates
        exp.set_connectome_parameters(exp.config.connectome_parameters.model_copy(update={"input_gain": 1.01}))
        assert exp.circuit.spiking is state and state.step_index == 3000 and exp.circuit.readout() == readout
        exp.advance()
        assert state.step_index == 3100 and exp.circuit.turn() != 0
    finally:
        exp.close()


def test_the_spiking_step_follows_dt():
    """dt sets the number of 0.1 ms substeps: two 0.5 ms steps are exactly one 1 ms step."""
    sensors, none = SensorState(left=.7, right=.3), Interventions()
    whole, halves = ConnectomeCircuit(SPIKING), ConnectomeCircuit(SPIKING)
    for model in (whole, halves):
        model.reset(2)
    for _ in range(60):
        whole.advance(sensors, none)
        halves.advance(sensors, none, .0005)
        halves.advance(sensors, none, .0005)
    assert whole.spiking.step_index == halves.spiking.step_index == 600
    assert np.array_equal(whole.spiking.v, halves.spiking.v) and np.array_equal(whole.spiking.rate_hz, halves.spiking.rate_hz)
    halves.advance(sensors, none, .0003)
    assert halves.spiking.step_index == 603
    for dt in (.00015, 0, .00005):
        with pytest.raises(ValueError, match="multiples of 0.1 ms"):
            halves.advance(sensors, none, dt)
