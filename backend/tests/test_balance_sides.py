"""The builder's --balance-sides option: the cap applied per cell type and side."""
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_circuit_balance", ROOT / "scripts/build_circuit.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PREPARED = ROOT / ".cache/circuits/fafb783-connectome.npz"
BALANCED = {"fafb783-dna02-balanced": (["DNa02"], 3000), "fafb783-steering-balanced": (["DNa01", "DNa02", "DNp09"], 4000)}

# Seeds DNx (101 left, 102 right). Direct partners: LCa on both sides; Asym twice on the left, once on the right.
# Path strengths at hop 2 (input fraction × the partner's): VP 301 .16, 302 .12, 303 .08 (all left) and 311 .208
# (right); Asym 214 .125 (right); Mid 401 .04 (center); One 501 .1 (left only, no right neuron at all).
BRAIN = {
    101: ("DNx", "descending", "left"), 102: ("DNx", "descending", "right"),
    201: ("LCa", "visual_projection", "left"), 202: ("LCa", "visual_projection", "right"),
    211: ("Asym", "central", "left"), 212: ("Asym", "central", "left"), 213: ("Asym", "central", "right"),
    214: ("Asym", "central", "right"),
    301: ("VP", "visual_projection", "left"), 302: ("VP", "visual_projection", "left"),
    303: ("VP", "visual_projection", "left"), 311: ("VP", "visual_projection", "right"),
    401: ("Mid", "central", "center"), 501: ("One", "central", "left"),
}
EDGES = [(201, 101, 10), (211, 101, 10), (202, 102, 10), (212, 102, 10), (213, 102, 10),
         (301, 201, 40), (302, 201, 30), (303, 201, 20), (401, 201, 10), (501, 201, 25), (311, 202, 10), (214, 202, 6)]
HOP1 = ["201", "202", "211", "212", "213"]


@pytest.fixture
def brain(tmp_path, monkeypatch):
    for name, path in {"PREPARED": "cache/prepared.npz", "CATALOG": "cache/catalog.json",
                       "OUT_DIR": "circuits", "LOCAL_DIR": "circuits/local"}.items():
        monkeypatch.setattr(builder, name, tmp_path / path)
    ids = sorted(BRAIN)
    meta = {"id": np.array(ids, dtype=np.int64),
            "cell_type": np.array([BRAIN[i][0] for i in ids], dtype=object),
            "super_class": np.array([BRAIN[i][1] for i in ids], dtype=object),
            "cell_class": np.array([""] * len(ids), dtype=object), "cell_sub_class": np.array([""] * len(ids), dtype=object),
            "side": np.array([BRAIN[i][2] for i in ids], dtype=object),
            "neurotransmitter_predicted": np.array(["acetylcholine"] * len(ids), dtype=object),
            "neurotransmitter_score": np.full(len(ids), .9)}
    pre, post, count = (np.array(c) for c in zip(*EDGES))
    columns = {"Presynaptic_ID": pre, "Postsynaptic_ID": post, "Connectivity": count, "Excitatory": np.ones(len(pre), int)}
    builder.save_prepared(meta, columns, [{"name": "synthetic", "sha256": "0" * 64}])
    return tmp_path


def build(name, cap, balance=True, whole=False):
    builder.build_custom(name, ["DNx"], 2, 5, cap, whole, "json", False, balance)
    path = builder.LOCAL_DIR / f"{name}.json"
    return json.loads(path.read_text()), path


def test_balanced_cap_keeps_each_cell_type_in_left_right_pairs(brain):
    from digitalfly.neural.connectome import CircuitData
    plain, _ = build("plain", 11, balance=False)
    # Without balancing the cap keeps the four strongest: VP ends up 2 left / 1 right.
    assert plain["neurons"]["id"] == ["101", "102", *HOP1, "214", "301", "302", "311"]
    assert "balance_sides" not in plain["provenance"]["build"] and "side_balance" not in plain["provenance"]
    header, path = build("even", 11)
    # VP keeps the pair 301 + 311 (ranked by its weaker member, .16); 302 and 303 have no right partner, and One
    # has no right neuron at all, so they go. 214 evens out Asym's direct partners (2 left, 1 right). The midline
    # neuron is ranked alone and fills the last place.
    assert header["neurons"]["id"] == ["101", "102", *HOP1, "214", "301", "311", "401"]
    prov = header["provenance"]
    assert prov["build"]["balance_sides"] is True and "per cell type and side" in prov["coverage"]
    balance = prov["side_balance"]
    assert balance["applied"] and balance["unpaired_dropped"] == 3 and balance["rule"] == builder.BALANCE_RULE
    assert (balance["cell_types_with_sides"], balance["even_cell_types"], balance["uneven_neurons"]) == (4, 4, 0)
    assert balance["uneven_cell_types"] == {}
    cap = prov["cap_report"]
    assert cap["dropped"] == 3 and cap["dropped_top_cell_types"] == {"VP": 2, "One": 1}
    assert cap["weakest_kept_path_strength"] == pytest.approx(.04)  # the midline neuron
    assert cap["strongest_dropped_path_strength"] == pytest.approx(.12)  # an unpaired VP, stronger than kept ones
    assert prov["counts"]["visual_projection_inputs"] == {"left": 2, "right": 2}
    data = CircuitData(path)
    assert data.hop.tolist() == [0, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2]


