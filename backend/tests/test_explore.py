"""The connectivity explorer: partners, paths, influence and Neuroglancer links, checked by hand on small graphs."""
import importlib.util
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from digitalfly import explore
from digitalfly.api.models import RunConfig
from digitalfly.main import create_app

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / ".cache/circuits/fafb783-connectome.npz"

# The toy circuit of conftest.py (index: id, cell type, side, transmitter):
#   0 "1" DNx L ACh, 1 "2" DNx R ACh, 2 "3" LCa L ACh, 3 "4" LCa R ACh, 4 "5" Inh L GABA, 5 "6" Inh R Glu,
#   6 "7" DNy L ACh, 7 "8" DNy R ACh, 8 "9" Spd center ACh, 9 "10" Solo L ACh
# Into DNx: LCa 10 + 12, Inh 7 + 6, Solo 5 (40). LCa → Spd 5 + 5 (Spd's only input), Spd → Inh-left 6 (its only input).


@pytest.fixture
def toy(toy_brain):
    return explore.load_graph("toy-brain")


def test_partners_by_cell_type_add_synapses_and_fractions(toy):
    result = explore.partners(toy, "DNx", "upstream")
    rows = {r["cell_type"]: r for r in result["rows"]}
    assert result["total_synapses"] == 40 and result["query_neurons"]["count"] == 2
    assert [r["cell_type"] for r in result["rows"]] == ["LCa", "Inh", "Solo"]
    assert rows["LCa"]["synapses"] == 22 and rows["LCa"]["fraction"] == pytest.approx(22 / 40)
    assert rows["LCa"]["sign"] == 1 and rows["Inh"]["sign"] == -1 and rows["Inh"]["partners"] == 2
    assert rows["Inh"]["left"] == rows["Inh"]["right"] == 1 and rows["Solo"]["type_neurons"] == 1
    # The threshold drops Solo's five-synapse connection and Inh's six-synapse one onto the right DNx.
    strict = {r["cell_type"]: r["synapses"] for r in explore.partners(toy, "DNx", threshold=7)["rows"]}
    assert strict == {"LCa": 22, "Inh": 7}


def test_partners_by_neuron_side_and_downstream(toy):
    left = explore.partners(toy, "DNx", "upstream", group="neuron", side="left")
    assert left["query_neurons"]["ids"] == ["1"] and left["total_synapses"] == 22
    assert [(r["id"], r["synapses"], r["sign"]) for r in left["rows"]] == [("3", 10, 1), ("6", 7, -1), ("10", 5, 1)]
    down = explore.partners(toy, "LCa", "downstream")
    assert {r["cell_type"]: r["synapses"] for r in down["rows"]} == {"DNx": 22, "DNy": 16, "Spd": 10}
    # Downstream, a connection's sign is the query neuron's: Spd → Inh is excitatory although Inh inhibits.
    assert explore.partners(toy, "Spd", "downstream")["rows"][0]["sign"] == 1
    by_id = explore.partners(toy, "3, 4", "downstream", group="neuron")  # root IDs, comma-separated
    assert by_id["query"] == ["3", "4"] and by_id["query_neurons"]["count"] == 2


def test_queries_explain_what_they_cannot_answer(toy):
    with pytest.raises(explore.ExploreError, match="No cell type is named 'Nope'"):
        explore.partners(toy, "Nope")
    assert explore.partners(toy, "dnx ")["query"] == ["DNx"]  # a unique case-insensitive match is accepted
    twins = explore.Graph("t", "t", "circuit", [1, 2], ["Ab", "AB"], [0, 1], ["left"] * 2, ["x"] * 2,
                          ["gaba"] * 2, [0], [1], [5], {})
    with pytest.raises(explore.ExploreError, match="Did you mean Ab, AB"):
        explore.partners(twins, "ab")
    commas = explore.Graph("c", "c", "circuit", [1, 2, 3], ["VES051,VES052", "LAL028, LAL029", "X"], [0, 1, 2],
                           ["left"] * 3, ["x"] * 3, ["gaba"] * 3, [0, 1], [2, 2], [5, 5], {})
    assert commas.tokens("VES051,VES052") == ["VES051,VES052"]  # names with commas stay whole
    assert commas.tokens("X, LAL028, LAL029,VES051,VES052, 7") == ["X", "LAL028, LAL029", "VES051,VES052", "7"]
    assert explore.partners(commas, "X")["groups"] == 2
    with pytest.raises(explore.ExploreError, match="no neurons on the right"):
        explore.partners(toy, "Solo", side="right")
    with pytest.raises(explore.ExploreError, match="not in"):
        explore.partners(toy, "123456")
    with pytest.raises(explore.ExploreError, match="threshold"):
        explore.partners(toy, "DNx", threshold=0)
    with pytest.raises(explore.ExploreError, match="share a cell type"):
        explore.paths(toy, "DNx", "DNx")


