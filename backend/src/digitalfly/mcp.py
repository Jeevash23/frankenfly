"""An MCP server for DigitalFly: agents such as Claude Code drive a running app through its local API.

    ./scripts/setup.sh --with mcp                        # the official MCP Python SDK, from a hashed lock
    ./scripts/start.sh                                   # the app, at http://127.0.0.1:8000
    claude mcp add digitalfly -- /path/to/frankenfly/backend/.venv/bin/python /path/to/frankenfly/scripts/mcp.py

Every tool goes through `digitalfly.client.Client`, so an agent can do nothing the browser could not: the app's own
validation, origin checks and refusals apply. The server speaks MCP over stdio and holds no state of its own beyond an
append-only audit log (JSONL, one "call" line before and one "result" line after every tool call, in the git-ignored
`audit/` folder; a call is refused when its line cannot be written). Read-only tools say so in their MCP annotations
and descriptions. Nothing destructive is exposed: saved runs and presets cannot be deleted or overwritten, and the
tools that replace the live run (reset_run, start_comparison) refuse to discard a recorded run unless asked to with
discard_current=true. docs/USAGE.md#agents-and-the-mcp-server describes the setup for Claude Code and other clients.
"""
import argparse
import functools
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from digitalfly import __version__ as APPLICATION_VERSION
from digitalfly.client import DEFAULT_URL, Client, ClientError

ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = ROOT / "audit"
AUDIT_FILE = "mcp.jsonl"
TOOLKIT = ROOT / "scripts/toolkit.py"
DOWNLOADS = ROOT / "runs/downloads"
SERVER_NAME = "digitalfly"
MAX_ARGUMENT_BYTES = 65536
MAX_OUTPUT_CHARS = 20000
# Toolkit commands an agent may run (plugin commands, "plugin:name", are allowed too). The server chooses where they
# write; these options would let a caller write elsewhere, so they are refused.
TOOLKIT_COMMANDS = {"trials", "bias", "ablation", "paths", "robustness", "readouts", "scorecard", "compare", "metrics",
                    "partners", "route", "influence", "neuroglancer", "circuits", "plugins"}
WRITES_OUT = TOOLKIT_COMMANDS - {"circuits", "plugins", "neuroglancer"}
REFUSED_OPTIONS = ("--out", "--export-dir", "--publish-dir", "--save-recording", "--resume")
MAX_WORKERS = 4
RUN_MARGIN_S = .3  # run_for pauses this much simulated time before its end and steps the rest
SUMMARY_KEYS = ("run_id", "status", "t", "key", "path", "bytes", "job", "id", "batch_id", "total", "returncode", "url",
                "error")

INSTRUCTIONS = """DigitalFly is a local closed-loop simulation of an embodied fruit fly: a FlyGym body (or a fast toy \
body) driven by an engineered six-unit brain or a FlyWire v783 connectome circuit. These tools drive the user's \
running app. There is one live experiment, shared with the browser: commands change what the user sees.

Start with `status`. A typical run: reset_run (with discard_current=true only if the user agreed to drop the current \
recording), set_stimulus / set_interventions, run_for a few simulated seconds, then export_run to save it; saved runs \
are in list_runs / get_run (with the provenance manifest and a drafted methods paragraph). For many trials use \
run_trials or run_toolkit, which run in separate processes without touching the live experiment. Connectivity \
questions (partners, routes, influence, Neuroglancer links) are read-only and work on the whole FlyWire brain \
("brain") or any circuit.

Results describe this simulation, not fly biology: connectivity is data-derived, synaptic signs are assumed, and the \
sensory input and motor mapping are engineered. The Virtual Fly Brain MCP server, if connected, complements these \
tools with anatomy, cell-type and literature queries; use FlyWire cell-type names (for example DNa02) in both."""


class AuditError(RuntimeError):
    """The audit log could not be written, so the call was refused."""


class ToolFailure(RuntimeError):
    """A tool call that failed with a message for the agent."""


