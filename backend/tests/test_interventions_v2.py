"""Interventions v2: per-side silencing, output scaling and activation of any cell type, live, in protocols, in
comparisons (custom conditions) and in the ablation scan; and runs without them unchanged."""
import json
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from digitalfly import toolkit
from digitalfly.api.models import (BatchRequest, CellTypeIntervention, ConnectomeParameters, Interventions, Protocol,
                                   ProtocolEvent, RunConfig, SensorState, SpikingParameters)
from digitalfly.main import create_app
from digitalfly.neural import connectome
from digitalfly.neural.connectome import LIF, ConnectomeCircuit
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]
CONNECTOME = RunConfig(engine="toy", neural_model="connectome")
TOY = ConnectomeParameters(circuit="toy-brain", global_gain=.05)
# Toy circuit (conftest): 0/1 DNx L/R (readout), 2/3 LCa L/R (input), 4/5 Inh, 6/7 DNy, 8 Spd (center), 9 Solo (left).


def cell(name, mode, value=0, side="both"):
    return CellTypeIntervention(name=name, side=side, mode=mode, value=value)


def test_cell_type_interventions_are_validated():
    assert Interventions().cell_types == [] and cell("DNa02", "silence").value == 0
    for bad in [{"name": "A", "mode": "scale", "value": 2.5}, {"name": "A", "mode": "activate", "value": 501},
                {"name": "A", "mode": "activate", "value": -1}, {"name": "A", "mode": "boost"},
                {"name": "A", "side": "middle", "mode": "silence"}, {"name": "", "mode": "silence"},
                {"name": "A", "mode": "silence", "extra": 1}]:
        with pytest.raises(ValidationError):
            CellTypeIntervention.model_validate(bad)
    # One manipulation per side of a type: "both" covers left and right; silence_types and DNa02 silencing count.
    for overlapping in [{"cell_types": [cell("A", "silence"), cell("A", "scale", .5)]},
                        {"cell_types": [cell("A", "silence"), cell("A", "scale", .5, "left")]},
                        {"silence_types": ["A"], "cell_types": [cell("A", "activate", .5, "right")]},
                        {"silence_dna02": "left", "cell_types": [cell("DNa02", "scale", .5, "left")]}]:
        with pytest.raises(ValidationError, match="one intervention per side"):
            Interventions(**overlapping)
    assert len(Interventions(cell_types=[cell("A", "silence", side="left"), cell("A", "activate", 9, "right")]).cell_types) == 2
    assert Interventions(silence_dna02="right", cell_types=[cell("DNa02", "activate", .5, "left")]).silence_dna02 == "right"
    assert Interventions(silence_dna02="left", silence_types=["DNa02"]).silence_types == ["DNa02"]  # as before v0.6
    with pytest.raises(ValidationError):
        Interventions(cell_types=[cell(f"T{k}", "silence") for k in range(33)])


def test_run_configurations_check_cell_type_interventions(toy_brain):
    def config(interventions, **settings):
        return RunConfig(neural_model="connectome", connectome_parameters={"circuit": "toy-brain", **settings},
                         initial_interventions=interventions)
    assert config(Interventions(cell_types=[cell("Solo", "activate", .4, "left")])).initial_interventions.cell_types
    assert config(Interventions(cell_types=[cell("Solo", "activate", 400)]), dynamics="spiking")
    for interventions, message in [([cell("Nope", "silence")], "Not a cell type"),
                                   ([cell("Solo", "silence", side="right")], "no right neurons"),
                                   ([cell("Spd", "scale", .5, "left")], "no left neurons"),
                                   ([cell("Solo", "activate", 2)], "from 0 to 1")]:
        with pytest.raises(ValidationError, match=message):
            config(Interventions(cell_types=interventions))
    with pytest.raises(ValidationError, match="need the connectome model"):
        RunConfig(initial_interventions=Interventions(cell_types=[cell("DNa02", "silence")]))
    protocol = Protocol(duration_steps=20, events=[ProtocolEvent(step=5, interventions=Interventions(
        cell_types=[cell("Nope", "scale", .5)]))])
    with pytest.raises(ValidationError, match="Nope"):
        RunConfig(neural_model="connectome", connectome_parameters={"circuit": "toy-brain"}, protocol=protocol)


