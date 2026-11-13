"""Connectivity explorer: partners, paths and influence over the whole FlyWire v783 brain or any circuit.

Every query runs on one *graph*: "brain" (all 144,837 neurons and 15.1 million connections of the prepared archive
in .cache/circuits/, which `scripts/build_circuit.py prepare` writes) or a circuit file by name (committed or built
locally). A query first keeps the connections of at least `threshold` synapses (default 5). Nothing is downloaded.

What each result is:
  data-derived  neurons, cell types, sides, predicted transmitters and synapse counts (FlyWire FAFB v783)
  assumed       signs, from the predicted transmitter of the presynaptic neuron with the model's rule
                (acetylcholine +1; GABA and glutamate −1; dopamine, serotonin, octopamine and unknown 0 unless
                `other_transmitters="excitatory"`), as in digitalfly.neural.connectome
  engineered    the influence score's linear dynamics and its rescaling (below); path weights

Partners. Upstream partners of a query (a cell type, FlyWire root IDs, or several of either, optionally one side)
are the neurons with a connection onto any query neuron; downstream partners receive one. A row's fraction is its
synapses ÷ every synapse onto (upstream) or from (downstream) the query neurons in the kept connections.

Paths. A step u → v carries the fraction f = synapses(u → v) ÷ all of v's input synapses (neurons), or, between cell
types, the synapses from type A onto type B ÷ all of B's input synapses. A path's strength multiplies its steps' f;
its net sign multiplies the steps' signs (0 when a step's sign is excluded). "strongest" finds the path with the
largest strength (Dijkstra on −ln f); "shortest" the one with the fewest steps, ties broken by strength (weights
1 + 0.001 × −ln f). Alternatives are the best path through each other connection, ranked: the first row is the exact
optimum, the others are distinct simple paths, not an exhaustive k-shortest-paths list.

Influence, after the steady-state influence of the BANC paper's ConnectomeInfluenceCalculator
(github.com/DrugowitschLab/ConnectomeInfluenceCalculator): a linear rate model τ dr/dt = (W̃ − I) r + s with
W_ij = sign(j) × synapses(j → i) (counts, signed) and W̃ = 0.99 W ÷ λ, where λ is the largest real part of W's
eigenvalues. Seeds get s = 1. The steady state r = (I − W̃)⁻¹ s is solved with BiCGSTAB; r_i is i's influence.
"onto" solves the transposed system, so x_j is the influence on the query neurons (summed) of stimulating j alone.
It is a linear approximation of polysynaptic reach, with no rectification, thresholds or dynamics of the
simulation's models; negative values are net inhibition under the assumed signs. If λ ≤ 0 (an acyclic or
inhibition-dominated graph), W is scaled by the spectral radius of |W| instead, and failing that by its largest
row sum; the result says which rule was used.
"""
import json
import math
import threading
import urllib.parse
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
import numpy as np
from pydantic import Field
from scipy import sparse
from scipy.sparse import csgraph
from scipy.sparse import linalg as sparse_linalg
from digitalfly.api.models import StrictModel
from digitalfly.neural.connectome import CLASSIC_SIGNS, load_circuit

ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = ROOT / ".cache/circuits/fafb783-connectome.npz"
BRAIN = "brain"
LICENSE = "CC BY-NC 4.0 (FlyWire public-release terms): non-commercial use only"
ATTRIBUTION = ("FlyWire Consortium (Dorkenwald et al. 2024; Schlegel et al. 2024, Nature 634), connectivity as released "
               "with Shiu et al. 2024; predicted transmitters from Eckstein et al. 2024")
SPECTRAL_TARGET = 0.99
SHORTEST_TIEBREAK = 1e-3
TINY = 1e-12
MAX_QUERY_NEURONS = 20_000
NEUROGLANCER = "https://neuroglancer-demo.appspot.com"
NG_SOURCES = {  # public FlyWire buckets: neurons stream from Google Cloud Storage, nothing is downloaded beforehand
    "segmentation": "precomputed://gs://flywire_v141_m783",
    "em": "precomputed://gs://flywire_em/aligned/v1",
    "brain_mesh": "precomputed://gs://flywire_neuropil_meshes/whole_neuropil/brain_mesh_v141.surf",
}
NG_COLORS = ["#e6550d", "#3182bd", "#31a354", "#9467bd", "#d62728", "#17becf", "#bcbd22", "#e377c2", "#8c564b",
             "#7f7f7f"]
NG_SEGMENT_LIMIT = 20_000
SIGN_RULE = ("Signs from the predicted transmitter of the presynaptic neuron: acetylcholine +1; GABA and glutamate −1; "
             "dopamine, serotonin, octopamine and unknown {other}.")


class ExploreError(ValueError):
    """A query this graph cannot answer, with the reason (the API answers 422)."""


class Unavailable(FileNotFoundError):
    """The graph's data is missing (the API answers 404)."""


