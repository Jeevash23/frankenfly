"""Plugins: other packages add sensors, stimulus programs, scorecard tests, run metrics and toolkit commands.

A plugin is an installed Python distribution that declares one entry point in the `digitalfly.plugins` group:

    [project.entry-points."digitalfly.plugins"]
    example = "digitalfly_example_plugin:plugin"

The entry point names a `Plugin` (or a function without arguments that returns one). Its name is the entry point's
name; its version is the distribution's. `docs/PLUGINS.md` is the API reference; `examples/plugins/` has a package.

Plugins never change what DigitalFly does by default. Nothing a plugin contributes runs until it is asked for by name
("plugin:contribution"): a sensor in `RunConfig.plugins.sensor`, a stimulus program through `stimulus_protocol`, scorecard
tests with `scorecard --plugin-tests`, metrics with `toolkit.py metrics` or `GET /api/runs/KEY/metrics`, commands as
`toolkit.py plugin:command`. A run that used a plugin records it (name, distribution, version and API version) in its
metadata and provenance manifest; runs made without plugins are computed, exported and replayed exactly as before.

Discovery imports each plugin's module once per process. A plugin that fails to import, or that was written for
another API version, is listed with its error and never used. Set DIGITALFLY_PLUGINS=0 to skip discovery altogether.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable

API_VERSION = 1
GROUP = "digitalfly.plugins"
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
REFERENCE = re.compile(r"^([a-z0-9][a-z0-9_.-]{0,63}):([a-z0-9][a-z0-9_.-]{0,63})$")
KINDS = ("sensors", "stimuli", "scorecard_tests", "metrics", "commands")


class PluginError(ValueError):
    """A plugin or contribution that is missing, broken or of the wrong kind."""


# ---------------------------------------------------------------------------------------------------------------------
# What a plugin can contribute (API version 1). Every contribution has a `name` unique within its plugin and kind.

@dataclass(frozen=True)
class SensorReading:
    """What a sensor plugin sees each 10 ms control interval: the body's pose (mm, rad, mm/s), the target, simulated
    time and step, and the built-in geometric encoder's values for comparison. No other state is offered: a sensor must
    be a deterministic function of these, so runs that use it replay."""
    t: float
    step: int
    x: float
    y: float
    yaw: float
    velocity: float
    target_x: float
    target_y: float
    intensity: float
    geometric_left: float
    geometric_right: float
    bearing_rad: float  # target bearing from the heading, positive to the left
    distance_mm: float


@dataclass(frozen=True)
class Sensor:
    """Replaces the geometric encoder's two values (left, right, each clipped to [0, 1]) with `encode(reading)`.
    Works with the geometric sensor model on either body; input interventions (zero_left, zero_right) still apply."""
    name: str
    title: str
    encode: Callable[[SensorReading], tuple[float, float]]
    description: str = ""


@dataclass(frozen=True)
class StimulusProgram:
    """Writes a stimulus and intervention schedule: `protocol(**parameters)` returns a `Protocol` (or its dict). The
    schedule goes into the run's configuration, so the run replays without the plugin; the program is recorded."""
    name: str
    title: str
    protocol: Callable[..., Any]
    parameters: dict = field(default_factory=dict)  # name → default value (numbers, text or booleans)
    description: str = ""


@dataclass(frozen=True)
class ScorecardTest:
    """A scorecard test written like the built-in ones (digitalfly.scorecard.TESTS). `conditions(names, dynamics)`
    returns [(label, Stimulus, Interventions)] for matched-seed trials, `names` being the first cell type found for each
    group in `cell_types`; `score(names, trials)` returns (status, measured) from the trial rows (condition, seed and
    the metrics of scorecard.trial_metrics). Statuses: pass, partial, fail or inconclusive."""
    id: str
    title: str
    source: dict  # citation, doi, finding
    manipulation: str
    measure: str
    rule: str
    conditions: Callable[..., list]
    score: Callable[..., tuple]
    cell_types: list = field(default_factory=list)  # groups of accepted names, as in TESTS
    needs: list = field(default_factory=list)  # capabilities: walk, turn, vision, ... (see scorecard.CAPABILITY_TEXT)
    caveats: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.id