class AuditLog:
    """Append-only JSONL: a "call" line before each tool runs and a "result" line after. Lines are only ever added
    (the file is opened with O_APPEND, mode 0600); nothing in DigitalFly rewrites or trims it."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else AUDIT_DIR / AUDIT_FILE
        self.session = uuid.uuid4().hex[:12]
        self._lock = threading.Lock()

    def write(self, entry: dict):
        line = json.dumps({"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                           "session": self.session, **entry}, default=str, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    os.write(descriptor, line.encode())
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise AuditError(f"The audit log {self.path} could not be written ({exc.strerror or exc}); "
                                 "the call was refused.") from exc

    def entries(self) -> list[dict]:
        if not self.path.is_file():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]


def _arguments_for_log(arguments: dict) -> Any:
    text = json.dumps(arguments, default=str, ensure_ascii=False)
    if len(text.encode()) <= MAX_ARGUMENT_BYTES:
        return arguments
    return {"truncated": True, "bytes": len(text.encode()), "start": text[:2000]}


def _summary(result) -> dict | None:
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    summary = {k: result[k] for k in SUMMARY_KEYS if k in result and isinstance(result[k], (str, int, float, bool))}
    if isinstance(result.get("job"), dict):
        summary["job"] = {k: result["job"].get(k) for k in ("id", "kind", "status", "target")}
    if isinstance(result.get("sample"), dict):
        summary["t"] = result["sample"].get("t")
    return summary


def _axis(key: str, values: list) -> str:
    """One --vary axis as scripts/toolkit.py reads it: comma-separated scalars, or one JSON list of lists/objects."""
    if not values:
        raise ValueError(f"vary.{key} needs at least one value.")
    if all(isinstance(v, (list, dict)) or v is None for v in values):
        return json.dumps(values)
    if any(isinstance(v, (list, dict)) or v is None for v in values):
        raise ValueError(f"vary.{key}: give either plain values or only lists/objects, not a mix.")
    if any(isinstance(v, str) and "," in v for v in values):
        raise ValueError(f"vary.{key}: text values cannot contain commas.")
    return ",".join(v if isinstance(v, str) else json.dumps(v) for v in values)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    read_only: bool
    destructive: bool
    idempotent: bool
    function: Any

    @property
    def description(self) -> str:
        text = " ".join((self.function.__doc__ or "").split())
        marker = "[read-only] " if self.read_only else "[changes the live experiment] " if self.destructive else ""
        return marker + text


def tool(title: str, read_only: bool = False, destructive: bool = False, idempotent: bool = False):
    def mark(function):
        function.mcp_tool = {"title": title, "read_only": read_only, "destructive": destructive,
                             "idempotent": idempotent or read_only}
        return function
    return mark


# Parameter types shared by several tools.
RunKey = Annotated[str, Field(description="A saved run's folder name, as list_runs gives it", max_length=200)]
Graph = Annotated[str, Field(description='"brain" (the whole FlyWire v783 brain, from the prepared archive) or a '
                                         'circuit name from list_circuits', max_length=64)]
Side = Literal["both", "left", "right"]
Others = Annotated[Literal["excluded", "excitatory"], Field(
    description="Synapses of neurons with other or unknown transmitters: left out (default) or counted excitatory")]
Discard = Annotated[bool, Field(description="Allow replacing a live run that has recorded samples. Unexported samples "
                                            "are lost; export_run first to keep them.")]


class Toolbox:
    """The tools, bound to a client and an audit log. `call(name, arguments)` runs one with auditing; the MCP server
    and the tests both use it."""

    def __init__(self, client: Client, audit: AuditLog | None = None, downloads: Path | None = None,
                 toolkit: Path = TOOLKIT, python: str = sys.executable):
        self.client, self.audit = client, audit or AuditLog()
        self.downloads = Path(downloads) if downloads else DOWNLOADS
        self.toolkit, self.python = Path(toolkit), python
        self._toolkit_lock = threading.Lock()

    def specs(self) -> list[ToolSpec]:
        found = []
        for name in dir(type(self)):
            function = getattr(type(self), name)
            meta = getattr(function, "mcp_tool", None)
            if meta:
                found.append(ToolSpec(name=name, function=getattr(self, name), **meta))
        return sorted(found, key=lambda s: s.name)

    def call(self, name: str, arguments: dict | None = None):
        spec = next((s for s in self.specs() if s.name == name), None)
        if spec is None:
            raise ToolFailure(f"No tool named {name}.")
        arguments = dict(arguments or {})
        call_id = uuid.uuid4().hex[:12]
        self.audit.write({"event": "call", "call": call_id, "tool": name, "read_only": spec.read_only,
                          "arguments": _arguments_for_log(arguments)})
        started = time.monotonic()
        try:
            result = spec.function(**arguments)
        except Exception as exc:
            message = self.explain(exc)
            self.audit.write({"event": "result", "call": call_id, "tool": name, "outcome": "error", "error": message,
                              "duration_ms": round((time.monotonic() - started) * 1000, 1)})
            raise ToolFailure(message) from exc
        self.audit.write({"event": "result", "call": call_id, "tool": name, "outcome": "ok",
                          "duration_ms": round((time.monotonic() - started) * 1000, 1), "summary": _summary(result)})
        return result

    def explain(self, exc: Exception) -> str:
        if isinstance(exc, ClientError):
            return f"DigitalFly refused the request: {exc}"
        if isinstance(exc, urllib.error.URLError) or isinstance(exc, ConnectionError):
            return (f"DigitalFly is not reachable at {self.client.url} ({getattr(exc, 'reason', exc)}). Ask the user to "
                    "start it with ./scripts/start.sh, or pass --url to the MCP server.")
        if isinstance(exc, (ToolFailure, ValueError, TimeoutError)):
            return str(exc)
        return f"{type(exc).__name__}: {exc}"

    # ---- Status and reading -------------------------------------------------------------------------------------

    @tool("Status of the running app", read_only=True)
    def status(self, include_capabilities: bool = False, events: Annotated[int, Field(ge=0, le=50)] = 10) -> dict:
        """The live experiment: run status, simulated time, configuration, interventions, the latest sample (pose in
        mm and rad, sensor values, readout rates, motor command), metrics and the latest events. With
        include_capabilities, also the bodies, models, circuits and optional parts this installation has."""
        state = self.client.status()
        sample = state.get("sample") or {}
        pose = {k: v for k, v in (sample.get("pose") or {}).items() if k != "legs"}
        batch = state.get("batch")
        compact = {
            "app": {"url": self.client.url, **self.client.health()},
            "status": state.get("status"), "error": state.get("error"), "run_id": state.get("run_id"),
            "config": state.get("config"), "interventions": state.get("interventions"),
            "sample": {"step": sample.get("step"), "t": sample.get("t"), "pose": pose, "sensors": sample.get("sensors"),
                       "rates": sample.get("rates"), "motor": sample.get("motor")} if sample else None,
            "metrics": state.get("metrics"), "recording_samples": state.get("recording_samples"),
            "recording_limit": state.get("recording_limit"), "real_time_factor": state.get("real_time_factor"),
            "batch": {k: v for k, v in batch.items() if k != "results"} | {"results": len(batch.get("results", []))}
            if batch else None,
            "events": [{k: e.get(k) for k in ("t", "kind", "message")} for e in (state.get("events") or [])[-events:]]
            if events else [],
            "connectome_units": (state.get("connectome") or {}).get("unit_names"),
        }
        if include_capabilities:
            compact["capabilities"] = self.client.capabilities()
        return compact

    @tool("List circuits", read_only=True)
    def list_circuits(self) -> dict:
        """Committed and locally built connectome circuits (name, neurons, connections, build settings) and the circuit
        the live run uses, plus the explorer's graphs and whether the whole-brain archive is prepared."""
        return {**self.client.circuits(), "explorer": self.client.explore_graphs()}

    @tool("List background jobs", read_only=True)
    def list_jobs(self) -> dict:
        """Background jobs (circuit builds, replay checks, scorecards) with status, progress and result, newest first."""
        return self.client.jobs()

    @tool("Validation scorecards", read_only=True)
    def get_scorecards(self, key: Annotated[str | None, Field(
            description="A card's key to return in full (its tests and measured values); omit for the list")] = None) -> dict:
        """The validation scorecard: published perturbation → behavior tests (source, rule) and, per model scored, the
        latest card's summary. Give a key for one card's per-test status, measurement and caveats."""
        listing = self.client.scorecards()
        cards = listing.get("scorecards", [])
        if key:
            card = next((c for c in cards if c.get("key") == key), None)
            if card is None:
                raise ValueError(f"No scorecard {key}; the scored models are {', '.join(c.get('key') for c in cards) or 'none'}.")
            return {k: v for k, v in card.items() if k != "trials"} | {"trials": len(card.get("trials", []))}
        return {"version": listing.get("version"),
                "tests": [{k: t.get(k) for k in ("id", "title", "rule", "needs")} | {"source": t.get("source")}
                          for t in listing.get("tests", [])],
                "scorecards": [{"key": c.get("key"), "label": (c.get("model") or {}).get("label"), "engine": c.get("engine"),
                                "created": c.get("created"), "summary": (c.get("summary") or {}).get("text")}
                               for c in cards]}

    @tool("List saved runs", read_only=True)
    def list_runs(self, offset: Annotated[int, Field(ge=0)] = 0, limit: Annotated[int, Field(ge=1, le=200)] = 20,
                  model: Literal["engineered", "connectome"] | None = None, circuit: str | None = None,
                  batch: Annotated[str | None, Field(description="A comparison's id")] = None,
                  tag: str | None = None, text: Annotated[str | None, Field(description="Search text")] = None) -> dict:
        """Saved runs in the run library, newest first: key, run id, configuration, samples, metrics, comparison and
        condition, tags and replay verdict. Filters combine; `total` counts all matches."""
        query = {"offset": offset, "limit": limit, "model": model, "circuit": circuit, "batch": batch, "tag": tag,
                 "q": text}
        body, headers = self.client.request("GET", "/api/runs", query={k: v for k, v in query.items() if v is not None})
        total = {k.lower(): v for k, v in headers.items()}.get("x-total-count")
        return {"runs": body.get("runs", []), "total": int(total) if total is not None else None}

    @tool("Get a saved run", read_only=True)
    def get_run(self, key: RunKey, trajectory: bool = False, manifest: bool = False, methods: bool = True) -> dict:
        """One saved run: its library entry (configuration, metrics, provenance labels, replay verdict) and, as asked,
        its decimated trajectory ([t s, x mm, y mm, speed mm/s], about 400 points), its RO-Crate provenance manifest
        (software, git commit, lock hashes, connectome sources and hashes, parameter changes) and a drafted methods
        paragraph (Markdown; review before use)."""
        detail = self.client.saved_run(key)
        if not trajectory:
            detail = {k: v for k, v in detail.items() if k != "trajectory"}
        if manifest:
            detail["manifest"] = self.client.manifest(key)
        if methods:
            detail["methods"] = self.client.methods(key)
        return detail

    @tool("Comparison summary", read_only=True)
    def comparison_summary(self, batch_id: Annotated[str, Field(description="The comparison's id (a run's batch_id)")],
                           methods: bool = True) -> dict:
        """Statistics of a comparison's saved trials per condition (reach rate with Wilson intervals, final distance
        and speed with bootstrap intervals) and matched-seed paired differences, plus a drafted methods paragraph."""
        summary = self.client.comparison_summary(batch_id)
        if methods:
            summary["methods_draft"] = self.client.comparison_methods(batch_id)
        return summary

    @tool("List presets", read_only=True)
    def list_presets(self, name: Annotated[str | None, Field(description="A preset to return in full")] = None) -> dict:
        """Named run configurations (shipped and saved locally). Give a name for its full configuration, which
        reset_run accepts as `config`."""
        if name:
            return self.client._get(f"/api/configs/{urllib.parse.quote(name, safe='')}")
        return self.client._get("/api/configs")

    # ---- Connectivity explorer (read-only) ----------------------------------------------------------------------

    @tool("Upstream or downstream partners", read_only=True)
    def explore_partners(self, query: Annotated[str, Field(description="Cell types or FlyWire root IDs, comma-separated")],
                         direction: Literal["upstream", "downstream"] = "upstream", graph: Graph = "brain",
                         group: Literal["cell_type", "neuron"] = "cell_type", side: Side = "both",
                         threshold: Annotated[int, Field(ge=1, le=1000, description="Minimum synapses per connection")] = 5,
                         limit: Annotated[int, Field(ge=1, le=500)] = 30, other_transmitters: Others = "excluded") -> dict:
        """Upstream or downstream partners of cell types or neurons, by cell type or neuron, with synapse counts,
        input fractions, transmitters and signs. Changes nothing in the live experiment."""
        return self.client.partners(query, direction=direction, graph=graph, group=group, side=side, threshold=threshold,
                                    limit=limit, other_transmitters=other_transmitters)

    @tool("Strongest or shortest route", read_only=True)
    def explore_route(self, source: str, target: str, mode: Literal["strongest", "shortest"] = "strongest",
                      level: Literal["cell_type", "neuron"] = "cell_type", graph: Graph = "brain",
                      threshold: Annotated[int, Field(ge=1, le=1000)] = 5, limit: Annotated[int, Field(ge=1, le=50)] = 5,
                      max_hops: Annotated[int, Field(ge=1, le=20)] = 10, source_side: Side = "both",
                      target_side: Side = "both", other_transmitters: Others = "excluded") -> dict:
        """Exact strongest (largest product of input fractions) or shortest (fewest steps) paths from source to target
        cell types or neurons, with alternatives through other connections."""
        return self.client.paths(source, target, mode=mode, level=level, graph=graph, threshold=threshold, limit=limit,
                                 max_hops=max_hops, source_side=source_side, target_side=target_side,
                                 other_transmitters=other_transmitters)

    @tool("Steady-state influence", read_only=True)
    def explore_influence(self, query: str, direction: Literal["from", "onto"] = "from", graph: Graph = "brain",
                          group: Literal["cell_type", "neuron"] = "cell_type", side: Side = "both",
                          threshold: Annotated[int, Field(ge=1, le=1000)] = 5, limit: Annotated[int, Field(ge=1, le=500)] = 30,
                          signed: bool = True, other_transmitters: Others = "excluded") -> dict:
        """Steady-state influence (a BANC-style linear model of the wiring) of the query on every neuron
        (direction "from"), or of every neuron on the query ("onto"), ranked. A property of the wiring, not a
        simulation."""
        return self.client.influence(query, direction=direction, graph=graph, group=group, side=side,
                                     threshold=threshold, limit=limit, signed=signed,
                                     other_transmitters=other_transmitters)

    @tool("Neuroglancer link", read_only=True)
    def neuroglancer_link(self, groups: Annotated[list[dict], Field(
            description='Neuron groups, each {"label", "cell_type", "side"} or {"label", "ids": [root IDs]}',
            max_length=20)] = [],  # noqa: B006 (MCP needs a JSON default)
            circuit: Annotated[str | None, Field(description="Also show a whole circuit by name")] = None,
            graph: Graph = "brain", title: str | None = None) -> dict:
        """A Neuroglancer link that shows the chosen neurons in the FlyWire brain, streamed from FlyWire's public
        segmentation (nothing is downloaded). Returns the URL and the neurons it holds."""
        result = self.client.neuroglancer(groups, circuit=circuit, graph=graph, **({"title": title} if title else {}))
        return {k: v for k, v in result.items() if k != "state"}

    # ---- Plugins ------------------------------------------------------------------------------------------------

    @tool("Installed plugins", read_only=True)
    def list_plugins(self) -> dict:
        """Installed DigitalFly plugins (digitalfly.plugins entry points), their status and their sensors, stimulus
        programs, scorecard tests, metrics and toolkit commands."""
        return self.client.plugins()

    @tool("Plugin metrics of a saved run", read_only=True)
    def run_metrics(self, key: RunKey, metrics: Annotated[list[str], Field(
            description="plugin:metric names; empty for every installed metric", max_length=50)] = []) -> dict:  # noqa: B006
        """Metrics that installed plugins compute on a saved run. Each value names its plugin and version."""
        return self.client.run_metrics(key, metrics or None)

    # ---- Driving the live experiment ----------------------------------------------------------------------------

    def _guard(self, discard_current: bool, action: str):
        state = self.client.status()
        if state.get("status") == "running":
            raise ValueError(f"The run is running; pause_run before you {action}.")
        if (state.get("recording_samples") or 0) > 1 and not discard_current:
            raise ValueError(f"The live run {state.get('run_id')} has {state['recording_samples']} recorded samples, "
                             f"which {action} would replace. export_run first to keep them, then repeat with "
                             "discard_current=true (ask the user if unsure).")

    @tool("Reset the live run", destructive=True)
    def reset_run(self, config: Annotated[dict | None, Field(
            description="A RunConfig (fields left out take the defaults, which include the FlyGym body), or omit to "
                        "restart from the current configuration")] = None,
            settings: Annotated[dict | None, Field(
                description='Single values to change, dotted for nested ones: {"seed": 4, '
                            '"connectome_parameters.dynamics": "spiking"}')] = None,
            discard_current: Discard = False) -> dict:
        """Start a new live run from a configuration (engine "toy" or "flygym", neural_model "engineered" or
        "connectome", connectome_parameters, stimulus, initial_interventions, protocol, seed, ...). Replaces the current
        run, so it refuses while recorded samples would be lost unless discard_current is true."""
        self._guard(discard_current, "a reset")
        return self._compact(self.client.reset(config, **(settings or {})))

    @tool("Start the live run")
    def start_run(self) -> dict:
        """Run the live experiment continuously (paced by its display speed) until pause_run, a protocol's end or the
        recording limit."""
        return self._compact(self.client.run())

    @tool("Pause the live run", idempotent=True)
    def pause_run(self) -> dict:
        """Pause the live experiment."""
        return self._compact(self.client.pause())

    @tool("Step the live run")
    def step_run(self, count: Annotated[int, Field(ge=1, le=500, description="10 ms control intervals")] = 1) -> dict:
        """Advance a paused run by count control intervals (10 ms each)."""
        return self._compact(self.client.step(count))

    @tool("Run for a while")
    def run_for(self, seconds: Annotated[float, Field(gt=0, le=120, description="Simulated seconds to add")],
                timeout_s: Annotated[float, Field(gt=0, le=1800)] = 300) -> dict:
        """Run the live experiment for this many more simulated seconds (to the 10 ms control interval), then pause,
        and return the state. Stops early at a protocol's end or the recording limit."""
        def now(state):
            return (state.get("sample") or {}).get("t") or 0
        state = self.client.status()
        end = now(state) + seconds - 1e-9
        # Run until close to the end (the display pace is at most 2× real time, about 0.1 s between polls), pause,
        # then step the last control intervals, so the run stops at the requested time.
        if seconds > RUN_MARGIN_S:
            self.client.run()
            try:
                state = self.client.wait_until(lambda s: now(s) >= end - RUN_MARGIN_S or s.get("status") != "running",
                                               timeout=timeout_s, interval=.05)
            finally:
                state = self.client.pause() if self.client.status().get("status") == "running" else self.client.status()
        while now(state) < end and state.get("status") == "paused":
            try:
                state = self.client.step(1)
            except ClientError as exc:
                if exc.status == 409:  # a protocol's end or the recording limit
                    break
                raise
        return self._compact(state)

    @tool("Move the target")
    def set_stimulus(self, x: Annotated[float, Field(ge=-40, le=40, description="mm")],
                     y: Annotated[float, Field(ge=-40, le=40, description="mm; positive = left of the start heading")],
                     intensity: Annotated[float, Field(ge=0, le=2)] = 1.0) -> dict:
        """Move the visual target to (x, y) mm with an intensity (0 = darkness). Recorded as a stimulus event."""
        return self._compact(self.client.stimulus(x, y, intensity))

    @tool("Set interventions")
    def set_interventions(self, interventions: Annotated[dict, Field(
            description='Interventions fields: zero_left, zero_right, silence (engineered), silence_dna02, '
                        'silence_types, cell_types: [{"name", "side": both|left|right, "mode": silence|scale|activate, '
                        '"value"}] (connectome)')],
            replace: Annotated[bool, Field(description="Reset the other fields to their defaults instead of merging")] = False
            ) -> dict:
        """Change the live run's interventions (engineered manipulations: silencing, scaling or activating cell types
        per side, zeroing a sensor). Merged into the current ones unless replace is true. Recorded and replayed."""
        return self._compact(self.client.interventions(interventions, replace=replace))

    @tool("Set connectome parameters")
    def set_connectome_parameters(self, parameters: Annotated[dict, Field(
            description="Live-editable ConnectomeParameters fields (gains, motor path, ...)")],
            replace: bool = False) -> dict:
        """Change the connectome model's live-editable parameters mid-run (merged into the current ones unless replace
        is true). Circuit, dynamics and populations change only with reset_run."""
        return self._compact(self.client.connectome_parameters(parameters, replace=replace))

    @tool("Save the live run")
    def export_run(self, share_safe: Annotated[bool, Field(
            description="Leave out local paths, the host name and the platform string")] = False) -> dict:
        """Save the live run to the run library (telemetry, metadata, provenance manifest, methods draft) and return
        its key. The run can go on afterwards."""
        result = self.client.export(share_safe=share_safe)
        return {**result, "key": Path(result.get("path", "")).name or None}

    # ---- Background work in the app ------------------------------------------------------------------------------

    @tool("Build a circuit")
    def build_circuit(self, name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")],
                      seeds: Annotated[list[str], Field(min_length=1, max_length=20, description="Seed cell types")],
                      hops: Annotated[int, Field(ge=1, le=6)] = 2, threshold: Annotated[int, Field(ge=1, le=1000)] = 5,
                      cap: Annotated[int, Field(ge=10, le=200000)] = 3000, whole_brain: bool = False,
                      balance_sides: bool = False) -> dict:
        """Build a local circuit from FlyWire v783 around seed cell types, as a background job (follow it with
        list_jobs). Needs the prepared FlyWire archive. Refuses an existing name and a second concurrent build."""
        return self.client.build_circuit(name, seeds, hops=hops, threshold=threshold, cap=cap, whole_brain=whole_brain,
                                         balance_sides=balance_sides)

    @tool("Score a model")
    def run_scorecard(self, model: Literal["engineered", "connectome"] = "connectome", circuit: str | None = None,
                      dynamics: Literal["rate", "spiking"] = "rate", engine: Literal["toy", "flygym"] = "toy") -> dict:
        """Score a model on the validation scorecard in a background job (the toy body takes under a minute for a
        rate model). The card then appears in get_scorecards."""
        return self.client.run_scorecard(model=model, circuit=circuit, dynamics=dynamics, engine=engine)

    @tool("Start a comparison", destructive=True)
    def start_comparison(self, config: Annotated[dict, Field(description="A RunConfig with a protocol (a finite schedule)")],
                         conditions: Annotated[list[str], Field(max_length=4, description=(
                             "Built-in conditions: control, left_sensor_off, descending_off, baseline, engineered_model, "
                             "connectome_model, dna02_left_off, dna02_right_off, dna02_both_off, cell_type_off"))] = ["control"],  # noqa: B006
                         seeds: Annotated[list[int], Field(min_length=1, max_length=5)] = [42, 43],  # noqa: B006
                         custom_conditions: Annotated[list[dict], Field(max_length=6, description=(
                             '[{"label", "interventions": {...} | null, "connectome_parameters": {...} | null}]'))] = [],  # noqa: B006
                         cell_type: str | None = None, max_speed: bool = True, discard_current: Discard = False) -> dict:
        """Run a matched-seed comparison in the app: every condition for every seed, each trial saved to the run
        library under one batch id; read it with comparison_summary. It takes over the live experiment, so it refuses
        to replace a recorded run unless discard_current is true."""
        self._guard(discard_current, "a comparison")
        state = self.client.start_comparison(config, conditions=conditions, seeds=seeds,
                                             custom_conditions=custom_conditions, cell_type=cell_type, max_speed=max_speed)
        return self._compact(state)

    @tool("Cancel the comparison")
    def cancel_comparison(self) -> dict:
        """Cancel a running comparison; the unfinished trial is saved marked partial."""
        return self._compact(self.client.cancel_comparison())

    @tool("Check a run replays")
    def replay_check(self, key: RunKey) -> dict:
        """Replay a saved run in a background job and compare it with its recording (the verdict appears in get_run)."""
        return self.client.replay_check(key)

    @tool("Cancel a background job", idempotent=True)
    def cancel_job(self, job_id: str) -> dict:
        """Cancel a queued or running background job (a build, replay check or scorecard). Saved data is not touched."""
        return self.client.cancel_job(job_id)

    @tool("Export a run as NWB")
    def export_nwb(self, key: RunKey) -> dict:
        """Write a saved run as an NWB 2 file (body position and heading, readout activity, spike times) and save a copy
        under runs/downloads/. Needs pynwb in the app's environment (./scripts/setup.sh --with nwb)."""
        if "/" in key or key.startswith("."):
            raise ValueError("Give a run key from list_runs.")
        return self.client.nwb(key, self.downloads / f"{key}.nwb")

    # ---- The research toolkit (separate processes; the live experiment is untouched) --------------------------------

    @tool("Closed-loop trials (toolkit)")
    def run_trials(self, settings: Annotated[dict, Field(
            description='RunConfig values for every trial, dotted names allowed: {"neural_model": "connectome", '
                        '"connectome_parameters.circuit": "fafb783-steering"}')] = {},  # noqa: B006
            vary: Annotated[dict[str, list], Field(
                description='Grid axes: {"connectome_parameters.dynamics": ["rate", "spiking"]}')] = {},  # noqa: B006
            engine: Literal["toy", "flygym"] = "toy",
            seeds: Annotated[str, Field(description="e.g. 1-5 or 1,7,9")] = "1-3",
            bearings: Annotated[str, Field(description="Target bearings, degrees, positive = left")] = "0,45,-45,90,-90",
            distances: Annotated[str, Field(description="Target distances, mm")] = "12",
            duration_s: Annotated[float, Field(gt=0, le=60)] = 5,
            workers: Annotated[int, Field(ge=1, le=MAX_WORKERS)] = 1,
            timeout_s: Annotated[float, Field(gt=0, le=3600)] = 900) -> dict:
        """Closed-loop trials or a parameter sweep with the research toolkit (scripts/toolkit.py trials), in separate
        processes: every combination of the varied settings × target positions × seeds. Returns per-condition
        statistics (reach rate, first turn toward, final distance, speed, with intervals) and matched-seed paired
        differences, and where the full results were saved."""
        # "--option=value" keeps values such as "-45,45" from being read as options.
        arguments = [f"--engine={engine}", f"--duration={duration_s:g}", f"--workers={workers}"]
        named = set(settings) | set(vary)
        if not named & {"seed"}:
            arguments.append(f"--seeds={seeds}")
        if not named & {"stimulus", "stimulus.x", "stimulus.y"}:
            arguments += [f"--bearings={bearings}", f"--distances={distances}"]
        for key, value in settings.items():
            arguments.append(f"--set={key}={value if isinstance(value, str) else json.dumps(value)}")
        for key, values in vary.items():
            arguments.append(f"--vary={key}={_axis(key, values)}")
        return self.run_toolkit("trials", arguments, timeout_s)

    @tool("Research toolkit command")
    def run_toolkit(self, command: Annotated[str, Field(description=(
            "trials, bias, ablation, paths, robustness, readouts, scorecard, compare, metrics, partners, route, "
            "influence, neuroglancer, circuits, plugins, or a plugin command plugin:name"))],
            arguments: Annotated[list[str], Field(max_length=200, description=(
                'Command-line arguments as a list, e.g. ["--set", "circuit=fafb783-steering"]; see '
                "scripts/toolkit.py COMMAND --help. The server chooses where results are saved."))] = [],  # noqa: B006
            timeout_s: Annotated[float, Field(gt=0, le=3600)] = 900) -> dict:
        """Run one research-toolkit command (scripts/toolkit.py) in a separate process, without the app: sweeps, bias
        curves, ablation scans, assumption robustness, scorecards (not published to the app), fits to recordings,
        plugin metrics or plugin commands. Returns its printed report and, when it saves one, the JSON results."""
        if command not in TOOLKIT_COMMANDS and not (":" in command and command.count(":") == 1):
            raise ValueError(f"run_toolkit runs {', '.join(sorted(TOOLKIT_COMMANDS))} or a plugin command (plugin:name), "
                             f"not {command!r}.")
        arguments = [str(a) for a in arguments]
        for argument in arguments:
            if argument.split("=", 1)[0] in REFUSED_OPTIONS:
                raise ValueError(f"{argument.split('=', 1)[0]} is chosen by the server; leave it out.")
        for flag, value in zip(arguments, arguments[1:] + [""]):
            if flag.split("=", 1)[0] == "--workers":
                count = value if "=" not in flag else flag.split("=", 1)[1]
                if not count.isdigit() or not 1 <= int(count) <= MAX_WORKERS:
                    raise ValueError(f"Use 1 to {MAX_WORKERS} workers.")
        stem = None
        command_line = [self.python, str(self.toolkit), command, *arguments]
        if command in WRITES_OUT:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            stem = ROOT / "runs/toolkit/mcp" / f"{stamp}-{uuid.uuid4().hex[:6]}-{command}"
            command_line += ["--out", str(stem)]
            if command == "scorecard":
                command_line.append("--no-publish")
        if not self._toolkit_lock.acquire(blocking=False):
            raise ValueError("Another toolkit command from this server is still running; wait for it to finish.")
        try:
            return self._run_process(command_line, timeout_s, stem)
        finally:
            self._toolkit_lock.release()

    def _run_process(self, command_line: list[str], timeout_s: float, stem: Path | None) -> dict:
        process = subprocess.Popen(command_line, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True,
                                   env={**os.environ, "PYTHONUNBUFFERED": "1"})
        try:
            output, _ = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            raise TimeoutError(f"The toolkit command did not finish within {timeout_s:g} s and was stopped. Its output "
                               f"ended: {(output or '')[-1500:]}")
        result = {"command": command_line[2:], "returncode": process.returncode,
                  "output": (output or "")[-MAX_OUTPUT_CHARS:]}
        if stem is not None:
            saved = Path(f"{stem}.json")
            if saved.is_file():
                report = json.loads(saved.read_text())
                for bulky in ("trials", "rows", "results"):
                    if isinstance(report.get(bulky), list) and len(report[bulky]) > 50:
                        report[bulky] = f"{len(report[bulky])} rows; see {saved.relative_to(ROOT)}"
                text = json.dumps(report, default=str)
                result["report"] = report if len(text) <= 200_000 else f"{len(text)} characters; see the saved file"
                result["saved"] = [str(p.relative_to(ROOT)) for p in sorted(stem.parent.glob(stem.name + ".*"))]
        if process.returncode:
            result["error"] = "The toolkit command failed; see output."
        return result

    def _compact(self, state: dict) -> dict:
        """The state a command returns, without the display history (status() gives the rest)."""
        if not isinstance(state, dict):
            return state
        sample = state.get("sample") or {}
        return {"status": state.get("status"), "error": state.get("error"), "run_id": state.get("run_id"),
                "t": sample.get("t"), "step": sample.get("step"),
                "pose": {k: v for k, v in (sample.get("pose") or {}).items() if k != "legs"},
                "sensors": sample.get("sensors"), "motor": sample.get("motor"), "interventions": state.get("interventions"),
                "recording_samples": state.get("recording_samples"), "metrics": state.get("metrics"),
                "batch": {k: v for k, v in (state.get("batch") or {}).items() if k != "results"} or None}


