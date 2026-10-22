"""A circuit file may list a cell type that has no neurons: its mean activity is 0, not NaN, so the live state
(which JSON carries) and the recorded type activity stay valid."""
import json
import numpy as np
from conftest import toy_circuit
from digitalfly.api.models import RunConfig
from digitalfly.simulation.experiment import Experiment


def test_a_cell_type_without_neurons_has_mean_activity_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.neural.connectome.LOCAL_DIR", tmp_path)
    header, neurons, edges = toy_circuit("ghost-type")
    header["lookups"]["cell_type"].append("Ghost")  # listed, with no neuron of that type
    (tmp_path / "ghost-type.json").write_text(json.dumps({**header, "neurons": neurons, "edges": edges}))
    exp = Experiment(RunConfig(engine="toy", neural_model="connectome", record_activity="types",
                               connectome_parameters={"circuit": "ghost-type", "global_gain": .05}), render=False)
    try:
        for _ in range(5):
            exp.advance()
        means = exp.circuit.type_means()
        assert exp.circuit.data.type_names[-1] == "Ghost" and means[-1] == 0
        assert np.isfinite(means).all() and means[:-1].any()
        json.dumps(exp.connectome_snapshot(), allow_nan=False)  # the live connectome block
        assert all(np.isfinite(row).all() for row in exp.activity)
    finally:
        exp.close()
