"""The circuit builder's selection rules, and the provenance of the committed circuit."""
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_circuit", ROOT / "scripts/build_circuit.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
CIRCUIT = ROOT / "data/circuits/fafb783-dna02.json"
STEERING = ROOT / "data/circuits/fafb783-steering.json"

# A hand-checkable graph. Seeds 1 and 2 stand in for the two DNa02 neurons.
EDGES = [
    (10, 1, 8), (12, 1, 3),            # 12 → 1 is below the 5-synapse threshold
    (11, 2, 6),
    (20, 10, 9), (21, 10, 5),          # hop 2 through 10
    (22, 11, 7),                       # hop 2 through 11
    (23, 12, 9),                       # 12 is not a partner, so 23 is not either
    (24, 20, 9),                       # three hops back
    (10, 11, 5), (20, 21, 2),          # lateral connections, the second below threshold
]


def select(threshold=5, hops=2, cap=100):
    pre, post, count = (np.array(column) for column in zip(*EDGES))
    return builder.select_subcircuit(pre, post, count, [1, 2], threshold, hops, cap)


def test_threshold_and_hops_define_the_partners():
    chosen = select()
    assert chosen["kept"].tolist() == [1, 2, 10, 11, 20, 21, 22]
    assert chosen["by_hop"] == [2, 2, 3] and chosen["hop"].tolist() == [0, 0, 1, 1, 2, 2, 2]
    assert 12 not in chosen["kept"] and 23 not in chosen["kept"] and 24 not in chosen["kept"]
    assert 24 in select(hops=3)["kept"]
    assert select(threshold=3)["kept"].tolist()[:5] == [1, 2, 10, 11, 12]


def test_induced_subgraph_keeps_every_strong_connection_between_kept_neurons():
    chosen = select()
    kept = chosen["kept"].tolist()
    pre, post, synapses = chosen["edges"]
    pairs = {(kept[a], kept[b]): s for a, b, s in zip(pre, post, synapses)}
    assert pairs == {(10, 1): 8, (11, 2): 6, (20, 10): 9, (21, 10): 5, (22, 11): 7, (10, 11): 5}
    assert list(zip(post.tolist(), pre.tolist())) == sorted(zip(post.tolist(), pre.tolist()))


def test_cap_keeps_the_strongest_paths_and_records_the_rest():
    # Path strength multiplies input fractions: 22 → 11 → 2 is 7/12 × 6/6 (11 also hears 10),
    # 20 → 10 → 1 is 9/14 × 8/11 and 21 → 10 → 1 is 5/14 × 8/11.
    chosen = select(cap=5)
    assert chosen["kept"].tolist() == [1, 2, 10, 11, 22]
    assert chosen["dropped"].tolist() == [20, 21] and chosen["candidates"] == 7
    assert chosen["dropped_strength"][0] == pytest.approx(9 / 14 * 8 / 11)
    assert chosen["weakest_kept_strength"] == pytest.approx(7 / 12)
    # Direct partners are never dropped, even when they alone exceed the cap.
    assert select(cap=3)["kept"].tolist() == [1, 2, 10, 11]


def test_weakest_kept_strength_comes_from_the_deepest_hop_that_kept_neurons():
    # With a third hop the cap still binds at hop 2 and hop 3 keeps nothing (24 is dropped too).
    deeper = select(hops=3, cap=5)
    assert deeper["by_hop"] == [2, 2, 1, 0] and deeper["dropped"].tolist() == [20, 21, 24]
    assert deeper["weakest_kept_strength"] == pytest.approx(7 / 12)
    # When the direct partners alone fill the cap, hop 1 holds the weakest kept path (10 → 1: 8 of 11 synapses).
    assert select(cap=3)["weakest_kept_strength"] == pytest.approx(8 / 11)
    assert select()["weakest_kept_strength"] is None  # nothing dropped