def test_strongest_and_shortest_cell_type_paths(toy):
    result = explore.paths(toy, "LCa", "DNx", "strongest")
    first, second = result["paths"][:2]
    assert first["cell_types"] == ["LCa", "DNx"] and first["strength"] == pytest.approx(22 / 40) and first["net_sign"] == 1
    # LCa → Spd carries all of Spd's input, Spd → Inh all of Inh's; Inh → DNx 13 of DNx's 40.
    assert second["cell_types"] == ["LCa", "Spd", "Inh", "DNx"] and second["strength"] == pytest.approx(13 / 40)
    assert second["net_sign"] == -1 and [e["synapses"] for e in second["edges"]] == [10, 6, 13]
    shortest = explore.paths(toy, "LCa", "DNx", "shortest")["paths"]
    assert [p["steps"] for p in shortest] == [1, 3]
    assert explore.paths(toy, "LCa", "DNx", max_hops=2)["paths"][0]["steps"] == 1
    assert len(explore.paths(toy, "LCa", "DNx", max_hops=2)["paths"]) == 1
    none = explore.paths(toy, "DNx", "LCa")
    assert none["paths"] == [] and not none["connected"]


def test_a_weak_direct_link_loses_the_strongest_path_but_wins_the_shortest():
    # A → C directly carries 1 of C's 101 synapses; A → B → C carries all of B's and 100 of C's.
    graph = explore.Graph("t", "t", "circuit", [1, 2, 3], ["A", "B", "C"], [0, 1, 2], ["left"] * 3, ["x"] * 3,
                          ["acetylcholine"] * 3, [0, 1, 0], [1, 2, 2], [5, 100, 1], {})
    strongest = explore.paths(graph, "A", "C", "strongest", threshold=1)["paths"]
    assert [p["cell_types"] for p in strongest] == [["A", "B", "C"], ["A", "C"]]
    assert strongest[0]["strength"] == pytest.approx(100 / 101)
    shortest = explore.paths(graph, "A", "C", "shortest", threshold=1)["paths"]
    assert [p["cell_types"] for p in shortest] == [["A", "C"], ["A", "B", "C"]]


def test_neuron_paths_use_each_neurons_input_fraction(toy):
    result = explore.paths(toy, "3", "1", level="neuron")
    first = result["paths"][0]
    # neuron 1 (left DNx) receives 10 from neuron 3, 7 from 6 and 5 from 10.
    assert [n["id"] for n in first["neurons"]] == ["3", "1"] and first["strength"] == pytest.approx(10 / 22)
    # Left LCa (3) reaches the right DNx (2) through Spd (9, half its input) and the left Inh (5, all of its input),
    # which gives the right DNx 6 of its 18 synapses; the right LCa has no path to the left DNx at all.
    across = explore.paths(toy, "LCa", "DNx", level="neuron", source_side="left", target_side="right")["paths"]
    assert [n["id"] for n in across[0]["neurons"]] == ["3", "9", "5", "2"]
    assert across[0]["strength"] == pytest.approx(.5 * 1 * 6 / 18) and across[0]["net_sign"] == -1
    assert explore.paths(toy, "LCa", "DNx", level="neuron", source_side="right", target_side="left")["paths"] == []
    with pytest.raises(explore.ExploreError, match="neuron-level"):
        explore.paths(toy, "LCa", "DNx", source_side="left")


def ring(weights, transmitters):
    """Neurons 0 → 1 → 2 → 0 with the given synapse counts, plus 0 → 3."""
    return explore.Graph("ring", "ring", "circuit", [10, 11, 12, 13], ["A", "B", "C", "D"], [0, 1, 2, 3],
                         ["left"] * 4, ["x"] * 4, transmitters, [0, 1, 2, 0], [1, 2, 0, 3], weights, {})


def dense_influence(graph, signed=True):
    n = len(graph.ids)
    w = np.zeros((n, n))
    signs = graph.signs() if signed else np.ones(n)
    for a, b, s in zip(graph.pre, graph.post, graph.synapses):
        w[b, a] += signs[a] * s
    lam = np.linalg.eigvals(w).real.max()
    return np.linalg.inv(np.eye(n) - .99 * w / lam), lam