class Layer:
    """One graph's connections of at least `threshold` synapses, as sparse matrices (built once, then cached)."""

    def __init__(self, graph: "Graph", threshold: int):
        n = len(graph.ids)
        keep = graph.synapses >= threshold
        self.threshold = threshold
        self.pre, self.post = graph.pre[keep], graph.post[keep]
        self.syn = graph.synapses[keep].astype(np.float64)
        # rows: presynaptic neuron (out) / postsynaptic neuron (in)
        self.out = sparse.csr_matrix((self.syn, (self.pre, self.post)), shape=(n, n))
        self.into = self.out.T.tocsr()
        self.in_total = np.asarray(self.into.sum(axis=1)).ravel()
        self.out_total = np.asarray(self.out.sum(axis=1)).ravel()
        self._cache = {}
        self.lock = threading.Lock()

    def cached(self, key, build):
        with self.lock:
            if key not in self._cache:
                self._cache[key] = build()
            return self._cache[key]


class Graph:
    """Neurons and connections of one graph, with lookups shared by every query."""

    def __init__(self, key, title, kind, ids, type_names, type_index, side, super_class, transmitter, pre, post,
                 synapses, provenance):
        self.key, self.title, self.kind, self.provenance = key, title, kind, provenance
        self.ids = np.asarray(ids, dtype=np.int64)
        self.type_names = np.asarray(type_names, dtype=object)
        self.type_index = np.asarray(type_index, dtype=np.int64)
        self.side = np.asarray(side, dtype=object)
        self.super_class = np.asarray(super_class, dtype=object)
        self.transmitter = np.asarray(transmitter, dtype=object)
        self.pre, self.post = np.asarray(pre, dtype=np.int32), np.asarray(post, dtype=np.int32)
        self.synapses = np.asarray(synapses, dtype=np.int32)
        self.order = np.argsort(self.ids, kind="stable")
        self.type_counts = np.bincount(self.type_index, minlength=len(self.type_names))
        self.type_lookup = {str(name): i for i, name in enumerate(self.type_names)}
        self.folded = {}
        for name in self.type_lookup:
            self.folded.setdefault(name.casefold(), []).append(name)
        member_order = np.argsort(self.type_index, kind="stable")
        bounds = np.searchsorted(self.type_index[member_order], np.arange(len(self.type_names) + 1))
        self._members = (member_order, bounds)
        self._layers, self._signs = {}, {}
        self.lock = threading.Lock()

    def describe(self):
        return {"key": self.key, "title": self.title, "kind": self.kind, "neurons": int(len(self.ids)),
                "connections": int(len(self.synapses)), "cell_types": int(len(self.type_names)),
                "license": self.provenance.get("license", LICENSE)}

    def layer(self, threshold: int) -> Layer:
        with self.lock:
            if threshold not in self._layers:
                if len(self._layers) >= 2:  # keep the two most recent thresholds
                    self._layers.pop(next(iter(self._layers)))
                self._layers[threshold] = Layer(self, threshold)
            return self._layers[threshold]

    def type_members(self, t: int) -> np.ndarray:
        order, bounds = self._members
        return order[bounds[t]:bounds[t + 1]]

    def index_of(self, neuron_id: int) -> int:
        position = np.searchsorted(self.ids, neuron_id, sorter=self.order)
        if position < len(self.ids) and self.ids[self.order[position]] == neuron_id:
            return int(self.order[position])
        return -1

    def cell_type(self, name: str) -> int:
        name = name.strip()
        if name in self.type_lookup:
            return self.type_lookup[name]
        folded = self.folded.get(name.casefold(), [])
        if len(folded) == 1:
            return self.type_lookup[folded[0]]
        raise ExploreError(f"No cell type is named {name!r} in {self.title}." + (
            f" Did you mean {', '.join(folded)}?" if folded else " Names are case-sensitive; search for one first."))

    def resolve(self, query: str, side: str = "both") -> tuple[np.ndarray, list[str]]:
        """Neuron indices of a query: comma-separated cell-type names and FlyWire root IDs, on one side or both."""
        tokens = [token.strip() for token in str(query).split(",") if token.strip()]
        if not tokens:
            raise ExploreError("Give a cell type or a FlyWire root ID.")
        if len(tokens) > 50:
            raise ExploreError("Give at most 50 cell types or neuron IDs at once.")
        found, labels = [], []
        for token in tokens:
            if token.isdigit():
                index = self.index_of(int(token))
                if index < 0:
                    raise ExploreError(f"Neuron {token} is not in {self.title}.")
                found.append(np.array([index]))
                labels.append(token)
            else:
                t = self.cell_type(token)
                found.append(self.type_members(t))
                labels.append(str(self.type_names[t]))
        neurons = np.unique(np.concatenate(found))
        if side in ("left", "right"):
            neurons = neurons[self.side[neurons] == side]
        if not len(neurons):
            raise ExploreError(f"{', '.join(labels)} has no neurons on the {side} side in {self.title}.")
        if len(neurons) > MAX_QUERY_NEURONS:
            raise ExploreError(f"The query has {len(neurons):,} neurons; narrow it to at most {MAX_QUERY_NEURONS:,}.")
        return neurons, labels

    def neuron(self, i: int) -> dict:
        return {"id": str(self.ids[i]), "cell_type": str(self.type_names[self.type_index[i]]),
                "side": str(self.side[i]), "super_class": str(self.super_class[i]),
                "transmitter": str(self.transmitter[i])}

    def signs(self, other_transmitters: str = "excluded") -> np.ndarray:
        if other_transmitters not in self._signs:
            other = 1.0 if other_transmitters == "excitatory" else 0.0
            self._signs[other_transmitters] = np.array([CLASSIC_SIGNS.get(nt, other) for nt in self.transmitter],
                                                       dtype=np.float64)
        return self._signs[other_transmitters]