def test_transmitter_labels_are_normalised_without_guessing():
    assert builder.transmitter("ACH") == "acetylcholine" and builder.transmitter("gaba") == "gaba"
    assert builder.transmitter("Glutamate") == "glutamate" and builder.transmitter("") == "unknown"
    assert builder.transmitter("histamine") == "unknown"


def test_committed_circuit_records_complete_provenance():
    raw = CIRCUIT.read_bytes()
    assert len(raw) < 5_000_000
    data = json.loads(raw)
    prov = data["provenance"]
    assert data["format"] == "digitalfly-circuit" and prov["release"] == "v783" and prov["sex"] == "female"
    assert "CC BY-NC 4.0" in prov["license"] and prov["non_commercial"] is True
    assert prov["build"]["synapse_threshold"] == 5 and prov["build"]["hops"] == 2
    assert prov["counts"]["neurons"] <= prov["build"]["neuron_cap"]
    assert {prov["dna02"]["left"], prov["dna02"]["right"]} == {"720575940604737708", "720575940629327659"}
    downloads = json.loads((ROOT / "data/circuits/downloads.json").read_text())
    assert downloads == prov["sources"]
    for source in prov["sources"]:
        assert source["url"].startswith("https://") and len(source["sha256"]) == 64
        assert source["bytes"] > 0 and source["license"] and source["release"] and source["retrieved_utc"]
    neurons, edges = data["neurons"], data["edges"]
    n = len(neurons["id"])
    assert n == prov["counts"]["neurons"] == len(set(neurons["id"]))
    assert len(edges["pre"]) == prov["counts"]["connections"]
    assert sum(edges["synapses"]) == prov["counts"]["synapses"]
    assert min(edges["synapses"]) >= prov["build"]["synapse_threshold"]
    assert max(max(edges["pre"]), max(edges["post"])) < n
    assert neurons["hop"][:2] == [0, 0] and max(neurons["hop"]) <= 2
    assert all(isinstance(i, str) for i in neurons["id"])
    assert hashlib.sha256(raw).hexdigest()  # recorded in every export by the model


# A twelve-neuron "brain" for the general builder, run through the builder's own prepare step.
# DNx is the seed pair; LCa feeds it, Inh inhibits it, an untyped neuron feeds LCa, DAx feeds that.
# Weak → DNx is below threshold, Lonely has no connections, the Pair is strong but unreachable,
# and neuron 999 has connections but no metadata.
BRAIN = {
    101: ("DNx", "descending", "left", "acetylcholine"), 102: ("DNx", "descending", "right", "acetylcholine"),
    201: ("LCa", "visual_projection", "left", "acetylcholine"), 202: ("LCa", "visual_projection", "right", "acetylcholine"),
    301: ("Inh", "central", "left", "gaba"), 302: ("Inh", "central", "right", "glutamate"),
    401: ("", "central", "", "acetylcholine"), 501: ("DAx", "central", "center", "dopamine"),
    601: ("Lonely", "central", "left", "acetylcholine"), 701: ("Weak", "central", "left", "acetylcholine"),
    801: ("Pair", "central", "left", "acetylcholine"), 802: ("Pair", "central", "right", "acetylcholine"),
}
BRAIN_EDGES = [(201, 101, 10, 1), (202, 102, 12, 1), (301, 102, 6, -1), (302, 101, 7, -1), (401, 201, 8, 1),
               (401, 202, 9, 1), (501, 401, 20, 1), (701, 101, 2, 1), (999, 101, 30, 1), (101, 301, 5, 1),
               (801, 802, 15, 1)]


