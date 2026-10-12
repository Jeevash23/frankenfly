"""Local run records and bounded, provenance-preserving connectivity exploration."""
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from digitalfly.api.models import StrictModel
from digitalfly.simulation.engines import ROOT

RUN_KEY = re.compile(r"\d{8}T\d{6}-[a-f0-9]{8}-[a-f0-9]{6}")


def run_detail(key: str, root: Path | None = None, include_trajectory=True):
    if not RUN_KEY.fullmatch(key):
        raise ValueError("Unknown run identifier.")
    directory = (root or ROOT / "runs") / key
    if directory.is_symlink() or not (directory / "metadata.json").is_file():
        raise ValueError("Saved run not found.")
    meta = json.loads((directory / "metadata.json").read_text())
    trajectory = []
    csv_path = directory / "telemetry.csv"
    if include_trajectory and csv_path.is_file():
        with csv_path.open() as file:
            rows = list(csv.DictReader(file))[:30000]
        interval = max(1, len(rows)//400)
        trajectory = [[float(row[k]) for k in ["time_s", "x_mm", "y_mm", "speed_mm_s"]]
                      for i, row in enumerate(rows) if i % interval == 0 or i == len(rows)-1]
    return {"key": key, "run_id": meta["run_id"], "created_utc": meta["created_utc"],
        "config": meta["initial_config"], "samples": meta["recorded_samples"],
        "metrics": meta.get("metrics", {}), "trial": meta.get("trial"),
        "error": meta.get("error"), "provenance": meta["provenance"],
        "trajectory": trajectory, "download_url": f"/api/exports/{key}.zip"}


def list_runs(root: Path | None = None):
    root = root or ROOT / "runs"
    records = []
    if root.exists():
        for path in sorted(root.iterdir(), reverse=True):
            if not path.is_dir() or not RUN_KEY.fullmatch(path.name):
                continue
            try:
                item = run_detail(path.name, root, include_trajectory=False)
                item.pop("trajectory")
                records.append(item)
            except (OSError, ValueError, KeyError):
                continue
            if len(records) == 100:
                break
    return records


class GraphSource(StrictModel):
    kind: Literal["biological", "synthetic"]
    dataset: str = Field(min_length=1, max_length=120)
    release: str = Field(min_length=1, max_length=80)
    specimen: str = Field(min_length=1, max_length=120)
    sex: Literal["female", "male", "unknown", "mixed"]
    source_url: str = Field(pattern=r"^https?://", max_length=1000)
    license: str = Field(min_length=1, max_length=160)
    coverage: str = Field(min_length=1, max_length=500)
    weight_assumption: str = Field(min_length=1, max_length=500)


class GraphNode(StrictModel):
    id: str = Field(strict=True, min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    cell_type: str = Field(default="unknown", max_length=120)
    side: Literal["left", "right", "midline", "unknown"] = "unknown"


class GraphEdge(StrictModel):
    pre_id: str = Field(strict=True, min_length=1, max_length=80)
    post_id: str = Field(strict=True, min_length=1, max_length=80)
    synapse_count: int = Field(ge=1, le=100000000)


class ConnectivityGraph(StrictModel):
    provenance: GraphSource
    nodes: list[GraphNode] = Field(min_length=1, max_length=300)
    edges: list[GraphEdge] = Field(max_length=3000)

    @model_validator(mode="after")
    def valid_graph(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Neuron identifiers must be unique.")
        pairs = [(e.pre_id, e.post_id) for e in self.edges]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Combine duplicate directed edges before importing.")
        if any(a not in ids or b not in ids for a, b in pairs):
            raise ValueError("Every edge endpoint must have a node record.")
        return self


def graph_summary(graph: ConnectivityGraph):
    incoming = {n.id: 0 for n in graph.nodes}
    outgoing = dict(incoming)
    pairs = set()
    for edge in graph.edges:
        incoming[edge.post_id] += edge.synapse_count
        outgoing[edge.pre_id] += edge.synapse_count
        pairs.add((edge.pre_id, edge.post_id))
    return {"nodes": len(graph.nodes), "edges": len(graph.edges),
        "synapses": sum(e.synapse_count for e in graph.edges),
        "reciprocal_pairs": sum(a != b and (b, a) in pairs for a, b in pairs)//2,
        "incoming_synapses": incoming, "outgoing_synapses": outgoing,
        "interpretation": "Structural counts within this subset; counts are not physiological weights. No coupling to the walking controller."}


def save_graph(graph: ConnectivityGraph):
    content = graph.model_dump_json()
    key = hashlib.sha256(content.encode()).hexdigest()[:20]
    directory = ROOT / "data/connectivity"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{key}.json").write_text(content)
    return {"key": key, "graph": graph.model_dump(), "summary": graph_summary(graph)}


def load_graph(key: str):
    if not re.fullmatch(r"[a-f0-9]{20}", key):
        raise ValueError("Unknown connectivity identifier.")
    path = ROOT / "data/connectivity" / f"{key}.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Connectivity file not found.")
    graph = ConnectivityGraph.model_validate_json(path.read_text())
    return {"key": key, "graph": graph.model_dump(), "summary": graph_summary(graph)}


def list_graphs():
    directory = ROOT / "data/connectivity"
    result = []
    if directory.exists():
        for path in sorted(directory.glob("*.json"))[:100]:
            try:
                data = load_graph(path.stem)
                result.append({"key": data["key"], "provenance": data["graph"]["provenance"], "summary": data["summary"]})
            except (OSError, ValueError):
                continue
    return result
