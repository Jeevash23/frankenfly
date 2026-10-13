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