@pytest.fixture
def brain(tmp_path, monkeypatch):
    for name, path in {"PREPARED": "cache/prepared.npz", "CATALOG": "cache/catalog.json",
                       "OUT_DIR": "circuits", "LOCAL_DIR": "circuits/local"}.items():
        monkeypatch.setattr(builder, name, tmp_path / path)
    ids = sorted(BRAIN, reverse=True)  # the prepare step must sort by ID itself
    meta = {"id": np.array(ids, dtype=np.int64),
            "cell_type": np.array([BRAIN[i][0] for i in ids], dtype=object),
            "super_class": np.array([BRAIN[i][1] for i in ids], dtype=object),
            "cell_class": np.array(["deep" if i == 401 else "" for i in ids], dtype=object),
            "cell_sub_class": np.array([""] * len(ids), dtype=object),
            "side": np.array([BRAIN[i][2] for i in ids], dtype=object),
            "neurotransmitter_predicted": np.array([BRAIN[i][3] for i in ids], dtype=object),
            "neurotransmitter_score": np.linspace(.5, .9, len(ids))}
    pre, post, count, sign = (np.array(c) for c in zip(*BRAIN_EDGES))
    columns = {"Presynaptic_ID": pre, "Postsynaptic_ID": post, "Connectivity": count, "Excitatory": sign}
    builder.save_prepared(meta, columns, [{"name": "synthetic", "sha256": "0" * 64}])
    return tmp_path


def build(name, seeds, fmt="auto", hops=2, threshold=5, cap=100, whole=False, committed=False):
    builder.build_custom(name, seeds, hops, threshold, cap, whole, fmt, committed)
    folder = builder.OUT_DIR if committed else builder.LOCAL_DIR
    return next(path for suffix in (".json", ".npz") if (path := folder / f"{name}{suffix}").is_file())


def test_prepare_sorts_neurons_and_writes_a_catalog(brain):
    data = builder.load_prepared()
    assert data["neuron_id"].tolist() == sorted(BRAIN)
    assert data["header"]["connections"] == 10 and data["header"]["unmatched_connections"] == 1
    catalog = {c["cell_type"]: c for c in json.loads(builder.CATALOG.read_text())["cell_types"]}
    assert catalog["DNx"] == {"cell_type": "DNx", "neurons": 2, "left": 1, "right": 1, "super_class": "descending"}
    assert "deep (untyped)" in catalog and catalog["DAx"]["left"] == catalog["DAx"]["right"] == 0


def test_build_writes_format_2_with_provenance_and_default_readout(brain):
    from digitalfly.neural.connectome import CircuitData
    path = build("test-dnx", ["DNx"])
    assert path.suffix == ".json" and path.parent == builder.LOCAL_DIR
    header = json.loads(path.read_text())
    prov = header["provenance"]
    assert header["version"] == 2 and header["defaults"] == {"readout_types": ["DNx"], "input": "visual_projection"}
    assert prov["seeds"] == [{"seed": "DNx", "cell_types": ["DNx"], "left": ["101"], "right": ["102"], "other": []}]
    assert prov["counts"]["by_hop"] == [2, 4, 1] and prov["counts"]["synapses"] == 57
    assert prov["non_commercial"] is True and prov["sources"] == [{"name": "synthetic", "sha256": "0" * 64}]
    data = CircuitData(path)
    assert data.ids == ["101", "102", "201", "202", "301", "302", "401"]
    assert data.hop.tolist() == [0, 0, 1, 1, 1, 1, 2]
    assert [data.type_names[t] for t in data.type_index] == ["DNx", "DNx", "LCa", "LCa", "Inh", "Inh", "deep (untyped)"]
    assert data.transmitter.tolist()[4:6] == ["gaba", "glutamate"] and data.side[6] == "unknown"
    pairs = {(data.ids[a], data.ids[b]): s for a, b, s in zip(data.pre, data.post, data.synapses)}
    assert pairs == {("201", "101"): 10, ("202", "102"): 12, ("301", "102"): 6, ("302", "101"): 7,
                     ("401", "201"): 8, ("401", "202"): 9, ("101", "301"): 5}
    # The same graph through the identifier-based selection used by the committed build.
    pre, post, count, _ = (np.array(c) for c in zip(*BRAIN_EDGES))
    reference = builder.select_subcircuit(pre, post, count, [101, 102], 5, 2, 100)
    assert sorted(map(str, reference["kept"])) == sorted(data.ids + ["999"])  # 999 has no metadata