def test_rate_scaling_multiplies_what_a_type_sends(toy_brain):
    plain, scaled = ConnectomeCircuit(TOY), ConnectomeCircuit(TOY)
    half = Interventions(cell_types=[cell("LCa", "scale", .5, "left")])
    for model, interventions in ((plain, Interventions()), (scaled, half)):
        for _ in range(2):
            model.advance(SensorState(left=1, right=1), interventions)
    # The scaled neuron's own rate is unchanged; its targets and the readout receive half of it.
    assert scaled.rates[2] == plain.rates[2] > 0 and scaled.activity[2] == pytest.approx(.5 * plain.rates[2])
    assert scaled.rates[0] == pytest.approx(.5 * plain.rates[0]) and scaled.rates[0] > 0
    assert scaled.rates[6] == pytest.approx(.5 * plain.rates[6]) and scaled.rates[1] == plain.rates[1]
    assert scaled.readout()[2] == pytest.approx(.5 * plain.readout()[2])  # "Visual input L" is LCa left
    assert scaled.manipulation(half).scaled.tolist() == [2]


def test_rate_activation_clamps_and_drives_targets(toy_brain):
    model = ConnectomeCircuit(TOY)
    on = Interventions(cell_types=[cell("Solo", "activate", .6)])
    model.apply_silencing(on)
    assert model.rates[9] == .6
    model.advance(SensorState(), on)
    assert model.rates[9] == .6 and model.rates[0] == pytest.approx(.05 * 5 * .05 * .6)  # dt/tau × W × r
    model.advance(SensorState(), Interventions())
    assert model.rates[9] < .6  # released: the unit decays toward its input
    with pytest.raises(ValueError, match="from 0 to 1"):
        model.manipulation(Interventions(cell_types=[cell("Solo", "activate", 2)]))
    with pytest.raises(ValueError, match="no right neurons"):
        model.manipulation(Interventions(cell_types=[cell("Solo", "silence", side="right")]))


def test_spiking_activation_is_poisson_input_without_refractoriness(toy_brain):
    model = ConnectomeCircuit(TOY.model_copy(update={"dynamics": "spiking"}))
    model.reset(4)
    # DNx (Solo's only target) silenced, so every spike counted is Solo's.
    on = Interventions(cell_types=[cell("Solo", "activate", 200), cell("DNx", "silence")])
    state, none = model.spiking, np.array([], dtype=np.int64)
    state.manipulate(model.manipulation(on))
    assert state.refractory[9] == 0 and state.refractory[2] == 0 and state.refractory[0] == 22
    spikes = sum(state.advance(0, 0, model.silenced(on)) for _ in range(2000))  # 2 s
    assert 340 <= spikes <= 460  # 200 Hz
    state.manipulate(model.manipulation(Interventions()))
    assert state.refractory[9] == 22 and state.refractory[2] == 0
    assert sum(state.advance(0, 0, none) for _ in range(100)) == 0
    model.advance(SensorState(), on)
    assert model.manipulation(on).activated.tolist() == [9]


def test_spiking_scaling_scales_each_spike_and_survives_live_edits(toy_brain):
    model = ConnectomeCircuit(TOY.model_copy(update={"dynamics": "spiking"}))
    half = Interventions(cell_types=[cell("LCa", "scale", .5, "left")])
    model.advance(SensorState(), half)
    for weight in (.275, .5):
        state, none = model.spiking, np.array([], dtype=np.int64)
        state.reset(0)
        state.v[2] = state.v[3] = -40.0  # both LCa fire in the first substep
        for _ in range(19):  # delivered 1.8 ms later
            state.advance(0, 0, none, substeps=1)
        assert state.g[0] == pytest.approx(.5 * 10 * weight) and state.g[6] == pytest.approx(.5 * 8 * weight)
        assert state.g[1] == pytest.approx(12 * weight)
        model.configure(model.parameters.model_copy(update={"spiking": SpikingParameters(synapse_weight_mv=.5)}))
        assert model.spiking is state  # a live edit keeps the network and its scaling


