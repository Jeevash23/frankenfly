"""FlyVis eyes: the FlyWire bridge and the column mapping always; the FlyVis network itself when installed."""
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, SensorState
from digitalfly.neural.connectome import (ConnectomeCircuit, bridge_path, circuit_path, list_circuits, load_bridge,
                                          load_circuit)
from digitalfly.vision.flyvis_eyes import available, column_order

ROOT = Path(__file__).resolve().parents[2]
FLYVIS, REASON = available()
needs_flyvis = pytest.mark.skipif(not FLYVIS, reason=REASON or "FlyVis is not installed")
TYPES = json.loads((ROOT / "data/circuits/fafb783-dna02.flyvis.json").read_text())["flyvis"]["types"]


def test_committed_bridges_match_their_circuits():
    for name in ["fafb783-dna02", "fafb783-steering"]:
        data = load_circuit(name)
        raw = json.loads(bridge_path(data).read_text())
        assert raw["circuit_sha256"] == data.sha256 and raw["non_commercial"] and len(raw["flyvis"]["types"]) == 65
        assert all(data.super_class[i] == "visual_projection" for i in raw["neurons"])
        matrix, types = load_bridge(data)
        weights = np.asarray(matrix.sum(axis=1)).ravel()
        fed = weights > 0
        assert np.allclose(weights[fed], 1, atol=1e-4) and fed.sum() >= .95 * len(raw["neurons"])
        assert raw["flyvis"]["flywire_names"]["CT1(Lo1)"] == "CT1" and "Mi9" in raw["flyvis"]["flywire_names"]
        assert 0 < np.median(raw["coverage"]) < 1
    assert not any(c["name"].endswith(".flyvis") for c in list_circuits())
    with pytest.raises(ValueError):
        circuit_path("fafb783-dna02.flyvis")


def test_visual_drive_reaches_the_input_neurons_of_the_seeing_eye(toy_brain):
    data = load_circuit("toy-brain")
    # LCa left (index 2) hears type 5 from the left eye; LCa right (index 3) the same type from the right eye.
    bridge_path(data).write_text(json.dumps({
        "format": "digitalfly-flyvis-bridge", "version": 1, "circuit": "toy-brain", "circuit_sha256": data.sha256,
        "flyvis": {"release": "1.2.0", "types": TYPES}, "neurons": [2, 3],
        "entries": {"neuron": [0, 1], "type": [5, 5], "eye": [0, 1], "weight": [1.0, 1.0]}}))
    responses = np.zeros((2, 65))
    responses[0, 5] = .8
    model = ConnectomeCircuit(ConnectomeParameters(circuit="toy-brain", global_gain=.05))
    assert model.set_visual(responses) == (pytest.approx(.8), 0)
    for _ in range(300):
        model.advance(SensorState(left=0, right=1), Interventions())  # the sensor values are not used
    assert model.rates[2] > 0 and model.rates[3] == 0 and model.turn() < 0
    model.set_visual(None)
    model.reset()
    for _ in range(300):
        model.advance(SensorState(left=0, right=1), Interventions())
    assert model.rates[3] > 0 and model.rates[2] == 0
    spiking = ConnectomeCircuit(ConnectomeParameters(circuit="toy-brain", dynamics="spiking", input_gain=10))
    spiking.reset(1)
    spiking.set_visual(responses)
    for _ in range(200):
        spiking.advance(SensorState(), Interventions())
    assert spiking.spiking.rate_hz[2] > 0 and spiking.spiking.rate_hz[3] == 0
    with pytest.raises(ValueError):
        model.set_visual(np.zeros((2, 3)))
    bridge_path(data).write_text(bridge_path(data).read_text().replace(data.sha256, "0" * 64))
    with pytest.raises(ValueError, match="rebuild"):
        ConnectomeCircuit(ConnectomeParameters(circuit="toy-brain")).set_visual(responses)


def test_flyvis_settings_are_validated():
    with pytest.raises(ValueError, match="FlyGym"):
        RunConfig(engine="toy", neural_model="connectome", sensor_model="flyvis")
    with pytest.raises(ValueError, match="connectome"):
        RunConfig(sensor_model="flyvis")
    if FLYVIS:
        assert RunConfig(neural_model="connectome", sensor_model="flyvis").sensor_model == "flyvis"
    else:
        with pytest.raises(ValueError, match="FlyVis"):
            RunConfig(neural_model="connectome", sensor_model="flyvis")


def hex_columns(columns=7, rows=6):
    """Centres of a hexagonal lattice in vertical columns, alternate columns offset by half a row: (row, column)."""
    return np.array([(r + (c % 2) / 2, c) for c in range(columns) for r in range(rows)], dtype=float)


def test_column_mapping_recovers_a_shuffled_lattice():
    lattice = hex_columns()
    rng = np.random.default_rng(0)
    shuffle = rng.permutation(len(lattice))
    flygym = lattice[shuffle] * [10, 12] + [100, 5]   # another scale and offset, ommatidia in another order
    flyvis = lattice * [2.5, 3] + [7, -4]
    order = column_order(flygym, flyvis)
    assert np.array_equal(flygym[order], lattice * [10, 12] + [100, 5])
    with pytest.raises(ValueError):
        column_order(flygym[:-1], flyvis)


@needs_flyvis
def test_flyvis_columns_map_one_to_one_and_t4_prefers_the_flys_directions():
    from digitalfly.vision.flyvis_eyes import FlyVisEyes, ommatidia_centroids
    eyes = FlyVisEyes()
    assert sorted(eyes.order["left"]) == sorted(eyes.order["right"]) == list(range(721))
    rows, cols = ommatidia_centroids(eyes.retina.ommatidia_id_map).T

    def sweep(lit_at, cell_types, steps=100):
        eyes.reset()
        means = {t: 0. for t in cell_types}
        for k in range(steps):
            eyes.step(np.full(721, .5), np.where(lit_at((k + 1) / steps), 1., 0.))
            for t in cell_types:
                means[t] += eyes.type_activity("right", t).mean() / steps
        return means
    # The front of the right eye's image is its left side (low columns); rows grow downward.
    front_to_back = sweep(lambda f: cols < 450 * f, ["T4a", "T4b"])
    back_to_front = sweep(lambda f: cols > 450 * (1 - f), ["T4a", "T4b"])
    upward = sweep(lambda f: rows > 512 * (1 - f), ["T4c", "T4d"])
    assert front_to_back["T4a"] > front_to_back["T4b"] and back_to_front["T4b"] > back_to_front["T4a"]
    assert upward["T4c"] > upward["T4d"]


@needs_flyvis
@pytest.mark.flygym
def test_flyvis_eyes_drive_the_circuit_and_replay_exactly(tmp_path):
    from digitalfly import toolkit
    from digitalfly.simulation.experiment import Experiment
    config = toolkit.configure({"engine": "flygym", "neural_model": "connectome", "sensor_model": "flyvis", "seed": 2},
                               stimulus=toolkit.target(45, 12))
    exp = Experiment(config, render=False)
    try:
        assert exp.status == "paused", exp.error
        for _ in range(30):
            exp.advance()
        assert exp.circuit.visual is not None and exp.sample.sensors.left > 0
        assert all(np.isfinite(exp.sample.rates))
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    metadata = json.loads((run / "metadata.json").read_text())
    assert "FlyVis" in metadata["provenance"]["sensor_model"]
    replay = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)], capture_output=True, text=True,
                            timeout=600)
    assert replay.returncode == 0, replay.stderr
    assert json.loads(replay.stdout)["maximum_absolute_error"] == 0