# ---------------------------------------------------------------------------------------------- loading graphs

@lru_cache(maxsize=1)
def _brain(path: str, mtime_ns: int) -> Graph:
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    header = json.loads(str(data["header"]))
    lookup = lambda key: data[f"lookup_{key}"].astype(object)[data[key]]  # noqa: E731
    return Graph(BRAIN, "the whole FlyWire v783 brain", "brain", data["neuron_id"], data["lookup_cell_type"],
                 data["cell_type"], lookup("side"), lookup("super_class"), lookup("transmitter"), data["pre"],
                 data["post"], data["synapses"],
                 {"dataset": "FlyWire FAFB", "release": "v783", "license": LICENSE, "attribution": ATTRIBUTION,
                  "sources": [{k: s.get(k) for k in ("name", "url", "sha256", "license")} for s in header["sources"]],
                  "coverage": f"Every proofread neuron with metadata ({header['neurons']:,}) and every connection "
                              f"between them ({header['connections']:,}), the prepared archive of scripts/build_circuit.py"})


@lru_cache(maxsize=3)
def _circuit(path: str, sha256: str) -> Graph:
    data = load_circuit(Path(path))
    prov = data.provenance
    return Graph(data.key, f"the {data.key} circuit", "circuit", [int(i) for i in data.ids], data.type_names,
                 data.type_index, data.side, data.super_class, data.transmitter, data.pre, data.post, data.synapses,
                 {"dataset": prov.get("dataset"), "release": prov.get("release"), "license": prov.get("license"),
                  "attribution": prov.get("attribution", ATTRIBUTION), "coverage": prov.get("coverage"),
                  "sha256": sha256})


def brain_available() -> bool:
    return ARCHIVE.is_file()


def load_graph(key: str = BRAIN) -> Graph:
    """The whole brain ("brain") or a circuit by name."""
    if key == BRAIN:
        if not ARCHIVE.is_file():
            raise Unavailable("The whole-brain explorer reads the prepared FlyWire archive, which is not there yet. "
                              "Run: backend/.venv/bin/python scripts/build_circuit.py prepare")
        return _brain(str(ARCHIVE), ARCHIVE.stat().st_mtime_ns)
    try:
        data = load_circuit(key)
    except FileNotFoundError as exc:
        raise Unavailable(str(exc)) from exc
    return _circuit(str(data.path), data.sha256)


def running_view(circuit: str | None):
    """Per cell type, how many neurons the running circuit has on each side: what a Workbench manipulation can reach."""
    if circuit is None:
        return None
    try:
        data = load_circuit(circuit)
    except (OSError, ValueError):
        return None
    left = np.bincount(data.type_index, weights=data.side == "left", minlength=len(data.type_names))
    right = np.bincount(data.type_index, weights=data.side == "right", minlength=len(data.type_names))
    return {"circuit": data.key, "types": {name: (int(data.type_counts[i]), int(left[i]), int(right[i]))
                                          for i, name in enumerate(data.type_names)}}


def _in_running(running, cell_type: str):
    if running is None:
        return None
    counts = running["types"].get(cell_type)
    return None if counts is None else {"neurons": counts[0], "left": counts[1], "right": counts[2]}


def _check_threshold(threshold: int):
    if not 1 <= int(threshold) <= 1000:
        raise ExploreError("Choose a synapse threshold from 1 to 1000.")


def lookup(graph: Graph, text: str, limit: int = 20) -> dict:
    """Cell types whose name contains `text` (exact and prefix matches first), and the neuron when it is a root ID."""
    text = text.strip()
    rows = []
    if text.isdigit():
        index = graph.index_of(int(text))
        if index >= 0:
            rows.append({"kind": "neuron", **graph.neuron(index)})
    folded = text.casefold()
    names = [str(n) for n in graph.type_names]
    hits = [n for n in names if folded in n.casefold()] if folded else []
    hits.sort(key=lambda n: (n.casefold() != folded, not n.casefold().startswith(folded), len(n), n))
    for name in hits[:limit]:
        members = graph.type_members(graph.type_lookup[name])
        sides = graph.side[members]
        rows.append({"kind": "cell_type", "cell_type": name, "neurons": int(len(members)),
                     "left": int((sides == "left").sum()), "right": int((sides == "right").sum()),
                     "super_class": _mode(graph.super_class[members])})
    return {"graph": graph.key, "query": text, "matches": rows, "more": max(0, len(hits) - limit)}


