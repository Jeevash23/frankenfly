"""Circuit files and the circuit registry, configurable populations, summaries and path tracing."""
import numpy as np
import pytest
from conftest import write_circuit
from digitalfly.api.models import ConnectomeParameters, Interventions, RunConfig, SensorState
from digitalfly.neural import connectome
from digitalfly.neural.connectome import (CircuitData, ConnectomeCircuit, circuit_path, circuit_summary, list_circuits,
                                          load_circuit, trace_paths)


def test_json_npz_and_v03_files_load_the_same_way(tmp_path):
    a = CircuitData(write_circuit(tmp_path, "same", "json"))
    b = CircuitData(write_circuit(tmp_path / "npz", "same", "npz"))
    assert a.ids == b.ids == [str(i) for i in range(1, 11)] and a.seeds == b.seeds and a.defaults == b.defaults
    for field in ["type_index", "super_class", "side", "transmitter", "hop", "pre", "post", "synapses"]:
        assert np.array_equal(getattr(a, field), getattr(b, field)), field
    assert a.members("DNx", "left").tolist() == [0] and a.members("Spd").tolist() == [8]
    with pytest.raises(ValueError, match="not a cell type"):
        a.members("Nope")
    v03 = load_circuit()
    assert v03.version == 1 and v03.defaults["readout_types"] == ["DNa02"] and v03.seeds[0]["seed"] == "DNa02"
    assert v03.summary()["committed"] and v03.summary()["neurons"] == 3000


def test_registry_finds_committed_then_local_circuits_safely(tmp_path, monkeypatch):
    committed, local = tmp_path / "committed", tmp_path / "local"
    monkeypatch.setattr(connectome, "CIRCUIT_DIR", committed)
    monkeypatch.setattr(connectome, "LOCAL_DIR", local)
    write_circuit(committed, "alpha")
    write_circuit(local, "alpha")  # shadowed: committed circuits win
    write_circuit(local, "beta", "npz")
    (local / "gamma.json").symlink_to(committed / "alpha.json")
    (local / "broken.json").write_text("{not json")
    (local / "Upper.json").write_text("{}")
    (committed / "downloads.json").write_text("[]")
    assert circuit_path("alpha") == committed / "alpha.json" and circuit_path("beta") == local / "beta.npz"
    for bad in ["../alpha", "local", "Alpha", "a/b", ""]:
        with pytest.raises(ValueError):
            circuit_path(bad)
    for missing in ["gamma", "missing"]:
        with pytest.raises(FileNotFoundError):
            circuit_path(missing)
    listed = {c["name"]: c for c in list_circuits()}
    assert list(listed) == ["alpha", "beta", "broken"]
    assert listed["alpha"]["committed"] and not listed["beta"]["committed"] and listed["beta"]["format"] == "npz"
    assert listed["beta"]["neurons"] == 10 and listed["beta"]["readout_types"] == ["DNx"] and "error" in listed["broken"]


def run(model, left, right, steps=300, interventions=Interventions()):
    for _ in range(steps):
        model.advance(SensorState(left=left, right=right), interventions)