def test_influence_is_the_banc_style_linear_steady_state():
    graph = ring([5, 10, 20, 8], ["acetylcholine", "acetylcholine", "acetylcholine", "acetylcholine"])
    inverse, lam = dense_influence(graph)
    result = explore.influence(graph, "A", group="neuron", threshold=1)
    assert result["model"]["lambda"] == pytest.approx(lam) and result["model"]["scale_rule"] == "largest real eigenvalue"
    got = {r["id"]: r["influence"] for r in result["rows"]}
    assert got == pytest.approx({"11": inverse[1, 0], "12": inverse[2, 0], "13": inverse[3, 0]})
    assert result["query_self"] == pytest.approx(inverse[0, 0]) and result["model"]["relative_residual"] < 1e-9
    # "onto": the influence of stimulating each neuron alone on the query, a row of the same inverse.
    onto = explore.influence(graph, "D", direction="onto", group="neuron", threshold=1)
    assert {r["id"]: r["influence"] for r in onto["rows"]} == pytest.approx(
        {"10": inverse[3, 0], "11": inverse[3, 1], "12": inverse[3, 2]})
    by_type = explore.influence(graph, "A", threshold=1)
    assert by_type["rows"][0]["influence"] == pytest.approx(max(inverse[1:, 0]))


def test_signed_influence_carries_inhibition_and_the_fallback_scaling():
    # B is GABAergic, so C is inhibited; the loop's complex eigenvalues still have a positive real part.
    graph = ring([5, 10, 20, 8], ["acetylcholine", "gaba", "acetylcholine", "acetylcholine"])
    inverse, lam = dense_influence(graph)
    result = explore.influence(graph, "A", group="neuron", threshold=1)
    assert result["model"]["scale_rule"] == "largest real eigenvalue" and result["model"]["lambda"] == pytest.approx(lam)
    got = {r["id"]: r["influence"] for r in result["rows"]}
    assert got == pytest.approx({"11": inverse[1, 0], "12": inverse[2, 0], "13": inverse[3, 0]})
    assert got["11"] > 0 > got["12"]
    unsigned = explore.influence(graph, "A", group="neuron", threshold=1, signed=False)
    assert all(r["sign"] == 1 for r in unsigned["rows"])
    # A two-neuron loop of excitation and inhibition has eigenvalues ±i√(5 × 10): no positive real part.
    pair = explore.Graph("p", "p", "circuit", [1, 2], ["A", "B"], [0, 1], ["left"] * 2, ["x"] * 2,
                         ["acetylcholine", "gaba"], [0, 1], [1, 0], [5, 10], {})
    looped = explore.influence(pair, "A", group="neuron", threshold=1)
    assert looped["model"]["scale_rule"].startswith("spectral radius")
    assert looped["model"]["lambda"] == pytest.approx(50 ** .5)
    # An acyclic graph has no eigenvalue to scale by: its largest row sum of |W| is used.
    chain = explore.Graph("c", "c", "circuit", [1, 2, 3], ["A", "B", "C"], [0, 1, 2], ["left"] * 3, ["x"] * 3,
                          ["acetylcholine"] * 3, [0, 1, 0], [1, 2, 2], [5, 10, 4], {})
    rows = explore.influence(chain, "A", group="neuron", threshold=1)
    assert rows["model"]["scale_rule"].startswith("largest row sum") and rows["model"]["lambda"] == 14
    b = .99 * 5 / 14
    assert {r["id"]: r["influence"] for r in rows["rows"]} == pytest.approx({"2": b, "3": .99 * (4 + 10 * b) / 14})


def test_excluded_transmitters_have_no_sign_unless_counted_excitatory(toy):
    graph = ring([5, 10, 20, 8], ["acetylcholine", "dopamine", "acetylcholine", "acetylcholine"])
    assert explore.paths(graph, "A", "C", threshold=1)["paths"][0]["net_sign"] == 0
    assert explore.paths(graph, "A", "C", threshold=1, other_transmitters="excitatory")["paths"][0]["net_sign"] == 1
    reached = {r["id"] for r in explore.influence(graph, "A", group="neuron", threshold=1)["rows"]}
    assert reached == {"11", "13"}  # nothing passes the dopaminergic neuron


def decode(url):
    assert url.startswith(explore.NEUROGLANCER + "/#!")
    return json.loads(urllib.parse.unquote(url.split("#!", 1)[1]))