@pytest.mark.parametrize("dynamics", ["rate", "spiking"])
def test_a_neutral_scale_changes_nothing(toy_brain, dynamics):
    def trace(interventions):
        model = ConnectomeCircuit(TOY.model_copy(update={"dynamics": dynamics}))
        model.reset(3)
        out = []
        for step in range(200):
            model.advance(SensorState(left=.8, right=.3), interventions)
            out.append([model.turn(), *model.readout()])
        return np.array(out)
    assert np.array_equal(trace(Interventions()), trace(Interventions(cell_types=[cell("LCa", "scale", 1)])))


def test_a_live_edit_keeps_the_loaded_circuit_when_the_cache_dropped_it(toy_brain):
    model = ConnectomeCircuit(TOY)
    for _ in range(20):
        model.advance(SensorState(left=1, right=.5), Interventions())
    data, rates = model.data, model.rates.copy()
    connectome._load.cache_clear()  # as when three other circuits were loaded since
    model.configure(model.parameters.model_copy(update={"output_gain": 2}))
    assert model.data is data and rates.any() and np.array_equal(model.rates, rates)


# Final x, y, yaw, Σ|rates| and Σ motor of a 60-step toy run, seed 7, target 30° at 12 mm, without interventions
# ("default") and with DNa02 left silenced at step 20 and LC10a + both DNa02 at step 40 ("legacy"), recorded with the
# code before interventions v2 (v0.6-robustness 1f79576). Bitwise equal there; compared at 1e-10 because other CPUs
# may round some functions differently.
V05 = {
    ('fafb783-dna02', 'rate', 'default'): (2.7613929392703582, 1.8267540577330585, 1.1361714887170993, 111.51098844653575, 59.77999999999999),
    ('fafb783-dna02', 'rate', 'legacy'): (3.4758252793238387, 0.45443213915114566, 0.0342434886779502, 85.84417393705694, 59.78000000000001),
    ('fafb783-dna02', 'spiking', 'default'): (1.2672687928045896, 2.867575081671396, 2.085635524937474, 278.6036008202055, 67.54774999569726),
    ('fafb783-dna02', 'spiking', 'legacy'): (3.8937634243621053, 0.23094226729211947, -0.38663939209405274, 193.3431024659366, 70.88362631925851),
    ('fafb783-steering', 'rate', 'default'): (3.266147409425986, 1.1940683984926066, 0.5096615099658613, 159.24502728455622, 59.78),
    ('fafb783-steering', 'rate', 'legacy'): (3.4500529925767305, 0.6815267016064056, 0.2590995626959231, 143.7851301982423, 59.779999999999994),
    ('fafb783-steering', 'spiking', 'default'): (1.026614797385386, 3.4889850548126202, 2.2566336892044054, 399.23389748801446, 76.17379537143374),
    ('fafb783-steering', 'spiking', 'legacy'): (3.21197114810811, 2.3795153270201164, 0.6202716121776262, 304.4530947021253, 69.5293706606345),
}


@pytest.mark.parametrize("circuit", ["fafb783-dna02", "fafb783-steering"])
@pytest.mark.parametrize("dynamics", ["rate", "spiking"])
def test_runs_without_the_new_interventions_are_unchanged(circuit, dynamics):
    for kind in ("default", "legacy"):
        config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 7}, stimulus=toolkit.target(30, 12),
                                   **{"connectome_parameters.circuit": circuit, "connectome_parameters.dynamics": dynamics})
        exp = Experiment(config, render=False)
        try:
            for step in range(60):
                if kind == "legacy" and step == 20:
                    exp.set_interventions(Interventions(silence_dna02="left"))
                if kind == "legacy" and step == 40:
                    exp.set_interventions(Interventions(silence_types=["LC10a"], silence_dna02="both"))
                exp.advance()
            rows = np.array([[*s.rates, *s.motor] for s in exp.records])
            pose = exp.sample.pose
            actual = (pose.x, pose.y, pose.yaw, float(np.abs(rows[:, :-2]).sum()), float(rows[:, -2:].sum()))
        finally:
            exp.close()
        assert actual == pytest.approx(V05[(circuit, dynamics, kind)], rel=1e-10, abs=1e-12), kind