# ---------------------------------------------------------------------------------------------------------------------
# The MCP server (needs the optional `mcp` package: ./scripts/setup.sh --with mcp)

def build_server(toolbox: Toolbox):
    """An MCPServer with every tool of the toolbox, each annotated (read-only, destructive, idempotent) and audited."""
    try:
        from mcp.server.mcpserver import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise SystemExit("The MCP server needs the mcp package: ./scripts/setup.sh --with mcp (or backend/.venv/bin/"
                         "python -m pip install --require-hashes -r backend/requirements-mcp.lock).") from exc
    import anyio.to_thread

    server = MCPServer(SERVER_NAME, title="DigitalFly", version=APPLICATION_VERSION, instructions=INSTRUCTIONS,
                       description="Drive a local DigitalFly embodied-fly simulation: runs, interventions, comparisons, "
                                   "the scorecard, the connectivity explorer and saved runs with provenance.")
    for spec in toolbox.specs():
        def make(spec=spec):
            @functools.wraps(spec.function)
            async def handler(**arguments):
                try:
                    return await anyio.to_thread.run_sync(functools.partial(toolbox.call, spec.name, arguments))
                except (ToolFailure, AuditError) as exc:
                    raise ToolError(str(exc)) from None
            return handler
        server.add_tool(make(), name=spec.name, title=spec.title, description=spec.description, structured_output=False,
                        annotations=ToolAnnotations(title=spec.title, read_only_hint=spec.read_only,
                                                    destructive_hint=spec.destructive if not spec.read_only else False,
                                                    idempotent_hint=spec.idempotent, open_world_hint=False))
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="DigitalFly's MCP server (stdio): agents drive the running app.")
    parser.add_argument("--url", default=os.environ.get("DIGITALFLY_URL", DEFAULT_URL),
                        help=f"The app's address (default {DEFAULT_URL}, or DIGITALFLY_URL)")
    parser.add_argument("--audit-log", default=os.environ.get("DIGITALFLY_MCP_AUDIT"),
                        help=f"Audit log file (default {AUDIT_DIR.relative_to(ROOT)}/{AUDIT_FILE}, or DIGITALFLY_MCP_AUDIT)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Seconds to wait for one API request (default 60)")
    parser.add_argument("--list-tools", action="store_true", help="Print the tools and their annotations, then exit")
    args = parser.parse_args(argv)
    toolbox = Toolbox(Client(args.url, timeout=args.timeout), AuditLog(Path(args.audit_log) if args.audit_log else None))
    if args.list_tools:
        for spec in toolbox.specs():
            kind = "read-only" if spec.read_only else "destructive (guarded)" if spec.destructive else "changes state"
            print(f"{spec.name:28} {kind:22} {spec.title}")
        return
    server = build_server(toolbox)
    toolbox.audit.write({"event": "start", "url": args.url, "version": APPLICATION_VERSION, "pid": os.getpid(),
                         "tools": [s.name for s in toolbox.specs()]})
    print(f"DigitalFly MCP server for {args.url}; audit log {toolbox.audit.path}", file=sys.stderr, flush=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
