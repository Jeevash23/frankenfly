"""Local run records and bounded, provenance-preserving connectivity exploration."""
import csv
from functools import lru_cache
import hashlib
import io
import json
import math
import os
import re
import shutil
from threading import Lock
import uuid
from pathlib import Path
from typing import Annotated, Literal
import numpy as np
from pydantic import Field, field_validator, model_validator
from digitalfly.api.models import DEFAULT_CIRCUIT, RunConfig, RunMetrics, StrictModel, TrialRecord
from digitalfly.simulation.engines import ROOT
from digitalfly.toolkit import REACH_MM, summarize

RUN_KEY = re.compile(r"\d{8}T\d{6}-[a-f0-9]{8}-[a-f0-9]{6}")
BATCH_ID = r"^[A-Za-z0-9_-]{1,64}$"
ANNOTATIONS = "annotations.json"
SUMMARY_METRICS = ("target_distance_mm", "path_length_mm", "net_turn_deg", "mean_speed_mm_s")
Tag = Annotated[str, Field(pattern=r"^[A-Za-z0-9 _-]{1,24}$")]
_annotating = Lock()


class RunAnnotations(StrictModel):
    """A researcher's tags and notes on a saved run, kept in its annotations.json; metadata.json never changes.
    As a PATCH body, only the fields given are changed."""
    tags: list[Tag] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=2000)

    @field_validator("tags")
    @classmethod
    def distinct_tags(cls, tags):
        tags = [tag.strip() for tag in tags]
        if not all(tags):
            raise ValueError("A tag needs a letter, a digit, '_' or '-'.")
        if len({tag.lower() for tag in tags}) != len(tags):
            raise ValueError("List each tag once.")
        return tags


class ReplayVerdict(StrictModel):
    """The latest replay check of a saved run (its replay.json)."""
    ok: bool
    max_abs_error: float
    tolerance: float
    checked: str
    same_software: bool
    message: str


class RunItem(StrictModel):
    """A saved run in the library. Older runs may lack configuration fields and metrics added since."""
    key: str
    run_id: str
    created_utc: str
    config: RunConfig
    samples: int
    metrics: RunMetrics
    trial: TrialRecord | None
    error: str | None
    provenance: dict[str, str]
    download_url: str
    batch_id: str | None
    condition: str | None
    tags: list[str]
    notes: str
    verified: ReplayVerdict | None


class RunPage(StrictModel):
    runs: list[RunItem]


class MetricSummary(StrictModel):
    mean: float | None
    sd: float | None  # sample standard deviation; None below two trials
    ci95: tuple[float, float] | None  # bootstrap for means, Wilson for reached; None below two trials (n = 0 for reached)


class ConditionSummary(StrictModel):
    condition: str
    n: int
    metrics: dict[str, MetricSummary]


class PairedDifference(StrictModel):
    condition: str
    baseline: str
    metric: str
    mean_diff: float | None
    ci95: tuple[float, float] | None
    n_pairs: int


class BatchSummary(StrictModel):
    batch_id: str
    n_trials: int
    partial_trials: int  # saved unfinished (cancelled or failed) and left out
    reach_mm: float
    conditions: list[ConditionSummary]
    paired: list[PairedDifference]
    methods: dict[str, str]


def _read_run(directory: Path) -> dict:
    # Metadata schemas 2-5 share every field read here.
    meta = json.loads((directory / "metadata.json").read_text())
    trial = meta.get("trial")
    return {"key": directory.name, "run_id": meta["run_id"], "created_utc": meta["created_utc"],
        "config": meta["initial_config"], "samples": meta["recorded_samples"],
        "metrics": meta.get("metrics", {}), "trial": trial,
        "error": meta.get("error"), "provenance": meta["provenance"], "download_url": f"/api/exports/{directory.name}.zip",
        "batch_id": trial.get("batch_id") if trial else None, "condition": trial.get("condition") if trial else None}


