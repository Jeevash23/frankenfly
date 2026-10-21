"""Local run records and bounded, provenance-preserving connectivity exploration."""
import csv
from functools import lru_cache
import hashlib
import json
import math
import re
import shutil
import uuid
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from digitalfly.api.models import StrictModel
from digitalfly.simulation.engines import ROOT

RUN_KEY = re.compile(r"\d{8}T\d{6}-[a-f0-9]{8}-[a-f0-9]{6}")


def run_detail(key: str, root: Path | None = None, include_trajectory=True):
    """A saved run's summary and decimated trajectory; metadata schemas 2-4 share every field read here."""
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
        points = (_point(row) for i, row in enumerate(rows) if i % interval == 0 or i == len(rows)-1)
        trajectory = [point for point in points if point is not None]
    return {"key": key, "run_id": meta["run_id"], "created_utc": meta["created_utc"],
        "config": meta["initial_config"], "samples": meta["recorded_samples"],
        "metrics": meta.get("metrics", {}), "trial": meta.get("trial"),
        "error": meta.get("error"), "provenance": meta["provenance"], "verified": verification(directory),
        "trajectory": trajectory, "download_url": f"/api/exports/{key}.zip"}


def _point(row):
    """A trajectory point, or None for a damaged row (missing or non-finite values), which is left out."""
    try:
        point = [float(row[k]) for k in ["time_s", "x_mm", "y_mm", "speed_mm_s"]]
    except (KeyError, TypeError, ValueError):
        return None
    return point if all(math.isfinite(value) for value in point) else None


VERDICT_FIELDS = ("ok", "max_abs_error", "tolerance", "checked", "same_software", "message")


def verification(directory: Path) -> dict | None:
    """The latest replay check's verdict (replay.json, written by scripts/replay.py --save), or None."""
    path = directory / "replay.json"
    try:
        stat = path.lstat()
    except OSError:
        return None
    return _verdict(str(path), stat.st_mtime_ns, stat.st_size) if path.is_file() and not path.is_symlink() else None


@lru_cache(maxsize=2048)
def _verdict(path: str, mtime_ns: int, size: int):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or any(field not in data for field in VERDICT_FIELDS):
        return None
    return data


@lru_cache(maxsize=2048)
def _run_summary(directory: str, mtime_ns: int, size: int):
    # Keyed by the metadata file's identity: saved runs never change, and listing re-reads none of them.
    path = Path(directory)
    item = run_detail(path.name, path.parent, include_trajectory=False)
    item.pop("trajectory")
    return item


def list_runs(root: Path | None = None, include_empty=True) -> list[dict]:
    """Every readable saved run, newest first (run identifiers start with the run's UTC start time).
    Hidden folders, such as exports still being written, are never listed. include_empty=False leaves out
    runs with at most one sample (exported straight after a reset)."""
    root = root or ROOT / "runs"
    records = []
    if root.is_dir():
        for path in sorted(root.iterdir(), reverse=True):
            if not RUN_KEY.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
                continue
            try:
                stat = (path / "metadata.json").stat()
                item = _run_summary(str(path), stat.st_mtime_ns, stat.st_size)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if include_empty or item["samples"] > 1:
                records.append({**item, "verified": verification(path)})  # replay.json changes; the metadata never does
    return records


def delete_run(key: str, root: Path | None = None):
    """Delete a saved run's folder and its ZIP. The folder is renamed to a hidden name first, so a deletion
    that is interrupted never leaves a partial run in the library. Links are never followed."""
    if not RUN_KEY.fullmatch(key):
        raise ValueError("Unknown run identifier.")
    root = root or ROOT / "runs"
    directory, archive = root / key, root / f"{key}.zip"
    if directory.is_symlink() or archive.is_symlink() or not (directory.is_dir() or archive.is_file()):
        raise FileNotFoundError("Saved run not found.")
    if directory.is_dir():
        trash = root / f".deleting-{key}-{uuid.uuid4().hex[:6]}"
        directory.rename(trash)
        shutil.rmtree(trash)
    archive.unlink(missing_ok=True)
    return {"deleted": key}


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


@lru_cache(maxsize=1024)
def _graph_entry(directory: str, key: str, mtime_ns: int):
    data = load_graph(key)
    return {"key": data["key"], "provenance": data["graph"]["provenance"], "summary": data["summary"]}


def list_graphs() -> list[dict]:
    """Every readable imported graph, most recently imported first."""
    directory = ROOT / "data/connectivity"
    result = []
    if directory.is_dir():
        files = []
        for path in directory.glob("*.json"):
            try:
                files.append((path.stat().st_mtime_ns, path))
            except OSError:
                continue
        for mtime_ns, path in sorted(files, key=lambda item: (-item[0], item[1].name)):
            try:
                result.append(_graph_entry(str(directory), path.stem, mtime_ns))
            except (OSError, ValueError):
                continue
    return result