def test_neuroglancer_links_stream_public_flywire_segments(toy):
    result = explore.neuroglancer(None, [{"label": "pair", "ids": ["720575940604737708", "720575940629327659"]},
                                         {"ids": ["720575940627692677"], "color": "#123456"}], "test")
    state = decode(result["url"])
    assert state == result["state"] and state["layout"] == "3d" and state["title"] == "test"
    layers = {layer["name"]: layer for layer in state["layers"]}
    assert layers["pair"]["source"]["url"] == "precomputed://gs://flywire_v141_m783"
    assert layers["pair"]["segments"] == ["720575940604737708", "720575940629327659"]
    assert layers["group 2"]["segmentDefaultColor"] == "#123456"
    assert layers["brain outline"]["source"].startswith("precomputed://gs://flywire_neuropil_meshes/")
    assert result["neurons"] == 3 and not result["truncated"]
    capped = explore.neuroglancer(None, [{"ids": [str(i) for i in range(1, 11)]}], limit=4)
    assert capped["truncated"] and capped["neurons"] == 4
    with pytest.raises(explore.ExploreError, match="not a FlyWire root ID"):
        explore.neuroglancer(None, [{"ids": ["12a"]}])
    # The toy circuit is synthetic, so its IDs are not FlyWire's.
    with pytest.raises(explore.ExploreError, match="not FlyWire v783"):
        explore.neuroglancer(toy, [{"cell_type": "DNx"}])


def test_neuroglancer_for_a_committed_circuit_and_its_cell_types():
    request = explore.NeuroglancerRequest(circuit="fafb783-dna02", groups=[{"cell_type": "LC10a", "side": "left"}],
                                          graph="fafb783-dna02")
    result = explore.neuroglancer_request(request)
    seeds, rest, lc10a = result["groups"]
    assert seeds["label"] == "seeds: DNa02" and seeds["neurons"] == 2 and seeds["neurons"] + rest["neurons"] == 3000
    graph = explore.load_graph("fafb783-dna02")
    assert lc10a["neurons"] == int(((graph.type_names[graph.type_index] == "LC10a") & (graph.side == "left")).sum())


