"""Shared fixtures: a hand-checkable format-2 circuit installed as a local circuit."""
import json
import numpy as np
import pytest

# index: id, cell type, super class, side, transmitter, hop
NEURONS = [
    ("1", "DNx", "descending", "left", "acetylcholine", 0), ("2", "DNx", "descending", "right", "acetylcholine", 0),
    ("3", "LCa", "visual_projection", "left", "acetylcholine", 1), ("4", "LCa", "visual_projection", "right", "acetylcholine", 1),
    ("5", "Inh", "central", "left", "gaba", 1), ("6", "Inh", "central", "right", "glutamate", 1),
    ("7", "DNy", "descending", "left", "acetylcholine", 1), ("8", "DNy", "descending", "right", "acetylcholine", 1),
    ("9", "Spd", "central", "center", "acetylcholine", 2), ("10", "Solo", "central", "left", "acetylcholine", 2),
]
# pre index → post index: synapses. Into DNx: 10 + 12 from LCa, 6 + 7 from Inh, 5 from Solo (40 in all).
EDGES = [(2, 0, 10), (3, 1, 12), (4, 1, 6), (5, 0, 7), (2, 6, 8), (3, 7, 8), (2, 8, 5), (3, 8, 5), (8, 4, 6), (9, 0, 5)]


def toy_circuit(name="toy-brain"):
    lookups = {key: sorted({n[k] for n in NEURONS}) for k, key in
               [(1, "cell_type"), (2, "super_class"), (3, "side"), (4, "transmitter")]}
    lookups["cell_class"] = [""]
    column = {key: [lookups[key].index(n[k]) for n in NEURONS] for k, key in
              [(1, "cell_type"), (2, "super_class"), (3, "side"), (4, "transmitter")]}
    seeds = [{"seed": "DNx", "cell_types": ["DNx"], "left": ["1"], "right": ["2"], "other": []}]
    header = {"format": "digitalfly-circuit", "version": 2, "name": name,
              "kind": "Synthetic fixture, not biological data",
              "provenance": {"dataset": "synthetic", "release": "test", "specimen": "none", "sex": "unknown",
                             "coverage": "test fixture", "license": "test", "seeds": seeds,
                             "build": {"synapse_threshold": 5, "hops": 2, "neuron_cap": 100, "whole_brain": False,
                                       "seeds": ["DNx"]},
                             "counts": {"neurons": len(NEURONS), "connections": len(EDGES), "cell_types": 6}},
              "defaults": {"readout_types": ["DNx"], "input": "visual_projection"}, "lookups": lookups}
    neurons = {"id": [n[0] for n in NEURONS], **column, "cell_class": [0] * len(NEURONS),
               "hop": [n[5] for n in NEURONS]}
    edges = {key: [e[k] for e in EDGES] for k, key in enumerate(["pre", "post", "synapses"])}
    return header, neurons, edges


def write_circuit(folder, name="toy-brain", fmt="json"):
    header, neurons, edges = toy_circuit(name)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.{fmt}"
    if fmt == "json":
        path.write_text(json.dumps({**header, "neurons": neurons, "edges": edges}))
    else:
        np.savez_compressed(path, header=np.array(json.dumps(header)), neuron_id=np.array(neurons.pop("id"), dtype=np.int64),
                            **{f"neuron_{k}": np.array(v, dtype=np.int32) for k, v in neurons.items()},
                            **{f"edge_{k}": np.array(v, dtype=np.int32) for k, v in edges.items()})
    return path


@pytest.fixture
def toy_brain(tmp_path, monkeypatch):
    """The toy circuit as a local circuit named toy-brain; committed circuits stay visible."""
    monkeypatch.setattr("digitalfly.neural.connectome.LOCAL_DIR", tmp_path / "local")
    return write_circuit(tmp_path / "local")