def _mode(values) -> str:
    if not len(values):
        return ""
    unique, counts = np.unique(values.astype(str), return_counts=True)
    return str(unique[np.argmax(counts)])


# ----------------------------------------------------------------------------------------------------- partners

def partners(graph: Graph, query: str, direction: str = "upstream", group: str = "cell_type", side: str = "both",
             threshold: int = 5, limit: int = 50, other_transmitters: str = "excluded", running=None) -> dict:
    """The query neurons' presynaptic (upstream) or postsynaptic (downstream) partners, by cell type or neuron."""
    _check_threshold(threshold)
    if direction not in ("upstream", "downstream") or group not in ("cell_type", "neuron"):
        raise ExploreError("direction is upstream or downstream; group is cell_type or neuron.")
    neurons, labels = graph.resolve(query, side)
    layer = graph.layer(threshold)
    matrix = layer.into if direction == "upstream" else layer.out
    block = matrix[neurons].tocoo()  # rows: query neurons; columns: partners
    query_n, partner = neurons[block.row], block.col
    synapses = block.data
    total = float(synapses.sum())
    signs = graph.signs(other_transmitters)
    # the sign of a connection is its presynaptic neuron's: the partner's upstream, the query neuron's downstream
    edge_sign = signs[partner] if direction == "upstream" else signs[query_n]
    signed = edge_sign * synapses
    rows = []
    if group == "cell_type":
        key = graph.type_index[partner]
        unique, inverse = np.unique(key, return_inverse=True)
        syn = np.bincount(inverse, weights=synapses)
        net = np.bincount(inverse, weights=signed)
        connections = np.bincount(inverse)
        for k in np.argsort(-syn, kind="stable")[:limit]:
            members = np.unique(partner[inverse == k])
            name = str(graph.type_names[unique[k]])
            nts = graph.transmitter[members].astype(str)
            sides = graph.side[members]
            rows.append({"cell_type": name, "super_class": _mode(graph.super_class[members]),
                         "transmitter": _mode(nts), "partners": int(len(members)),
                         "type_neurons": int(graph.type_counts[unique[k]]),
                         "left": int((sides == "left").sum()), "right": int((sides == "right").sum()),
                         "synapses": int(syn[k]), "connections": int(connections[k]),
                         "fraction": float(syn[k] / total) if total else 0.0, "sign": int(np.sign(net[k])),
                         "in_running_circuit": _in_running(running, name)})
        groups = int(len(unique))
    else:
        unique, inverse = np.unique(partner, return_inverse=True)
        syn = np.bincount(inverse, weights=synapses)
        net = np.bincount(inverse, weights=signed)
        for k in np.argsort(-syn, kind="stable")[:limit]:
            info = graph.neuron(int(unique[k]))
            rows.append({**info, "synapses": int(syn[k]), "fraction": float(syn[k] / total) if total else 0.0,
                         "sign": int(np.sign(net[k])), "in_running_circuit": _in_running(running, info["cell_type"])})
        groups = int(len(unique))
    q_sides = graph.side[neurons]
    return {
        "graph": graph.key, "query": labels, "side": side, "direction": direction, "group": group,
        "threshold": threshold, "query_neurons": {"count": int(len(neurons)), "left": int((q_sides == "left").sum()),
                                                  "right": int((q_sides == "right").sum()),
                                                  "ids": [str(graph.ids[i]) for i in neurons[:500]]},
        "total_synapses": int(total), "groups": groups, "rows": rows, "running_circuit": running and running["circuit"],
        "rule": (f"Connections of at least {threshold} synapses. Fraction: the row's synapses ÷ every synapse "
                 f"{'onto' if direction == 'upstream' else 'from'} the query neurons. "
                 + SIGN_RULE.format(other="+1" if other_transmitters == "excitatory" else "0 (excluded)")),
    }


# -------------------------------------------------------------------------------------------------------- paths

def _type_graph(graph: Graph, layer: Layer):
    """Cell-type connections of a layer: (pre type, post type, synapses, signed synapses with each rule)."""
    def build():
        n_types = len(graph.type_names)
        key = graph.type_index[layer.pre] * n_types + graph.type_index[layer.post]
        unique, inverse = np.unique(key, return_inverse=True)
        syn = np.bincount(inverse, weights=layer.syn)
        signed = {rule: np.bincount(inverse, weights=graph.signs(rule)[layer.pre] * layer.syn)
                  for rule in ("excluded", "excitatory")}
        incoming = np.bincount(graph.type_index[layer.post], weights=layer.syn, minlength=n_types)
        return unique // n_types, unique % n_types, syn, signed, incoming
    return layer.cached("types", build)