def test_json_and_npz_builds_load_identically(brain):
    from digitalfly.neural.connectome import CircuitData
    a, b = CircuitData(build("as-json", ["DNx"], "json")), CircuitData(build("as-npz", ["DNx"], "npz"))
    assert b.path.suffix == ".npz"
    assert a.ids == b.ids and a.type_names == b.type_names and a.seeds == b.seeds and a.defaults == b.defaults
    for field in ["type_index", "super_class", "transmitter", "side", "hop", "pre", "post", "synapses"]:
        assert np.array_equal(getattr(a, field), getattr(b, field)), field


def test_seeds_by_id_cap_and_whole_brain(brain):
    from digitalfly.neural.connectome import CircuitData
    header = json.loads(build("by-id", ["102", "101"]).read_text())
    assert [s["seed"] for s in header["provenance"]["seeds"]] == ["102", "101"]
    assert header["neurons"]["id"][:2] == ["102", "101"]
    assert header["defaults"]["readout_types"] == ["DNx"]  # the two seeds cover both sides
    assert json.loads(build("one-side", ["101"]).read_text())["defaults"]["readout_types"] == []
    capped = json.loads(build("capped", ["DNx"], cap=5).read_text())["provenance"]["cap_report"]
    assert capped["binding"] and capped["dropped"] == 1 and capped["kept"] == 6
    whole = CircuitData(build("whole", ["DNx"], whole=True))
    assert whole.ids == ["101", "102", "201", "202", "301", "302", "401", "501", "801", "802"]
    assert whole.hop.tolist() == [0, 0, 1, 1, 1, 1, 2, 3, -1, -1]
    assert whole.provenance["build"]["whole_brain"] and whole.provenance["counts"]["unreached"] == 2


def test_builder_refuses_bad_names_unknown_seeds_and_built_in_names(brain):
    for name, seeds in [("Bad Name", ["DNx"]), ("local", ["DNx"]), ("ok", ["Missing"]), ("ok", ["123"])]:
        with pytest.raises(SystemExit):
            build(name, seeds)
    builder.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (builder.OUT_DIR / "fafb783-dna02.json").write_text("{}")
    with pytest.raises(SystemExit, match="built-in"):
        build("fafb783-dna02", ["DNx"])
    assert build("fafb783-dna02", ["DNx"], committed=True).parent == builder.OUT_DIR


def test_rebuilding_a_circuit_never_touches_other_circuits_or_bridges(brain, monkeypatch):
    local = builder.LOCAL_DIR
    build("steer.v2", ["DNx"])
    bridge = local / "steer.flyvis.json"
    bridge.write_text('{"format": "digitalfly-flyvis-bridge"}')
    build("steer", ["DNx"], "json")
    assert sorted(p.name for p in local.iterdir()) == ["steer.flyvis.json", "steer.json", "steer.v2.json"]
    build("steer", ["DNx"], "npz")  # the same name in the other format replaces it
    assert sorted(p.name for p in local.iterdir()) == ["steer.flyvis.json", "steer.npz", "steer.v2.json"]
    with pytest.raises(SystemExit, match="flyvis"):
        build("steer.flyvis", ["DNx"])
    assert bridge.read_text() == '{"format": "digitalfly-flyvis-bridge"}'
    # A build that fails while writing leaves the previous circuit in place and no partial file behind.
    before = (local / "steer.npz").read_bytes()

    def crash(*args, **kwargs):
        raise MemoryError("out of memory while writing")
    monkeypatch.setattr(builder.np, "savez_compressed", crash)
    with pytest.raises(MemoryError):
        build("steer", ["DNx"], "npz")
    assert (local / "steer.npz").read_bytes() == before
    assert sorted(p.name for p in local.iterdir()) == ["steer.flyvis.json", "steer.npz", "steer.v2.json"]


