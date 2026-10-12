"""The connectome_dna02 rate model: signs, threshold, silencing, direction and determinism."""
import json
import numpy as np
import pytest
from pydantic import ValidationError
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, SensorState
from digitalfly.neural.connectome import CIRCUIT_PATH, ConnectomeCircuit, load_circuit

# Neurons: DNa02 L/R, one cholinergic visual projection neuron per side, then one
# GABAergic, one glutamatergic and one dopaminergic central neuron.
TYPES = ["DNa02", "LC-test", "GABA-test", "Glu-test", "DA-test"]


def tiny_circuit(tmp_path):
    neurons = {
        "id": ["1", "2", "3", "4", "5", "6", "7"],
        "cell_type": [0, 0, 1, 1, 2, 3, 4],
        "super_class": [0, 0, 1, 1, 2, 2, 2],
        "cell_class": [0] * 7, "transmitter_score": [None] * 7, "path_strength": [1.0] * 7,
        "transmitter": [0, 0, 0, 0, 2, 3, 1],
        "side": [0, 1, 0, 1, 0, 1, 1], "hop": [0, 0, 1, 1, 1, 1, 1], "shiu_sign": [0] * 7,
    }
    edges = {"pre": [2, 3, 4, 5, 6, 2], "post": [0, 1, 1, 0, 1, 1], "synapses": [10, 10, 6, 7, 8, 5]}
    data = {"format": "digitalfly-circuit", "version": 1, "name": "synthetic test circuit",
            "kind": "Synthetic fixture, not biological data",
            "provenance": {"dataset": "synthetic", "release": "test", "specimen": "none", "sex": "unknown",
                           "coverage": "test fixture", "license": "test", "dna02": {"left": "1", "right": "2"}},
            "lookups": {"cell_type": TYPES, "super_class": ["descending", "visual_projection", "central"],
                        "cell_class": [""], "transmitter": ["acetylcholine", "dopamine", "gaba", "glutamate"],
                        "side": ["left", "right"]},
            "neurons": neurons, "edges": edges}
    path = tmp_path / "circuit.json"
    path.write_text(json.dumps(data))
    return path


def weights(model):
    return model.W.toarray()


def test_signs_follow_predicted_transmitters(tmp_path):
    gain = .01
    model = ConnectomeCircuit(ConnectomeParameters(global_gain=gain), tiny_circuit(tmp_path))
    W = weights(model)
    assert W[0, 2] == pytest.approx(10 * gain)       # acetylcholine excites
    assert W[1, 4] == pytest.approx(-6 * gain)       # GABA inhibits
    assert W[0, 5] == pytest.approx(-7 * gain)       # glutamate inhibits
    assert W[1, 6] == 0                              # dopamine excluded by default
    assert model.counts["excluded_by_sign_assumption"] == 1
    switched = ConnectomeCircuit(ConnectomeParameters(global_gain=gain, other_transmitters="excitatory"),
                                 tiny_circuit(tmp_path))
    assert weights(switched)[1, 6] == pytest.approx(8 * gain)


def test_threshold_only_removes_weaker_connections(tmp_path):
    model = ConnectomeCircuit(ConnectomeParameters(synapse_threshold=7), tiny_circuit(tmp_path))
    W = weights(model)
    assert W[1, 4] == 0 and W[1, 2] == 0 and W[0, 2] != 0 and W[0, 5] != 0
    assert model.counts["excluded_below_threshold"] == 2
    with pytest.raises(ValidationError):
        ConnectomeParameters(synapse_threshold=4)


def run(model, left, right, interventions=Interventions(), steps=400):
    sensors = SensorState(left=left, right=right)
    for _ in range(steps):
        model.advance(sensors, interventions)
    return model.rates.copy(), model.motor()


def test_left_input_turns_left_and_silencing_clamps(tmp_path):
    params = ConnectomeParameters(global_gain=.05, input_gain=1, output_gain=2)
    model = ConnectomeCircuit(params, tiny_circuit(tmp_path))
    rates, motor = run(model, 1, 0)
    assert rates[0] > rates[1] and model.turn() < 0
    assert motor[1] > motor[0]  # a larger right amplitude turns the body left
    model.reset()
    rates, motor = run(model, 1, 0, Interventions(silence_dna02="left"))
    assert rates[0] == 0 and model.turn() >= 0
    model.reset()
    rates, motor = run(model, 1, 1, Interventions(silence_dna02="both"))
    assert rates[0] == rates[1] == 0
    assert motor.tolist() == pytest.approx([params.tonic_drive * 1.4] * 2)
    model.reset()
    # The API checks names against the committed circuit; this fixture has its own types.
    fixture_types = Interventions.model_construct(**{**Interventions().model_dump(), "silence_types": ["LC-test"]})
    rates, _ = run(model, 1, 1, fixture_types)
    assert rates[2] == rates[3] == 0 and rates[0] == 0
    invented = Interventions.model_construct(**{**Interventions().model_dump(), "silence_types": ["Invented"]})
    with pytest.raises(ValueError, match="not a cell type"):
        model.advance(SensorState(), invented)
    assert model.motor(baseline=True).tolist() == [1, 1]


def test_real_circuit_is_finite_deterministic_and_silenceable():
    data = load_circuit()
    assert data.path == CIRCUIT_PATH and len(data.input_left) and len(data.input_right)
    rng = np.random.default_rng(3)
    sensors = rng.uniform(0, 1, size=(300, 2))
    results = []
    for _ in range(2):
        model = ConnectomeCircuit()
        trace = []
        for left, right in sensors:
            model.advance(SensorState(left=left, right=right), Interventions())
            trace.append(model.motor())
        assert np.isfinite(model.rates).all() and (model.rates >= 0).all() and (model.rates <= 1).all()
        results.append((model.rates.copy(), np.array(trace)))
    assert np.array_equal(results[0][0], results[1][0]) and np.array_equal(results[0][1], results[1][1])
    model = ConnectomeCircuit()
    for left, right in sensors[:100]:
        model.advance(SensorState(left=left, right=right), Interventions(silence_dna02="right"))
    assert model.rates[data.right] == 0
    readout = model.readout()
    assert len(readout) == len(model.unit_names) == 5 and readout[1] == 0


def test_run_config_validates_model_and_interventions():
    assert RunConfig().neural_model == "engineered"
    with pytest.raises(ValidationError):
        RunConfig(neural_model="whole_brain")
    with pytest.raises(ValidationError, match="connectome"):
        RunConfig(initial_interventions=Interventions(silence_dna02="left"))
    with pytest.raises(ValidationError, match="engineered"):
        RunConfig(neural_model="connectome_dna02", initial_interventions=Interventions(silence="descending"))
    with pytest.raises(ValidationError):
        Interventions(silence_types=["DNa02", "DNa02"])
    with pytest.raises(ValidationError):
        RunConfig(neural_model="connectome_dna02", initial_interventions=Interventions(silence_types=["Not-a-type"]))
    config = RunConfig(neural_model="connectome_dna02", initial_interventions=Interventions(silence_types=["DNa02"]))
    assert config.initial_interventions.silence_types == ["DNa02"]
    for bad in [{"global_gain": -1}, {"tau_ms": 1}, {"output_gain": float("nan")}, {"other_transmitters": "inhibitory"}]:
        with pytest.raises(ValidationError):
            ConnectomeParameters(**bad)