def _weights(fraction: np.ndarray, mode: str) -> np.ndarray:
    cost = -np.log(np.clip(fraction, TINY, 1.0))
    return (1.0 + SHORTEST_TIEBREAK * cost if mode == "shortest" else cost) + TINY  # explicit zeros are not edges


def _walk(pred: np.ndarray, node: int) -> list[int]:
    out = [node]
    while pred[out[-1]] >= 0:
        out.append(int(pred[out[-1]]))
        if len(out) > len(pred):
            break
    return out


def _best_paths(pre, post, weight, n, sources, targets, limit, max_hops):
    """The optimum and the best path through each other connection, distinct and simple, by total weight."""
    forward = sparse.csr_matrix((weight, (pre, post)), shape=(n, n))
    d_s, pred_s, _ = csgraph.dijkstra(forward, directed=True, indices=sources, return_predecessors=True, min_only=True)
    d_t, pred_t, _ = csgraph.dijkstra(forward.T.tocsr(), directed=True, indices=targets, return_predecessors=True,
                                      min_only=True)
    total = d_s[pre] + weight + d_t[post]
    finite = np.flatnonzero(np.isfinite(total))
    if not len(finite):
        return [], 0
    paths, seen = [], set()
    for chunk in (min(len(finite), 4000), len(finite)):
        part = finite[np.argpartition(total[finite], chunk - 1)[:chunk]] if chunk < len(finite) else finite
        for e in part[np.argsort(total[part], kind="stable")]:
            nodes = _walk(pred_s, int(pre[e]))[::-1] + _walk(pred_t, int(post[e]))
            key = tuple(nodes)
            if key in seen or len(set(nodes)) != len(nodes) or len(nodes) - 1 > max_hops:
                seen.add(key)
                continue
            seen.add(key)
            paths.append((float(total[e]), nodes))
            if len(paths) >= limit:
                return paths, len(finite)
        if chunk == len(finite):
            break
    return paths, len(finite)


def paths(graph: Graph, source: str, target: str, mode: str = "strongest", level: str = "cell_type",
          threshold: int = 5, limit: int = 10, max_hops: int = 10, source_side: str = "both",
          target_side: str = "both", other_transmitters: str = "excluded", running=None) -> dict:
    """Shortest or strongest paths from the source to the target, between cell types or between neurons."""
    _check_threshold(threshold)
    if mode not in ("shortest", "strongest") or level not in ("cell_type", "neuron"):
        raise ExploreError("mode is shortest or strongest; level is cell_type or neuron.")
    if not 1 <= limit <= 50 or not 1 <= max_hops <= 20:
        raise ExploreError("Choose 1-50 paths and 1-20 steps.")
    src, src_labels = graph.resolve(source, source_side)
    dst, dst_labels = graph.resolve(target, target_side)
    layer = graph.layer(threshold)
    signs = graph.signs(other_transmitters)
    rows = []
    if level == "cell_type":
        if source_side != "both" or target_side != "both":
            raise ExploreError("Sides apply to neuron-level paths; cell-type paths join whole types.")
        t_pre, t_post, syn, signed, incoming = _type_graph(graph, layer)
        loops = t_pre != t_post
        t_pre, t_post, syn, net = t_pre[loops], t_post[loops], syn[loops], signed[other_transmitters][loops]
        fraction = syn / incoming[t_post]
        sources, targets = np.unique(graph.type_index[src]), np.unique(graph.type_index[dst])
        if np.intersect1d(sources, targets).size:
            raise ExploreError("The source and the target share a cell type; choose different ones.")
        found, reachable = _best_paths(t_pre, t_post, _weights(fraction, mode), len(graph.type_names), sources,
                                       targets, limit, max_hops)
        lookup_edge = {(int(a), int(b)): k for k, (a, b) in enumerate(zip(t_pre, t_post))}
        for _, nodes in found:
            steps = [lookup_edge[(a, b)] for a, b in zip(nodes, nodes[1:])]
            names = [str(graph.type_names[t]) for t in nodes]
            rows.append({"cell_types": names, "steps": len(steps),
                         "strength": float(np.prod(fraction[steps])),
                         "net_sign": int(np.prod(np.sign(net[steps]))),
                         "edges": [{"synapses": int(syn[k]), "fraction": float(fraction[k]), "sign": int(np.sign(net[k]))}
                                   for k in steps],
                         "in_running_circuit": [_in_running(running, name) for name in names]})
    else:
        if np.intersect1d(src, dst).size:
            raise ExploreError("The source and the target share neurons; choose different ones.")
        keep = layer.pre != layer.post
        pre, post, syn = layer.pre[keep], layer.post[keep], layer.syn[keep]
        fraction = syn / layer.in_total[post]
        found, reachable = _best_paths(pre, post, _weights(fraction, mode), len(graph.ids), src, dst, limit, max_hops)
        for _, nodes in found:
            f = [layer.into[b, a] / layer.in_total[b] for a, b in zip(nodes, nodes[1:])]
            s = [int(signs[a]) for a in nodes[:-1]]
            neurons = [graph.neuron(i) for i in nodes]
            rows.append({"neurons": neurons, "cell_types": [n["cell_type"] for n in neurons], "steps": len(f),
                         "strength": float(np.prod(f)), "net_sign": int(np.prod(s)),
                         "edges": [{"synapses": int(layer.into[b, a]), "fraction": float(x), "sign": sg}
                                   for a, b, x, sg in zip(nodes, nodes[1:], f, s)],
                         "in_running_circuit": [_in_running(running, n["cell_type"]) for n in neurons]})
    return {
        "graph": graph.key, "source": src_labels, "target": dst_labels, "mode": mode, "level": level,
        "threshold": threshold, "max_hops": max_hops, "paths": rows, "connected": bool(rows),
        "candidate_connections": int(reachable), "running_circuit": running and running["circuit"],
        "rule": (f"Connections of at least {threshold} synapses. Step strength f: synapses onto the next "
                 f"{'cell type' if level == 'cell_type' else 'neuron'} ÷ all its input synapses; a path's strength "
                 "multiplies its steps. "
                 + ("Strongest: the largest product (Dijkstra on −ln f). " if mode == "strongest" else
                    "Shortest: the fewest steps, ties broken by strength. ")
                 + "The first path is the optimum; the others are the best path through each other connection. "
                 + SIGN_RULE.format(other="+1" if other_transmitters == "excitatory" else "0 (excluded)")
                 + " Net sign multiplies the steps' signs."),
    }