@pytest.mark.parametrize("dynamics", ["rate", "spiking"])
def test_runs_with_cell_type_interventions_replay_exactly(tmp_path, dynamics):
    active = .8 if dynamics == "rate" else 150
    protocol = Protocol(duration_steps=45, events=[
        ProtocolEvent(step=10, interventions=Interventions(cell_types=[cell("DNa03", "activate", active, "right")])),
        ProtocolEvent(step=20, interventions=Interventions())])
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 5, "protocol": protocol.model_dump()},
                               stimulus=toolkit.target(-40, 12), **{"connectome_parameters.dynamics": dynamics,
                               "initial_interventions": Interventions(cell_types=[cell("LC10a", "scale", .3, "left")])})
    exp = Experiment(config, render=False)
    try:
        for step in range(45):
            if step == 30:
                exp.set_interventions(Interventions(silence_dna02="right", cell_types=[
                    cell("LC10a", "silence", side="left"), cell("PS049", "activate", active)]))
            exp.advance()
        assert [e.payload["source"] for e in exp.events if e.kind == "interventions"] == ["protocol", "protocol", "manual"]
        assert "DNa03 right activated" in [e for e in exp.events if e.kind == "interventions"][0].message
        neural = exp.metadata()["neural"]
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    assert [(i["cell_type"], i["side"], i["mode"], i["field"]) for i in neural["interventions"]] == [
        ("DNa02", "right", "silence", "silence_dna02"), ("LC10a", "left", "silence", "cell_types"),
        ("PS049", "both", "activate", "cell_types")]
    assert neural["interventions"][2]["value"] == active and neural["interventions"][2]["neurons"] == 2
    assert "not calibrated" in neural["labels"]["interventions"]
    done = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run)], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["maximum_absolute_error"] == 0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr('digitalfly.simulation.experiment.ROOT', tmp_path)
    monkeypatch.setattr('digitalfly.main.ROOT', tmp_path)
    app = create_app(CONNECTOME, render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_live_cell_type_interventions(client):
    def post(**body):
        return client.post("/api/interventions", json=body)
    for bad in [[{"name": "Not-a-type", "mode": "silence"}],
                [{"name": "AN_GNG_18", "side": "right", "mode": "silence"}],  # left neurons only
                [{"name": "DNa03", "mode": "activate", "value": 2}],  # rate dynamics: 0–1
                [{"name": "DNa03", "mode": "scale", "value": 3}],
                [{"name": "DNa03", "mode": "silence"}, {"name": "DNa03", "side": "left", "mode": "scale", "value": 1}]]:
        assert post(cell_types=bad).status_code == 422, bad
    state = post(silence_dna02="left", cell_types=[{"name": "LC10a", "side": "left", "mode": "scale", "value": .5},
                                                   {"name": "DNa03", "mode": "activate", "value": .8}]).json()
    assert state["interventions"]["cell_types"][0] == {"name": "LC10a", "side": "left", "mode": "scale", "value": .5}
    assert state["connectome"]["silenced_neurons"] == 1
    assert state["connectome"]["manipulated_neurons"] == {"silence": 1, "scale": 51, "activate": 2}
    assert state["events"][-1]["message"].endswith("silence DNa02 left · LC10a left output ×0.5 · DNa03 activated (rate 0.8)")
    for _ in range(5):
        state = client.post("/api/step", json={}).json()
    assert state["sample"]["rates"][0] == 0
    metadata = json.loads((Path(client.post("/api/export", json={}).json()["path"]) / "metadata.json").read_text())
    assert [i["mode"] for i in metadata["neural"]["interventions"]] == ["silence", "scale", "activate"]
    assert metadata["final_interventions"]["cell_types"][1]["value"] == .8
    # Spiking dynamics take activation in Hz; the engineered model has no cell types (409 live, 422 in a config).
    spiking = {**CONNECTOME.model_dump(), "connectome_parameters": {"dynamics": "spiking"}}
    assert client.post("/api/reset", json=spiking).status_code == 200
    assert post(cell_types=[{"name": "DNa03", "mode": "activate", "value": 250}]).status_code == 200
    engineered = {**CONNECTOME.model_dump(), "neural_model": "engineered"}
    assert client.post("/api/reset", json=engineered).status_code == 200
    assert post(cell_types=[{"name": "DNa03", "mode": "silence"}]).status_code == 409
    bad_reset = {**engineered, "initial_interventions": {"cell_types": [{"name": "DNa03", "mode": "silence"}]}}
    assert client.post("/api/reset", json=bad_reset).status_code == 422


def test_comparisons_take_custom_conditions(client, tmp_path):
    config = RunConfig(engine="toy", neural_model="connectome", protocol=Protocol(duration_steps=10)).model_dump()
    halved = {"label": "DNa02 left ×0.5", "interventions": {"cell_types": [
        {"name": "DNa02", "side": "left", "mode": "scale", "value": .5}]}}
    gain = {"label": "output gain 3", "connectome_parameters": {"output_gain": 3, "spiking": {"rate_window_ms": 30}}}
    body = {"config": config, "seeds": [42], "conditions": ["control"], "custom_conditions": [halved, gain],
            "max_speed": True}

    def status(**changes):
        return client.post("/api/batch/start", json={**body, **changes}).status_code
    assert status(custom_conditions=[halved, {**gain, "label": halved["label"]}]) == 422  # labels must differ
    assert status(custom_conditions=[{**halved, "label": "control"}]) == 422  # so must built-in names
    assert status(custom_conditions=[{**gain, "connectome_parameters": {"dynamics": "spiking"}}]) == 422  # not live
    assert status(custom_conditions=[{**halved, "interventions": {"cell_types": [{"name": "Nope", "mode": "silence"}]}}]) == 422
    assert status(custom_conditions=[{**halved, "interventions": {"cell_types": [
        {"name": "DNa02", "mode": "activate", "value": 5}]}}]) == 422  # rate dynamics: 0–1
    assert status(custom_conditions=[{**gain, "label": "  "}]) == 422
    assert status(conditions=["control", "left_sensor_off", "dna02_left_off", "dna02_both_off"],
                  custom_conditions=[halved, gain, {"label": "third"}]) == 422  # at most six in all
    assert status(conditions=[], custom_conditions=[]) == 422
    assert status(config={**config, "neural_model": "engineered"}, custom_conditions=[gain]) == 422
    assert status() == 200
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = client.get("/api/status").json()
        if state["batch"]["status"] == "completed":
            break
        time.sleep(.05)
    assert state["batch"]["status"] == "completed", state["batch"]
    assert [r["condition"] for r in state["batch"]["results"]] == ["control", "DNa02 left ×0.5", "output gain 3"]
    trials = {m["trial"]["condition"]: m for m in
              (json.loads(p.read_text()) for p in tmp_path.glob("runs/*/metadata.json"))}
    assert trials["DNa02 left ×0.5"]["initial_config"]["initial_interventions"]["cell_types"] == halved["interventions"]["cell_types"]
    assert trials["DNa02 left ×0.5"]["neural"]["interventions"][0]["mode"] == "scale"
    parameters = trials["output gain 3"]["initial_config"]["connectome_parameters"]
    assert parameters["output_gain"] == 3 and parameters["spiking"] == {**SpikingParameters().model_dump(), "rate_window_ms": 30}
    assert trials["output gain 3"]["initial_config"]["initial_interventions"] == Interventions().model_dump()
    assert trials["control"]["initial_config"]["connectome_parameters"]["output_gain"] == 1


def test_custom_conditions_validate_without_the_api(toy_brain):
    config = RunConfig(engine="toy", neural_model="connectome", connectome_parameters={"circuit": "toy-brain"},
                       protocol=Protocol(duration_steps=5))
    request = BatchRequest(config=config, conditions=[], seeds=[1, 2], custom_conditions=[
        {"label": "Solo on", "interventions": {"cell_types": [{"name": "Solo", "mode": "activate", "value": .5}]}}])
    assert request.condition_names == ["Solo on"] and request.custom_config("Solo on", 2).seed == 2
    with pytest.raises(ValidationError, match="Custom condition “Solo right”.*no right neurons"):
        BatchRequest(config=config, custom_conditions=[{"label": "Solo right", "interventions": {
            "cell_types": [{"name": "Solo", "side": "right", "mode": "silence"}]}}])
    with pytest.raises(ValidationError, match="30,000"):
        BatchRequest(config=config.model_copy(update={"protocol": Protocol(duration_steps=6000)}), seeds=[1, 2],
                     conditions=["control"], custom_conditions=[{"label": "a"}, {"label": "b"}])