def test_readout_input_and_speed_populations(toy_brain):
    parameters = ConnectomeParameters(circuit="toy-brain", global_gain=.05, readout_types=["DNx", "DNy"],
                                      input_types=["LCa"], speed_types=["Spd"], speed_gain=2)
    model = ConnectomeCircuit(parameters)
    assert model.unit_names == ["DNx L", "DNx R", "DNy L", "DNy R", "Input L", "Input R", "Circuit mean", "Speed drive"]
    run(model, 1, 0)
    r = model.rates
    assert model.turn() == pytest.approx((r[1] - r[0]) + (r[7] - r[6])) and model.turn() < 0
    assert model.forward() == pytest.approx(parameters.tonic_drive + 2 * r[8]) and r[8] > 0
    assert len(model.readout()) == 8 and model.readout()[-1] == pytest.approx(r[8])
    default = ConnectomeCircuit(ConnectomeParameters(circuit="toy-brain"))
    assert default.unit_names[:2] == ["DNx L", "DNx R"] and default.input_left.tolist() == [2]
    for bad, message in [({"readout_types": ["Solo"]}, "both sides"), ({"input_types": ["Solo"]}, "both sides"),
                         ({"speed_types": ["Nope"]}, "not a cell type")]:
        settings = ConnectomeParameters(circuit="toy-brain", **bad)
        with pytest.raises(ValueError, match=message):
            settings.check_against_circuit()
    with pytest.raises(ValueError, match="no DNa02"):
        default.advance(SensorState(), Interventions(silence_dna02="left"))
    with pytest.raises(ValueError):
        RunConfig(neural_model="connectome", connectome_parameters={"circuit": "no-such-circuit"})
    config = RunConfig(neural_model="connectome", connectome_parameters={"circuit": "toy-brain"},
                       initial_interventions=Interventions(silence_types=["Inh"]))
    assert config.connectome_parameters.circuit == "toy-brain"


def test_summary_marks_readouts_inputs_and_types(toy_brain):
    summary = circuit_summary(ConnectomeParameters(circuit="toy-brain", input_types=["LCa"]))
    names = {t["index"]: t for t in summary["types"]}
    readout = summary["readouts"][0]
    assert summary["name"] == "toy-brain" and readout["cell_type"] == "DNx" and names[readout["type_index"]]["name"] == "DNx"
    assert readout["left"] == ["1"] and readout["right"] == ["2"]
    into_left = dict(zip(readout["inputs"]["left"]["pre"], readout["inputs"]["left"]["synapses"]))
    by_name = {t["name"]: t["index"] for t in summary["types"]}
    assert into_left == {by_name["LCa"]: 10, by_name["Inh"]: 7, by_name["Solo"]: 5}
    assert [t["name"] for t in summary["types"] if t["input"]] == ["LCa"]
    assert names[by_name["Inh"]]["sign"] == -1 and names[by_name["Spd"]]["layer"] == 2


def test_trace_paths_ranks_by_input_fraction_and_signs(toy_brain):
    parameters = ConnectomeParameters(circuit="toy-brain")
    result = trace_paths(parameters, "LCa", "DNx")
    paths = [(p["cell_types"], round(p["strength"], 6), p["net_sign"]) for p in result["paths"]]
    # LCa → DNx carries 22 of DNx's 40 input synapses; LCa → Spd → Inh → DNx is 1 × 1 × 13/40 and inhibitory.
    assert paths == [(["LCa", "DNx"], .55, 1), (["LCa", "Spd", "Inh", "DNx"], .325, -1)]
    assert trace_paths(parameters, "LCa", "DNx", max_hops=2)["paths"] == result["paths"][:1]
    with pytest.raises(ValueError):
        trace_paths(parameters, "LCa", "Nope")


def test_dna02_interventions_need_a_circuit_with_dna02(toy_brain):
    from digitalfly.api.models import BatchRequest, Protocol, ProtocolEvent
    toy = {"circuit": "toy-brain"}
    with pytest.raises(ValueError, match="DNa02"):
        RunConfig(neural_model="connectome", connectome_parameters=toy, initial_interventions=Interventions(silence_dna02="left"))
    event = ProtocolEvent(step=1, interventions=Interventions(silence_types=["Nope"]))
    with pytest.raises(ValueError, match="Nope"):
        RunConfig(neural_model="connectome", connectome_parameters=toy, protocol=Protocol(duration_steps=5, events=[event]))
    config = RunConfig(engine="toy", neural_model="connectome", connectome_parameters=toy, protocol=Protocol(duration_steps=5))
    with pytest.raises(ValueError, match="DNa02"):
        BatchRequest(config=config, conditions=["control", "dna02_left_off"])
    assert BatchRequest(config=config, conditions=["control", "cell_type_off"], cell_type="Inh").cell_type == "Inh"