# ---------------------------------------------------------------------------------------------------- influence

def _leading_real(matrix) -> float:
    """The largest real part of a sparse matrix's eigenvalues (deterministic start vector)."""
    n = matrix.shape[0]
    if n <= 600:
        return float(np.linalg.eigvals(matrix.toarray()).real.max())
    values = sparse_linalg.eigs(matrix, k=1, which="LR", v0=np.ones(n), tol=1e-6, return_eigenvectors=False,
                                maxiter=n * 10)
    return float(values.real.max())


def _spectral_radius(matrix) -> float:
    n = matrix.shape[0]
    if n <= 600:
        return float(np.abs(np.linalg.eigvals(matrix.toarray())).max())
    values = sparse_linalg.eigs(matrix, k=1, which="LM", v0=np.ones(n), tol=1e-6, return_eigenvectors=False,
                                maxiter=n * 10)
    return float(np.abs(values).max())


def _operator(graph: Graph, layer: Layer, signed: bool, other_transmitters: str):
    def build():
        n = len(graph.ids)
        weight = (graph.signs(other_transmitters)[layer.pre] if signed else 1.0) * layer.syn
        nz = weight != 0
        w = sparse.csr_matrix((weight[nz], (layer.post[nz], layer.pre[nz])), shape=(n, n))  # rows post, columns pre
        rule, lam = "largest real eigenvalue", _leading_real(w) if w.nnz else 0.0
        if not lam > 1e-9:
            rule, lam = "spectral radius of |W| (W has no positive real eigenvalue)", _spectral_radius(abs(w)) if w.nnz else 0.0
        if not lam > 1e-9:
            rule, lam = "largest row sum of |W| (W is nilpotent: an acyclic graph)", float(abs(w).sum(axis=1).max()) if w.nnz else 1.0
        system = (sparse.identity(n, format="csr") - w * (SPECTRAL_TARGET / lam)).tocsr()
        return {"system": system, "transposed": system.T.tocsr(), "lambda": lam, "rule": rule, "weights": int(w.nnz)}
    return layer.cached(("influence", signed, other_transmitters), build)


def _solve(matrix, rhs):
    if matrix.shape[0] <= 5000:
        x = sparse_linalg.spsolve(matrix.tocsc(), rhs)
        method = "direct (SuperLU)"
    else:
        x, info = sparse_linalg.bicgstab(matrix, rhs, rtol=1e-9, maxiter=5000)
        method = "BiCGSTAB"
        if info != 0:
            x, info = sparse_linalg.gmres(matrix, rhs, rtol=1e-9, restart=200, maxiter=200)
            method = "GMRES (BiCGSTAB did not converge)"
            if info != 0:
                raise ExploreError("The influence solver did not converge for this query.")
    residual = float(np.linalg.norm(matrix @ x - rhs) / max(np.linalg.norm(rhs), TINY))
    return np.asarray(x, dtype=np.float64), method, residual