def test_shared_options_work_before_or_after_the_subcommand():
    for argv in (["--hops", "5", "build", "--name", "x", "--seed", "DNa02"],
                 ["build", "--name", "x", "--seed", "DNa02", "--hops", "5"]):
        args = builder.arguments(argv)
        assert (args.command, args.hops, args.threshold, args.cap) == ("build", 5, 5, 3000), argv
    args = builder.arguments(["--cap", "10", "--threshold", "7", "build", "--name", "x", "--seeds", "DNa02", "--cap", "20"])
    assert (args.cap, args.threshold) == (20, 7)  # given twice, the subcommand's value wins
    assert builder.arguments(["--offline", "prepare"]).offline and builder.arguments(["prepare", "--offline"]).offline
    assert not builder.arguments(["prepare"]).offline
    assert builder.arguments(["--hops", "3"]).hops == 3 and builder.arguments([]).command is None


@pytest.mark.skipif(not (ROOT / ".cache/circuits/fafb783-connectome.npz").is_file(),
                    reason="needs the prepared FlyWire archive (scripts/build_circuit.py prepare)")
def test_general_builder_reproduces_the_committed_circuit(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "LOCAL_DIR", tmp_path)
    built = json.loads(build("check-dna02", ["DNa02"], cap=3000).read_text())
    committed = json.loads(CIRCUIT.read_text())
    assert built["neurons"]["id"] == committed["neurons"]["id"]
    assert built["edges"] == committed["edges"]
    for field in ["hop", "path_strength", "shiu_sign", "transmitter_score"]:
        assert built["neurons"][field] == committed["neurons"][field], field
    for field in ["cell_type", "super_class", "cell_class", "transmitter", "side"]:
        names = lambda d: [d["lookups"][field][i] for i in d["neurons"][field]]
        assert names(built) == names(committed), field
    for key in ["candidates", "kept", "dropped", "weakest_kept_path_strength", "strongest_dropped_path_strength",
                "dropped_by_super_class"]:
        assert built["provenance"]["cap_report"][key] == committed["provenance"]["cap_report"][key], key
    # Format 2 names untyped neurons by class ("… (untyped)") instead of pooling them as "untyped".
    dropped = built["provenance"]["cap_report"]["dropped_top_cell_types"]
    for cell_type, count in committed["provenance"]["cap_report"]["dropped_top_cell_types"].items():
        assert cell_type == "untyped" or dropped[cell_type] == count, cell_type


def test_committed_steering_circuit_records_its_seeds_and_sources():
    raw = STEERING.read_bytes()
    assert len(raw) < 5_000_000
    data = json.loads(raw)
    prov = data["provenance"]
    assert data["version"] == 2 and data["defaults"]["readout_types"] == ["DNa01", "DNa02", "DNp09"]
    assert prov["build"]["seeds"] == ["DNa01", "DNa02", "DNp09"] and prov["build"]["neuron_cap"] == 4000
    assert [(s["seed"], len(s["left"]), len(s["right"])) for s in prov["seeds"]] == [("DNa01", 1, 1), ("DNa02", 1, 1), ("DNp09", 1, 1)]
    assert prov["seeds"][1]["left"] == ["720575940629327659"] and prov["seeds"][1]["right"] == ["720575940604737708"]
    assert prov["non_commercial"] and "CC BY-NC 4.0" in prov["license"]
    assert prov["sources"] == json.loads((ROOT / "data/circuits/downloads.json").read_text())
    neurons, edges = data["neurons"], data["edges"]
    assert len(neurons["id"]) == prov["counts"]["neurons"] == 4000 and len(edges["pre"]) == prov["counts"]["connections"]
    assert min(edges["synapses"]) >= 5 and neurons["hop"][:6] == [0] * 6


@pytest.mark.skipif(not (ROOT / ".cache/circuits/fafb783-connectome.npz").is_file(),
                    reason="needs the prepared FlyWire archive (scripts/build_circuit.py prepare)")
def test_committed_steering_circuit_rebuilds_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "OUT_DIR", tmp_path)
    (tmp_path / "fafb783-steering.json").unlink(missing_ok=True)
    built = build("fafb783-steering", ["DNa01", "DNa02", "DNp09"], cap=4000, committed=True)
    assert built.read_bytes() == STEERING.read_bytes()