@lru_cache(maxsize=2048)
def _run_summary(directory: str, mtime_ns: int, size: int):
    # Keyed by the metadata file's identity: saved runs never change, and listing re-reads none of them.
    return _read_run(Path(directory))


@lru_cache(maxsize=2048)
def _annotations(path: str, mtime_ns: int, size: int, inode: int) -> dict:
    try:
        return RunAnnotations.model_validate_json(Path(path).read_bytes()).model_dump()
    except (OSError, ValueError):
        return RunAnnotations().model_dump()  # unreadable notes never hide the run


def annotations(directory: Path) -> dict:
    """A saved run's tags and notes; none when it has no annotations.json (or only a link by that name)."""
    path = directory / ANNOTATIONS
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return RunAnnotations().model_dump()
    if path.is_symlink():
        return RunAnnotations().model_dump()
    return _annotations(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino)


def _run_directory(key: str, root: Path | None) -> Path:
    if not RUN_KEY.fullmatch(key):
        raise ValueError("Unknown run identifier.")
    directory = (root or ROOT / "runs") / key
    if directory.is_symlink() or not (directory / "metadata.json").is_file():
        raise ValueError("Saved run not found.")
    return directory


def run_detail(key: str, root: Path | None = None, include_trajectory=True):
    """A saved run's library entry and decimated trajectory ([time_s, x_mm, y_mm, speed_mm_s], about 400 points)."""
    directory = _run_directory(key, root)
    trajectory = []
    csv_path = directory / "telemetry.csv"
    if include_trajectory and csv_path.is_file():
        with csv_path.open() as file:
            rows = list(csv.DictReader(file))[:30000]
        interval = max(1, len(rows)//400)
        points = (_point(row) for i, row in enumerate(rows) if i % interval == 0 or i == len(rows)-1)
        trajectory = [point for point in points if point is not None]
    return {**_entry(directory, _read_run(directory)), "trajectory": trajectory}


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


def _entry(directory: Path, summary: dict) -> dict:
    """A library entry: the run's summary, which never changes, with its tags, notes and replay verdict, which can."""
    return {**summary, **annotations(directory), "verified": verification(directory)}


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
                item = _entry(path, _run_summary(str(path), stat.st_mtime_ns, stat.st_size))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
            if include_empty or item["samples"] > 1:
                records.append(item)
    return records


def filter_runs(runs: list[dict], model: str | None = None, circuit: str | None = None, batch: str | None = None,
                tag: str | None = None, q: str | None = None) -> list[dict]:
    """The runs matching every filter given: the neural model; the circuit (connectome runs only); the comparison;
    a tag (ignoring case); text found, ignoring case, in the run identifier, notes or condition."""
    def keep(run):
        config = run["config"]
        connectome = config.get("neural_model") in ("connectome", "connectome_dna02")  # the v0.3 name too
        if model is not None and (model == "connectome") != connectome:
            return False
        if circuit is not None and not (connectome and (config.get("connectome_parameters") or {}).get(
                "circuit", DEFAULT_CIRCUIT) == circuit):
            return False
        if batch is not None and run["batch_id"] != batch:
            return False
        if tag is not None and tag.strip().lower() not in {t.lower() for t in run["tags"]}:
            return False
        return q is None or any(q.lower() in (text or "").lower()
                                for text in (run["key"], run["notes"], run["condition"]))
    return [run for run in runs if keep(run)]


def annotate_run(key: str, change: RunAnnotations, root: Path | None = None) -> dict:
    """Set the tags and notes given in `change` on a saved run and return its library entry. annotations.json is
    replaced atomically (never written through a link), and metadata.json is never touched."""
    directory = _run_directory(key, root)
    with _annotating:
        updated = RunAnnotations.model_validate({**annotations(directory), **change.model_dump(include=change.model_fields_set)})
        staged = directory / f".{ANNOTATIONS}.{uuid.uuid4().hex[:6]}.tmp"
        try:
            staged.write_text(updated.model_dump_json(indent=2))
            os.replace(staged, directory / ANNOTATIONS)
        finally:
            staged.unlink(missing_ok=True)
    return _entry(directory, _read_run(directory))


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


def _sd(values) -> float | None:
    return float(np.std(values, ddof=1)) if len(values) > 1 else None


def batch_summary(batch_id: str, root: Path | None = None) -> dict:
    """A comparison's saved trials, per condition: mean, SD and 95% interval of each metric, and differences from
    the first condition over trials with the same seed, with the toolkit's statistics (toolkit.summarize). Reached
    (closest approach within the toolkit's REACH_MM) needs metrics.min_target_distance_mm, saved since v0.6. Trials
    saved unfinished (cancelled or failed) are left out and counted."""
    runs = [run for run in list_runs(root) if run["batch_id"] == batch_id]
    if not runs:
        raise FileNotFoundError("No saved trials belong to this comparison.")
    partial = [run for run in runs if run["trial"].get("partial")]
    trials = sorted((run for run in runs if not run["trial"].get("partial")),
                    key=lambda run: (run["trial"].get("index") or 0, run["key"]))
    reached = bool(trials) and all(run["metrics"].get("min_target_distance_mm") is not None for run in trials)
    rows = []
    for run in trials:
        stimulus, metrics = run["config"].get("stimulus") or {}, run["metrics"]
        rows.append({"condition": str(run["condition"]), "seed": run["trial"].get("seed"), "error": run["error"],
                     "target_bearing_deg": math.degrees(math.atan2(stimulus.get("y", 0), stimulus.get("x", 1))),
                     "first_turn_toward": None,
                     "reached": metrics["min_target_distance_mm"] <= REACH_MM if reached else None,
                     **{name: metrics.get(name) for name in SUMMARY_METRICS}})
    stats = summarize(rows, by=["condition"], match=("seed",), metrics=SUMMARY_METRICS)
    names = SUMMARY_METRICS + ("reached",) * reached
    conditions = []
    for item in stats["conditions"]:
        ok = [row for row in rows if row["condition"] == item["condition"]["condition"] and not row["error"]]
        summary = {name: {"mean": item[name]["mean"], "sd": _sd([row[name] for row in ok if row[name] is not None]),
                          "ci95": item[name]["ci95"]} for name in SUMMARY_METRICS}
        if reached:
            summary["reached"] = {"mean": item["reached_fraction"], "sd": _sd([float(row["reached"]) for row in ok]),
                                  "ci95": item["reached_ci95"]}
        conditions.append({"condition": item["condition"]["condition"], "n": len(ok), "metrics": summary})
    paired = [{"condition": item["condition"]["condition"], "baseline": item["baseline"]["condition"], "metric": name,
               "mean_diff": item[name]["mean_difference"], "ci95": item[name]["ci95"], "n_pairs": item["pairs"]}
              for item in stats["paired_differences"] for name in names]
    return {"batch_id": batch_id, "n_trials": len(trials), "partial_trials": len(partial), "reach_mm": REACH_MM,
            "conditions": conditions, "paired": paired,
            "methods": {**stats["methods"], "sd": "sample standard deviation (n − 1)",
                        "reached": f"closest approach to the target within {REACH_MM:g} mm "
                                   "(metrics.min_target_distance_mm); left out when a trial predates it"}}


def batch_summary_csv(summary: dict) -> str:
    """batch_summary as one table: a row per condition and metric, then a row per paired difference."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["kind", "condition", "baseline", "metric", "n", "mean", "sd", "ci95_low", "ci95_high"])
    for item in summary["conditions"]:
        for name, value in item["metrics"].items():
            writer.writerow(["condition", item["condition"], "", name, item["n"], value["mean"], value["sd"],
                             *(value["ci95"] or ["", ""])])
    for item in summary["paired"]:
        writer.writerow(["paired", item["condition"], item["baseline"], item["metric"], item["n_pairs"],
                         item["mean_diff"], "", *(item["ci95"] or ["", ""])])
    return output.getvalue()


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