def influence(graph: Graph, query: str, direction: str = "from", group: str = "cell_type", side: str = "both",
              threshold: int = 5, limit: int = 50, signed: bool = True, other_transmitters: str = "excluded",
              running=None) -> dict:
    """Steady-state influence of stimulating the query neurons (from), or of each neuron on the query (onto)."""
    _check_threshold(threshold)
    if direction not in ("from", "onto") or group not in ("cell_type", "neuron"):
        raise ExploreError("direction is from or onto; group is cell_type or neuron.")
    neurons, labels = graph.resolve(query, side)
    layer = graph.layer(threshold)
    op = _operator(graph, layer, signed, other_transmitters)
    rhs = np.zeros(len(graph.ids))
    rhs[neurons] = 1.0
    x, method, residual = _solve(op["system"] if direction == "from" else op["transposed"], rhs)
    x[np.abs(x) < 1e-12 * max(np.abs(x).max(), TINY)] = 0.0  # round-off, as BANC's notes advise
    seed = np.zeros(len(graph.ids), dtype=bool)
    seed[neurons] = True
    shown = np.where(seed, 0.0, x)  # the query neurons themselves are listed apart
    rows = []
    if group == "cell_type":
        n_types = len(graph.type_names)
        total = np.bincount(graph.type_index, weights=shown, minlength=n_types)
        reached = np.bincount(graph.type_index, weights=shown != 0, minlength=n_types)
        left = np.bincount(graph.type_index, weights=shown * (graph.side == "left"), minlength=n_types)
        right = np.bincount(graph.type_index, weights=shown * (graph.side == "right"), minlength=n_types)
        order = np.argsort(-np.abs(total), kind="stable")
        for t in order[:limit]:
            if total[t] == 0:
                break
            name = str(graph.type_names[t])
            rows.append({"cell_type": name, "influence": float(total[t]), "log10": float(math.log10(abs(total[t]))),
                         "sign": int(np.sign(total[t])), "left": float(left[t]), "right": float(right[t]),
                         "neurons": int(graph.type_counts[t]), "reached": int(reached[t]),
                         "super_class": _mode(graph.super_class[graph.type_members(int(t))]),
                         "in_running_circuit": _in_running(running, name)})
        counted = int((total != 0).sum())
    else:
        order = np.argsort(-np.abs(shown), kind="stable")
        for i in order[:limit]:
            if shown[i] == 0:
                break
            info = graph.neuron(int(i))
            rows.append({**info, "influence": float(shown[i]), "log10": float(math.log10(abs(shown[i]))),
                         "sign": int(np.sign(shown[i])), "in_running_circuit": _in_running(running, info["cell_type"])})
        counted = int((shown != 0).sum())
    return {
        "graph": graph.key, "query": labels, "side": side, "direction": direction, "group": group,
        "threshold": threshold, "signed": signed, "query_neurons": int(len(neurons)),
        "query_self": float(x[neurons].sum()), "rows": rows, "nonzero": counted,
        "neurons_reached": int((shown != 0).sum()), "running_circuit": running and running["circuit"],
        "model": {"lambda": op["lambda"], "scale_rule": op["rule"], "spectral_target": SPECTRAL_TARGET,
                  "weights": op["weights"], "solver": method, "relative_residual": residual},
        "rule": ("Linear steady state r = (I − W̃)⁻¹ s, after the BANC ConnectomeInfluenceCalculator: W = "
                 + ("signed " if signed else "unsigned ") + f"synapse counts of connections of at least {threshold} "
                 f"synapses, W̃ = {SPECTRAL_TARGET} W ÷ λ ({op['rule']}), s = 1 on the query neurons. "
                 + ("Each row sums r over its neurons (the query neurons excluded)." if direction == "from" else
                    "Each row is the influence on the query neurons, summed, of stimulating the row's neurons.")
                 + (" " + SIGN_RULE.format(other="+1" if other_transmitters == "excitatory" else "0 (excluded)")
                    if signed else " Unsigned: every connection counts as excitatory.")
                 + " A linear approximation: no rectification, thresholds or simulated dynamics."),
    }


# -------------------------------------------------------------------------------------------------- neuroglancer