@pytest.fixture
def client(toy_brain, tmp_path, monkeypatch):
    monkeypatch.setattr("digitalfly.simulation.experiment.ROOT", tmp_path)
    monkeypatch.setattr("digitalfly.main.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy", neural_model="connectome"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_the_explorer_api(client, monkeypatch, tmp_path):
    graphs = client.get("/api/explore/graphs").json()
    assert graphs["running"] == "fafb783-dna02" and "toy-brain" in {g["key"] for g in graphs["graphs"]}
    assert graphs["neuroglancer"]["sources"]["segmentation"] == "precomputed://gs://flywire_v141_m783"
    rows = client.get("/api/explore/partners", params={"query": "DNx", "graph": "toy-brain"}).json()["rows"]
    assert rows[0]["cell_type"] == "LCa" and rows[0]["in_running_circuit"] is None  # not in the running circuit
    real = client.get("/api/explore/partners", params={"query": "DNa02", "graph": "fafb783-dna02", "limit": 3}).json()
    assert real["running_circuit"] == "fafb783-dna02" and real["rows"][0]["in_running_circuit"]["neurons"] >= 1
    path = client.get("/api/explore/paths", params={"source": "LCa", "target": "DNx", "graph": "toy-brain",
                                                    "mode": "shortest"}).json()
    assert path["paths"][0]["cell_types"] == ["LCa", "DNx"]
    influence = client.get("/api/explore/influence", params={"query": "LCa", "graph": "toy-brain", "signed": "false"})
    assert influence.status_code == 200 and influence.json()["signed"] is False
    lookup = client.get("/api/explore/lookup", params={"q": "d", "graph": "toy-brain"}).json()
    assert [m["cell_type"] for m in lookup["matches"]][:2] == ["DNx", "DNy"]
    assert client.get("/api/explore/partners", params={"query": "Nope", "graph": "toy-brain"}).status_code == 422
    assert client.get("/api/explore/partners", params={"query": "DNx", "graph": "Bad/Name"}).status_code == 422
    assert client.get("/api/explore/partners", params={"query": "DNx", "graph": "no-such"}).status_code == 404
    assert client.get("/api/explore/paths", params={"source": "a", "target": "b", "mode": "x"}).status_code == 422
    monkeypatch.setattr(explore, "ARCHIVE", tmp_path / "missing.npz")
    missing = client.get("/api/explore/partners", params={"query": "DNa02"})
    assert missing.status_code == 404 and "build_circuit.py prepare" in missing.json()["detail"]
    link = client.post("/api/explore/neuroglancer", json={"groups": [{"ids": ["720575940604737708"]}]})
    assert link.status_code == 200 and link.json()["neurons"] == 1  # IDs alone need no archive
    big = {"groups": [{"ids": [str(10 ** 17 + i) for i in range(15000)]}], "limit": 20000}
    assert client.post("/api/explore/neuroglancer", json=big).json()["neurons"] == 15000  # its own body limit
    assert client.post("/api/explore/neuroglancer", json={"groups": [{"ids": ["x"]}]}).status_code == 422


def test_the_whole_brain_archive_through_the_builders_prepare_step(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_circuit", ROOT / "scripts/build_circuit.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, "PREPARED", tmp_path / "prepared.npz")
    monkeypatch.setattr(builder, "CATALOG", tmp_path / "catalog.json")
    rows = {301: ("DNx", "left", "acetylcholine"), 302: ("DNx", "right", "acetylcholine"),
            201: ("LCa", "left", "acetylcholine"), 101: ("", "left", "gaba")}
    ids = sorted(rows)
    meta = {"id": np.array(ids, dtype=np.int64), "cell_type": np.array([rows[i][0] for i in ids], dtype=object),
            "super_class": np.array(["central"] * 4, dtype=object), "cell_class": np.array(["c"] * 4, dtype=object),
            "cell_sub_class": np.array([""] * 4, dtype=object), "side": np.array([rows[i][1] for i in ids], dtype=object),
            "neurotransmitter_predicted": np.array([rows[i][2] for i in ids], dtype=object),
            "neurotransmitter_score": np.ones(4)}
    columns = {"Presynaptic_ID": np.array([201, 101, 201]), "Postsynaptic_ID": np.array([301, 301, 302]),
               "Connectivity": np.array([9, 3, 6]), "Excitatory": np.array([1, -1, 1])}
    builder.save_prepared(meta, columns, [{"name": "synthetic", "sha256": "0" * 64}])
    monkeypatch.setattr(explore, "ARCHIVE", tmp_path / "prepared.npz")
    graph = explore.load_graph("brain")
    assert graph.kind == "brain" and len(graph.ids) == 4 and graph.provenance["release"] == "v783"
    up = explore.partners(graph, "301", group="neuron", threshold=1)
    assert [(r["id"], r["cell_type"], r["sign"]) for r in up["rows"]] == [("201", "LCa", 1), ("101", "c (untyped)", -1)]
    assert explore.partners(graph, "DNx", threshold=5)["total_synapses"] == 15
    assert explore.lookup(graph, "301")["matches"][0] == {"kind": "neuron", "id": "301", "cell_type": "DNx",
                                                           "side": "left", "super_class": "central",
                                                           "transmitter": "acetylcholine"}


@pytest.mark.skipif(not ARCHIVE.is_file(), reason="needs the prepared FlyWire archive (scripts/build_circuit.py prepare)")
def test_whole_brain_queries_take_seconds():
    started = time.monotonic()
    graph = explore.load_graph("brain")
    assert len(graph.ids) == 144_837
    up = explore.partners(graph, "DNa02")
    assert up["query_neurons"]["count"] == 2 and up["groups"] > 100
    route = explore.paths(graph, "LC10a", "DNa02", level="neuron")
    assert route["paths"] and route["paths"][0]["neurons"][0]["cell_type"] == "LC10a"
    reach = explore.influence(graph, "DNa02", direction="onto", limit=10)
    assert reach["model"]["relative_residual"] < 1e-6 and len(reach["rows"]) == 10
    assert time.monotonic() - started < 30  # load, matrices, eigenvalue and three queries (a few seconds here)
    again = time.monotonic()
    explore.influence(graph, "LC10a", limit=10)
    explore.paths(graph, "LC10a", "DNa02", mode="shortest")
    assert time.monotonic() - again < 10


def test_toolkit_explorer_commands(tmp_path):
    out = tmp_path / "partners"
    run = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "partners", "--graph", "fafb783-dna02",
                          "--query", "DNa02", "--limit", "3", "--out", str(out)], capture_output=True, text=True,
                         timeout=120)
    assert run.returncode == 0, run.stderr
    assert "| Cell type |" in run.stdout and (tmp_path / "partners.csv").is_file()
    report = json.loads((tmp_path / "partners.json").read_text())
    assert report["command"] == "partners" and report["provenance"]["circuits"][0]["name"] == "fafb783-dna02"
    link = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "neuroglancer", "--ids",
                           "720575940604737708"], capture_output=True, text=True, timeout=120)
    assert link.returncode == 0 and explore.NEUROGLANCER in link.stdout
    bad = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "route", "--graph", "fafb783-dna02",
                          "--source", "Nope", "--target", "DNa02"], capture_output=True, text=True, timeout=120)
    assert bad.returncode != 0 and "No cell type is named 'Nope'" in bad.stderr