def test_units_are_kept_until_the_next_one_would_exceed_the_cap(brain):
    assert build("nine", 9)[0]["neurons"]["id"] == ["101", "102", *HOP1, "301", "311"]  # 214 would be the tenth
    eight, _ = build("eight", 8)  # one place left, and the strongest unit is a pair
    assert eight["neurons"]["id"] == ["101", "102", *HOP1]
    assert eight["provenance"]["counts"]["by_hop"] == [2, 5, 0] and eight["provenance"]["cap_report"]["kept"] == 7


def test_balance_changes_nothing_when_the_cap_does_not_bind(brain):
    plain, _ = build("loose-plain", 100, balance=False)
    loose, _ = build("loose", 100)
    assert loose["neurons"] == plain["neurons"] and loose["edges"] == plain["edges"]
    balance = loose["provenance"]["side_balance"]
    assert not balance["applied"] and balance["unpaired_dropped"] == 0
    # The data's own imbalance is reported, not hidden: VP 3 left / 1 right, One only on the left.
    assert balance["uneven_cell_types"] == {"VP": {"left": 3, "right": 1}, "One": {"left": 1, "right": 0}}
    assert balance["uneven_neurons"] == 3


def test_balance_refuses_whole_brain_builds(brain):
    with pytest.raises(SystemExit, match="whole-brain"):
        build("whole", 100, whole=True)


def test_balanced_trim_evens_out_earlier_hops_first():
    # Type 0: two right neurons kept at earlier hops (5, 6); candidates 0-2 left, 3-4 right, strongest first.
    group, side = np.zeros(7, dtype=np.int64), np.array([0, 0, 0, 1, 1, 1, 1])
    strength = np.array([.9, .8, .7, .6, .5, 1, 1])
    layer, earlier = np.arange(5), np.array([5, 6])
    kept, dropped, unpaired = builder.balanced_trim(layer, strength, earlier, group, side, 10)
    assert kept.tolist() == [0, 1, 2, 3] and dropped.tolist() == [4] and unpaired == 1  # 3 left, 3 right in all
    kept, dropped, _ = builder.balanced_trim(layer, strength, earlier, group, side, 3)
    assert kept.tolist() == [0, 1] and dropped.tolist() == [2, 3, 4]


def test_balance_sides_reaches_the_builder_from_the_command_line_and_the_app():
    from digitalfly.data.builds import BuildManager, BuildRequest
    assert builder.arguments(["build", "--name", "x", "--seed", "DNa02", "--balance-sides"]).balance_sides
    assert not builder.arguments(["build", "--name", "x", "--seed", "DNa02"]).balance_sides
    assert BuildManager.command(BuildRequest(name="x", seeds=["DNa02"], balance_sides=True))[-1] == "--balance-sides"
    assert "--balance-sides" not in BuildManager.command(BuildRequest(name="x", seeds=["DNa02"]))
    assert BuildRequest(name="x", seeds=["DNa02"]).balance_sides is False


@pytest.mark.parametrize("name", BALANCED)
def test_committed_balanced_circuits_record_how_they_were_built(name):
    seeds, cap = BALANCED[name]
    data = json.loads((ROOT / f"data/circuits/{name}.json").read_text())
    prov = data["provenance"]
    assert prov["build"]["seeds"] == seeds and prov["build"]["neuron_cap"] == cap and prov["build"]["balance_sides"] is True
    assert prov["side_balance"]["applied"] and prov["non_commercial"] and "CC BY-NC 4.0" in prov["license"]
    assert prov["sources"] == json.loads((ROOT / "data/circuits/downloads.json").read_text())
    assert data["defaults"]["readout_types"] == seeds and len(data["neurons"]["id"]) <= cap
    bridge = json.loads((ROOT / f"data/circuits/{name}.flyvis.json").read_text())
    assert bridge["circuit"] == name and bridge["non_commercial"]


def test_the_circuit_list_says_which_circuits_are_balanced():
    from digitalfly.neural.connectome import list_circuits
    listed = {c["name"]: c["build"]["balance_sides"] for c in list_circuits() if c.get("committed")}
    assert listed["fafb783-dna02"] is False and listed["fafb783-steering"] is False
    assert all(listed[name] is True for name in BALANCED)


@pytest.mark.skipif(not PREPARED.is_file(), reason="needs the prepared FlyWire archive (scripts/build_circuit.py prepare)")
@pytest.mark.parametrize("name", BALANCED)
def test_committed_balanced_circuits_rebuild_byte_for_byte(name, tmp_path, monkeypatch):
    seeds, cap = BALANCED[name]
    monkeypatch.setattr(builder, "OUT_DIR", tmp_path)
    builder.build_custom(name, seeds, 2, 5, cap, False, "auto", True, True)
    assert (tmp_path / f"{name}.json").read_bytes() == (ROOT / f"data/circuits/{name}.json").read_bytes()