def neuroglancer(graph: Graph | None, groups: list[dict], title: str = "DigitalFly selection",
                 limit: int = 5000) -> dict:
    """A Neuroglancer link showing groups of FlyWire v783 neurons, one coloured layer per group.

    Each group is {label, ids: [root IDs]} or {label, cell_type, side}, with an optional colour. The neurons stream
    from FlyWire's public segmentation; nothing is downloaded until Neuroglancer draws them.
    """
    if not 1 <= limit <= NG_SEGMENT_LIMIT:
        raise ExploreError(f"Choose a limit of 1-{NG_SEGMENT_LIMIT} neurons.")
    if not groups:
        raise ExploreError("Give at least one group of neurons.")
    if graph is not None and (graph.provenance.get("release") not in ("v783", None)
                              or graph.provenance.get("dataset") not in ("FlyWire FAFB", None)):
        raise ExploreError(f"{graph.title} is not FlyWire v783 data, so its IDs are not in the public segmentation.")
    layers = [{"type": "image", "source": NG_SOURCES["em"], "name": "FAFB EM", "visible": False},
              {"type": "segmentation", "source": NG_SOURCES["brain_mesh"], "name": "brain outline", "segments": ["1"],
               "objectAlpha": 0.08, "segmentColors": {"1": "#9e9e9e"}, "pick": False}]
    used, summary, truncated = 0, [], False
    for k, group in enumerate(groups):
        if group.get("ids") is not None:
            ids = []
            for value in group["ids"]:
                text = str(value).strip()
                if not text.isdigit():
                    raise ExploreError(f"{text!r} is not a FlyWire root ID.")
                ids.append(text)
            ids = list(dict.fromkeys(ids))
        elif group.get("cell_type") and graph is not None:
            members, _ = graph.resolve(group["cell_type"], group.get("side") or "both")
            ids = [str(graph.ids[i]) for i in members]
        else:
            raise ExploreError("Each group needs ids or a cell_type.")
        room = max(0, limit - used)
        if len(ids) > room:
            truncated, ids = True, ids[:room]
        used += len(ids)
        color = group.get("color") or NG_COLORS[k % len(NG_COLORS)]
        label = str(group.get("label") or group.get("cell_type") or f"group {k + 1}")[:80]
        summary.append({"label": label, "neurons": len(ids), "color": color})
        if ids:
            layers.append({"type": "segmentation",
                           "source": {"url": NG_SOURCES["segmentation"], "subsources": {"default": True, "mesh": True},
                                      "enableDefaultSubsources": False},
                           "name": label, "segments": ids, "segmentDefaultColor": color})
    state = {"title": title[:120],
             "dimensions": {"x": [4e-9, "m"], "y": [4e-9, "m"], "z": [4e-8, "m"]},
             "position": [130261.5, 55609.5, 930.5], "crossSectionScale": 1.2, "projectionScale": 105858.85,
             "layers": layers, "showSlices": False, "layout": "3d", "selectedLayer": {"visible": False}}
    url = f"{NEUROGLANCER}/#!" + urllib.parse.quote(json.dumps(state, separators=(",", ":")), safe="")
    return {"url": url, "state": state, "neurons": used, "truncated": truncated, "groups": summary,
            "host": NEUROGLANCER, "sources": NG_SOURCES, "url_length": len(url),
            "note": ("Neuroglancer streams the FlyWire v783 meshes from public Google Cloud buckets when you open the "
                     "link. " + LICENSE + "; cite " + ATTRIBUTION + ".")}


def circuit_groups(graph: Graph) -> list[dict]:
    """A circuit's neurons for Neuroglancer: its seed neurons, then every other neuron."""
    seeds = []
    data = load_circuit(graph.key)
    for record in data.seeds:
        seeds += record.get("left", []) + record.get("right", []) + record.get("other", [])
    seeds = list(dict.fromkeys(seeds))
    chosen = set(seeds)
    rest = [str(i) for i in graph.ids if str(i) not in chosen]
    return [{"label": "seeds: " + ", ".join(r["seed"] for r in data.seeds)[:60], "ids": seeds, "color": "#e6550d"},
            {"label": f"{graph.key} (other neurons)", "ids": rest, "color": "#3182bd"}]


# ------------------------------------------------------------------------------------------------ API requests

GraphKey = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


class NeuroglancerGroup(StrictModel):
    label: str | None = Field(default=None, max_length=80)
    ids: list[Annotated[str, Field(pattern=r"^\d{1,20}$")]] | None = Field(default=None, max_length=NG_SEGMENT_LIMIT)
    cell_type: str | None = Field(default=None, min_length=1, max_length=2000)
    side: Literal["both", "left", "right"] = "both"
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class NeuroglancerRequest(StrictModel):
    """Neurons to show in Neuroglancer: groups of root IDs or cell types in `graph`, or a whole circuit."""
    graph: GraphKey = BRAIN
    groups: list[NeuroglancerGroup] = Field(default_factory=list, max_length=20)
    circuit: GraphKey | None = None  # every neuron of this circuit (its seeds as their own group); groups are added
    title: str = Field(default="DigitalFly selection", max_length=120)
    limit: int = Field(default=5000, ge=1, le=NG_SEGMENT_LIMIT)


def neuroglancer_request(request: NeuroglancerRequest) -> dict:
    """A link for the request: cell-type groups resolve in `graph`; groups of IDs need no data on this computer."""
    groups = [g.model_dump(exclude_none=True) for g in request.groups]
    graph = None
    if request.circuit is not None:
        graph = load_graph(request.circuit)
        groups = circuit_groups(graph) + groups
    if any("ids" not in g for g in groups):
        graph = load_graph(request.graph)
    return neuroglancer(graph, groups, request.title, request.limit)