@dataclass(frozen=True)
class ExportedRun:
    """A saved run as metrics see it: its folder, metadata.json and telemetry.csv as columns of floats."""
    path: Path
    metadata: dict
    columns: dict[str, list[float]]

    @property
    def key(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Metric:
    """A number (or a flat dict of numbers) computed from an exported run. Return None when it does not apply."""
    name: str
    title: str
    compute: Callable[[ExportedRun], Any]
    unit: str = ""
    description: str = ""


@dataclass(frozen=True)
class Command:
    """A toolkit command, run as `scripts/toolkit.py plugin:name`: `add_arguments(parser)` declares its options and
    `run(args)` does the work (print, and save under runs/toolkit/ as the built-in commands do)."""
    name: str
    help: str
    run: Callable[[Any], Any]
    add_arguments: Callable[[Any], None] | None = None


@dataclass(frozen=True)
class Plugin:
    api_version: int
    title: str = ""
    description: str = ""
    url: str = ""
    license: str = ""
    sensors: tuple = ()
    stimuli: tuple = ()
    scorecard_tests: tuple = ()
    metrics: tuple = ()
    commands: tuple = ()


# ---------------------------------------------------------------------------------------------------------------------
# Discovery

@dataclass
class Installed:
    name: str
    distribution: str | None
    version: str | None
    value: str  # the entry point, module:attribute
    status: str  # ok, error or incompatible
    error: str | None = None
    plugin: Plugin | None = None

    def describe(self) -> dict:
        p = self.plugin
        contributions = {kind: [] for kind in KINDS}
        if p is not None and self.status == "ok":
            for kind in KINDS:
                for item in getattr(p, kind):
                    entry = {"name": item.name, "title": getattr(item, "title", None) or getattr(item, "help", "")}
                    if kind == "metrics" and item.unit:
                        entry["unit"] = item.unit
                    if kind == "stimuli":
                        entry["parameters"] = dict(item.parameters)
                    contributions[kind].append(entry)
        return {"name": self.name, "distribution": self.distribution, "version": self.version,
                "api_version": p.api_version if p is not None else None, "status": self.status, "error": self.error,
                "title": (p.title if p is not None else "") or self.name, "description": p.description if p else "",
                "url": p.url if p else "", "license": p.license if p else "", "entry_point": self.value,
                "contributions": contributions}

    def record(self, kind: str, contribution: str) -> dict:
        """How a run records its use of one contribution."""
        return {"plugin": self.name, "distribution": self.distribution, "version": self.version,
                "api_version": API_VERSION, "kind": kind, "contribution": contribution}


_lock = threading.Lock()
_cache: list[Installed] | None = None


def enabled() -> bool:
    return os.environ.get("DIGITALFLY_PLUGINS", "1").strip().lower() not in ("0", "false", "no", "off")


def _check(plugin: Plugin) -> str | None:
    """A problem with a loaded plugin's contributions, or None."""
    expected = {"sensors": Sensor, "stimuli": StimulusProgram, "scorecard_tests": ScorecardTest, "metrics": Metric,
                "commands": Command}
    for kind, kind_type in expected.items():
        names = []
        for item in getattr(plugin, kind):
            if not isinstance(item, kind_type):
                return f"{kind} holds a {type(item).__name__}, not a {kind_type.__name__}"
            if not NAME.fullmatch(item.name):
                return f"the {kind} name {item.name!r} must match {NAME.pattern}"
            names.append(item.name)
        if len(set(names)) != len(names):
            return f"two {kind} share a name"
    return None


def _load(entry) -> Installed:
    dist = getattr(entry, "dist", None)
    item = Installed(name=entry.name, distribution=dist.metadata["Name"] if dist else None,
                     version=dist.version if dist else None, value=entry.value, status="error")
    if not NAME.fullmatch(entry.name):
        item.error = f"The entry point name must match {NAME.pattern}."
        return item
    try:
        value = entry.load()
        plugin = value() if callable(value) and not isinstance(value, Plugin) else value
    except Exception as exc:  # a broken plugin is listed, never fatal
        item.error = f"{type(exc).__name__}: {exc}"
        return item
    if not isinstance(plugin, Plugin):
        item.error = f"The entry point gives a {type(plugin).__name__}, not a digitalfly.plugins.Plugin."
        return item
    item.plugin = plugin
    if plugin.api_version != API_VERSION:
        item.status, item.error = "incompatible", (f"Written for plugin API {plugin.api_version}; this DigitalFly "
                                                   f"supports API {API_VERSION}.")
        return item
    problem = _check(plugin)
    if problem:
        item.error = f"Invalid contribution: {problem}."
        return item
    item.status = "ok"
    return item


def discover(refresh: bool = False) -> list[Installed]:
    """Every installed plugin, loaded once per process (refresh=True looks again), sorted by name. Two plugins with
    one name are both marked as errors: neither can be addressed unambiguously."""
    global _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
        found = []
        if enabled():
            entries = importlib_metadata.entry_points(group=GROUP)
            found = [_load(entry) for entry in entries]
            counts = {}
            for item in found:
                counts[item.name] = counts.get(item.name, 0) + 1
            for item in found:
                if counts[item.name] > 1:
                    item.status, item.error = "error", "Another installed plugin has the same name."
        _cache = sorted(found, key=lambda i: (i.name, i.value))
        return _cache


def describe() -> dict:
    """The installed plugins as the API lists them."""
    return {"api_version": API_VERSION, "enabled": enabled(), "group": GROUP,
            "plugins": [item.describe() for item in discover()]}


def find(name: str) -> Installed:
    for item in discover():
        if item.name == name:
            if item.status != "ok":
                raise PluginError(f"The {name} plugin cannot be used: {item.error}")
            return item
    if not enabled():
        raise PluginError(f"Plugins are turned off (DIGITALFLY_PLUGINS=0), so {name} is unavailable.")
    raise PluginError(f"No plugin named {name} is installed.")


def resolve(reference: str, kind: str):
    """(installed plugin, contribution) for "plugin:contribution" of a kind (sensors, stimuli, ...)."""
    match = REFERENCE.fullmatch(reference or "")
    if not match:
        raise PluginError(f"Name a plugin contribution as plugin:name, not {reference!r}.")
    item = find(match.group(1))
    for contribution in getattr(item.plugin, kind):
        if contribution.name == match.group(2):
            return item, contribution
    singular = {"stimuli": "stimulus program", "scorecard_tests": "scorecard test"}.get(kind, kind.rstrip("s"))
    available = ", ".join(c.name for c in getattr(item.plugin, kind)) or "none"
    raise PluginError(f"The {item.name} plugin has no {singular} {match.group(2)} (it has: {available}).")


# ---------------------------------------------------------------------------------------------------------------------
# Using contributions

def sensor(reference: str) -> tuple[Installed, Sensor]:
    return resolve(reference, "sensors")


def encode(contribution: Sensor, reading: SensorReading) -> tuple[float, float]:
    """The sensor's two values, checked: finite numbers, clipped to [0, 1]."""
    values = contribution.encode(reading)
    try:
        left, right = (float(v) for v in values)
    except (TypeError, ValueError) as exc:
        raise PluginError(f"Sensor {contribution.name} must return two numbers (left, right).") from exc
    if not (math.isfinite(left) and math.isfinite(right)):
        raise PluginError(f"Sensor {contribution.name} returned a non-finite value.")
    return min(1., max(0., left)), min(1., max(0., right))


def stimulus_protocol(reference: str, **parameters) -> dict:
    """The schedule a stimulus program writes, validated as a Protocol, as a dict for RunConfig.protocol. Put the
    program's reference and parameters in RunConfig.plugins (stimulus, stimulus_parameters) so the run records it."""
    from digitalfly.api.models import Protocol
    item, program = resolve(reference, "stimuli")
    unknown = sorted(set(parameters) - set(program.parameters))
    if unknown:
        raise PluginError(f"The {reference} program has no parameter {', '.join(unknown)} "
                          f"(it takes: {', '.join(program.parameters) or 'none'}).")
    result = program.protocol(**{**program.parameters, **parameters})
    data = result.model_dump() if hasattr(result, "model_dump") else result
    return Protocol.model_validate(data).model_dump()


def used_by(config) -> list[dict]:
    """The plugin contributions a configuration uses, as its export records them (empty without plugins)."""
    choices = getattr(config, "plugins", None)
    if choices is None:
        return []
    records = []
    for kind, reference in (("sensors", choices.sensor), ("stimuli", choices.stimulus)):
        if reference:
            try:
                item, contribution = resolve(reference, kind)
                records.append(item.record(kind, contribution.name))
            except PluginError:  # recorded as asked even if the plugin is gone (the protocol replays without it)
                name, part = reference.split(":", 1)
                records.append({"plugin": name, "distribution": None, "version": None, "api_version": API_VERSION,
                                "kind": kind, "contribution": part, "installed": False})
    return records


def read_run(directory: Path) -> ExportedRun:
    """A saved run folder as metrics read it. Numbers that do not parse become NaN; text columns are left out."""
    directory = Path(directory)
    meta = json.loads((directory / "metadata.json").read_text())
    columns: dict[str, list[float]] = {}
    telemetry = directory / "telemetry.csv"
    if telemetry.is_file():
        with telemetry.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            values = [[] for _ in header]
            for row in reader:
                for k, cell in enumerate(row[:len(header)]):
                    try:
                        values[k].append(float(cell))
                    except ValueError:
                        values[k].append(math.nan)
            columns = {name: column for name, column in zip(header, values)
                       if column and not all(math.isnan(v) for v in column)}
    return ExportedRun(path=directory, metadata=meta, columns=columns)


def _plain(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if hasattr(value, "item"):  # NumPy scalars
        return _plain(value.item())
    raise PluginError(f"A metric must return a number, a dict of numbers or None, not {type(value).__name__}.")


def run_metrics(directory: Path, names: list[str] | None = None) -> dict:
    """Every installed metric (or the named plugin:metric ones) computed on a saved run. A metric that fails gives an
    error entry; the others still run. Each result names its plugin and version."""
    run = read_run(directory)
    chosen = [resolve(n, "metrics") for n in names] if names else [
        (item, metric) for item in discover() if item.status == "ok" for metric in item.plugin.metrics]
    results = []
    for item, metric in chosen:
        entry = {"metric": f"{item.name}:{metric.name}", "title": metric.title, "unit": metric.unit,
                 "plugin": item.name, "version": item.version}
        try:
            entry["value"] = _plain(metric.compute(run))
        except Exception as exc:
            entry["value"], entry["error"] = None, f"{type(exc).__name__}: {exc}"
        results.append(entry)
    return {"run": run.key, "run_id": run.metadata.get("run_id"), "api_version": API_VERSION, "metrics": results,
            "note": "Metrics come from installed plugins; they describe this simulation, not fly behavior."}


def scorecard_tests(references: list[str] | None = None) -> list[tuple[Installed, ScorecardTest]]:
    """The named plugin:test scorecard tests, or every installed one when references is empty."""
    if references:
        return [resolve(r, "scorecard_tests") for r in references]
    return [(item, test) for item in discover() if item.status == "ok" for test in item.plugin.scorecard_tests]


def commands() -> list[tuple[Installed, Command]]:
    return [(item, command) for item in discover() if item.status == "ok" for command in item.plugin.commands]
