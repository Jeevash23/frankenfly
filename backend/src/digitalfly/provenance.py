"""Provenance of saved runs: an RO-Crate 1.1 manifest, the parameter diff from defaults and a drafted methods paragraph.

Every export since schema 6 carries `ro-crate-metadata.json` (the manifest) and `methods.md` (the paragraph drafted from
it). For older runs both are built on demand from `metadata.json`; what those exports never recorded (the git commit,
the connectome's source files) is marked as not recorded, or looked up from the circuit file on disk only when its
SHA-256 still matches the run's.

The manifest is an RO-Crate (https://w3id.org/ro/crate/1.1): JSON-LD whose `@graph` holds the run folder (`./`), each
file with its SHA-256, the run as a `CreateAction`, DigitalFly and its dependencies as `SoftwareApplication`s, the
dependency locks with their hashes, the connectome release, its source files (URLs and hashes) and the circuit file,
and every setting as a `PropertyValue`: the seed, the model and sensor choice, and each parameter that differs from
the defaults. Terms schema.org lacks use the `digitalfly:` prefix declared in its `@context`.

The methods paragraph reads only the manifest, so whatever it states can be checked against the manifest.
"""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_FILE = "ro-crate-metadata.json"
METHODS_FILE = "methods.md"
REPOSITORY = "https://github.com/Jeevash23/frankenfly"
CONTEXT = ["https://w3id.org/ro/crate/1.1/context",
           {"digitalfly": "https://github.com/Jeevash23/frankenfly/blob/main/docs/SHARING.md#provenance-manifest-terms-"}]
CC_BY_NC = "https://creativecommons.org/licenses/by-nc/4.0/"
FORMATS = {".json": "application/json", ".csv": "text/csv", ".jsonl": "application/x-ndjson", ".npz": "application/zip",
           ".md": "text/markdown", ".nwb": "application/x-nwb"}
FILE_ROLES = {
    "metadata.json": "Run metadata: configuration, event schedule, provenance, metrics and software versions",
    "telemetry.csv": "One row per control step: pose, sensor values, readout activity, motor command, target, interventions",
    "body_signals.jsonl": "FlyGym body signals per control step: contact forces, CPG phase, joint angles",
    "activity_types.npz": "Mean activity of every cell type per recorded control step",
    "spikes_readout.npz": "Spike times of the readout neurons (spiking dynamics)",
    "methods.md": "Methods paragraph drafted from this manifest",
}
SETTINGS = [  # (initial_config path, name in the manifest and the methods)
    ("seed", "seed"), ("engine", "body engine"), ("sensor_model", "sensor model"), ("neural_model", "neural model"),
    ("controller", "controller"), ("connectome_parameters.circuit", "circuit"),
    ("connectome_parameters.dynamics", "dynamics"), ("record_activity", "recorded activity"),
]


def _git(*args):
    try:
        done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


@lru_cache(maxsize=1)
def code_version() -> dict:
    """DigitalFly's version, git commit and whether tracked files had changes, read once per process: the code that
    runs is what was imported when the process started. None outside a git checkout (for example in Docker)."""
    from digitalfly import __version__
    commit, status = _git("rev-parse", "HEAD"), _git("status", "--porcelain", "--untracked-files=no")
    return {"digitalfly": __version__, "git_commit": commit, "git_dirty": None if status is None else bool(status)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}{key}."))
        return out or {prefix[:-1]: {}}
    return {prefix[:-1]: value}


def parameter_diff(config: dict, defaults: dict | None = None) -> list[dict]:
    """Each setting of `config` (an initial_config) that differs from the defaults, as {parameter, value, default},
    by dotted path. Lists compare whole; a group set where the default has none (a protocol) is one entry. Defaults
    are this version's RunConfig unless given. A setting the defaults lack has default None."""
    if defaults is None:
        from digitalfly.api.models import RunConfig
        defaults = RunConfig().model_dump(mode="json")
    flat_default, flat = _flatten(defaults), _flatten(config)
    diff = []
    for path, value in flat.items():
        if path in flat_default:
            default = flat_default[path]
        else:  # a group present here but empty or None in the defaults: compare at the group
            head = next((p for p in flat_default if path.startswith(p + ".")), None)
            if head is not None and any(d["parameter"] == head for d in diff):
                continue
            if head is not None:
                path, value, default = head, _get(config, head), flat_default[head]
            else:
                default = None
        if not _same(value, default):
            diff.append({"parameter": path, "value": value, "default": default})
    # A setting the config lacks (an older export) is not recorded, so it is no difference.
    return sorted(diff, key=lambda d: d["parameter"])


def _get(data: dict, path: str):
    for key in path.split("."):
        data = data.get(key) if isinstance(data, dict) else None
    return data


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
    return a == b


def _jsonable(value):
    """A PropertyValue's value: numbers, text and booleans as they are, anything else as compact JSON text."""
    return value if isinstance(value, (str, int, float, bool)) or value is None else json.dumps(value, separators=(",", ":"))


def _circuit_sources(meta: dict) -> tuple[list, dict | None, str]:
    """The connectome's source files and build settings: as recorded (schema 6), else from the circuit file on disk
    when its SHA-256 matches the run's, else none. Returns (sources, build, how)."""
    if meta.get("connectome_sources") is not None:
        recorded = meta["connectome_sources"]
        return recorded.get("sources") or [], recorded.get("build"), "recorded at export"
    neural = meta.get("neural") or {}
    if neural.get("kind") != "connectome" or not neural.get("circuit"):
        return [], None, "no connectome"
    try:
        from digitalfly.neural.connectome import load_circuit
        data = load_circuit(neural["circuit"])
    except (OSError, ValueError, KeyError):
        return [], None, "circuit file not found; not recorded by this export"
    if data.sha256 != neural.get("circuit_sha256"):
        return [], None, "circuit file on disk has changed since; not recorded by this export"
    return data.provenance.get("sources") or [], data.provenance.get("build"), "read from the matching circuit file"


def _license(meta: dict) -> dict:
    neural, vision = meta.get("neural") or {}, meta.get("vision") or {}
    if neural.get("kind") == "connectome" or vision.get("bridge") or vision.get("flyvis"):
        return {"@id": CC_BY_NC, "@type": "CreativeWork", "name": "CC BY-NC 4.0",
                "description": "FlyWire-derived data: non-commercial use only, with credit to the FlyWire Consortium"}
    return {"@id": "#license-not-chosen", "@type": "CreativeWork", "name": "No license chosen yet",
            "description": "This run contains no FlyWire-derived data. Choose a license before publishing it."}


def _file_entity(name: str, path: Path | None, size: int | None = None, digest: str | None = None) -> dict:
    entity = {"@id": name, "@type": "File", "name": name, "encodingFormat": FORMATS.get(Path(name).suffix, "application/octet-stream"),
              "description": FILE_ROLES.get(name, "Run file")}
    if path is not None:
        size, digest = path.stat().st_size, sha256(path)
    if size is not None:
        entity["contentSize"] = str(size)
    if digest is not None:
        entity["sha256"] = digest
    return entity


def build_manifest(meta: dict, files: dict[str, Path | None], key: str | None = None) -> dict:
    """The RO-Crate manifest of a run, from its metadata and its files (name → path; a None path lists the file
    without size or hash)."""
    config, neural = meta.get("initial_config") or {}, meta.get("neural") or {}
    prov = meta.get("provenance") or {}
    code = meta.get("code") or {"digitalfly": meta.get("application_version"), "git_commit": None, "git_dirty": None}
    connectome = neural.get("kind") == "connectome"
    graph, run_objects = [], []
    license_entity = _license(meta)
    file_entities = [_file_entity(name, path) for name, path in files.items()]
    schema = meta.get("schema_version")

    software = {"@id": "#digitalfly", "@type": "SoftwareApplication", "name": "DigitalFly", "url": REPOSITORY,
                "version": code.get("digitalfly") or meta.get("application_version"),
                "digitalfly:gitCommit": code.get("git_commit") or "not recorded",
                "digitalfly:gitDirty": code.get("git_dirty") if code.get("git_dirty") is not None else "not recorded",
                "softwareRequirements": []}
    dependencies = []
    for name, version in sorted((meta.get("dependencies") or {}).items()):
        dependencies.append({"@id": f"#dependency-{name}", "@type": "SoftwareApplication", "name": name, "version": version})
    if meta.get("python"):
        dependencies.append({"@id": "#dependency-python", "@type": "SoftwareApplication", "name": "Python",
                             "version": meta["python"]})
    locks = [{"@id": f"#lock-{name}", "@type": "CreativeWork", "name": name, "sha256": digest or "missing",
              "description": "Hashed dependency lock the environment was installed from (backend/)"}
             for name, digest in sorted((meta.get("lockfiles") or {}).items())]
    software["softwareRequirements"] = [{"@id": e["@id"]} for e in dependencies + locks]

    settings = []
    for path, name in SETTINGS:
        if path.startswith("connectome_parameters.") and not connectome:
            continue
        value = _get(config, path)
        if value is not None:
            settings.append({"@id": f"#setting-{path}", "@type": "PropertyValue", "name": name, "propertyID": path,
                             "value": _jsonable(value)})
    stimulus = config.get("stimulus") or {}
    settings.append({"@id": "#setting-stimulus", "@type": "PropertyValue", "name": "initial target",
                     "propertyID": "stimulus", "value": _jsonable(stimulus), "unitText": "mm (x, y); intensity 0-2"})
    steps = meta.get("time_steps_s") or {}
    for name, value in steps.items():
        settings.append({"@id": f"#timestep-{name}", "@type": "PropertyValue", "name": f"{name} time step",
                         "propertyID": f"time_steps_s.{name}", "value": value, "unitCode": "SEC"})
    metrics = meta.get("metrics") or {}
    settings.append({"@id": "#duration", "@type": "PropertyValue", "name": "simulated duration", "propertyID": "metrics.duration_s",
                     "value": metrics.get("duration_s"), "unitCode": "SEC"})
    settings.append({"@id": "#samples", "@type": "PropertyValue", "name": "recorded samples",
                     "propertyID": "recorded_samples", "value": meta.get("recorded_samples")})
    recorded_diff = meta.get("parameter_diff")
    diff = recorded_diff if recorded_diff is not None else parameter_diff(config)
    diff_entities = [{"@id": f"#changed-{d['parameter']}", "@type": "PropertyValue", "name": d["parameter"],
                      "propertyID": d["parameter"], "value": _jsonable(d["value"]),
                      "digitalfly:default": _jsonable(d["default"])} for d in diff]
    schedule = _schedule(meta)
    schedule_entities = [{"@id": f"#change-{i}", "@type": "PropertyValue", "name": f"{item['kind']} at {item['t']:g} s",
                          "propertyID": item["kind"], "value": _jsonable(item["value"]),
                          "digitalfly:step": item["step"], "digitalfly:source": item["source"]}
                         for i, item in enumerate(schedule)]

    models = [{"@id": f"#model-{name}", "@type": "CreativeWork", "name": name.replace("_", " "), "description": text}
              for name, text in prov.items() if isinstance(text, str)]
    if connectome:
        detail = {k: neural.get(k) for k in ("dynamics", "neurons", "cell_types", "connections_active", "connections_total",
                                             "excluded_below_threshold", "excluded_by_sign_assumption", "readout_units",
                                             "equation", "output_mapping", "input_mapping")}
        models.append({"@id": "#model-connectome", "@type": "CreativeWork", "name": "connectome model",
                       "description": neural.get("equation", ""),
                       **{f"digitalfly:{k}": _jsonable(v) for k, v in detail.items() if v is not None},
                       "digitalfly:signs": _jsonable(neural.get("signs")),
                       "digitalfly:readout": _jsonable([r.get("cell_type") for r in neural.get("readout", [])])})
    run_objects += [{"@id": e["@id"]} for e in settings + diff_entities + schedule_entities + models]

    if connectome:
        sources, build, how = _circuit_sources(meta)
        source_entities = []
        for source in sources:
            entity = {"@id": source.get("url") or f"#source-{source.get('name')}", "@type": "File",
                      "name": source.get("name"), "description": source.get("content"), "version": source.get("release"),
                      "publisher": source.get("provider"), "license": source.get("license"),
                      "sha256": source.get("sha256"), "contentSize": str(source["bytes"]) if source.get("bytes") else None,
                      "digitalfly:hashScope": source.get("hash_scope"), "digitalfly:retrieved": source.get("retrieved_utc"),
                      "digitalfly:gitCommit": source.get("git_commit")}
            source_entities.append({k: v for k, v in entity.items() if v is not None})
        dataset, release = (neural.get("dataset") or "").split(" · ")[0], None
        dataset_entity = {"@id": "#connectome", "@type": "Dataset", "name": dataset or "connectome",
                          "description": neural.get("coverage"), "license": neural.get("license"),
                          "hasPart": [{"@id": e["@id"]} for e in source_entities],
                          "digitalfly:sources": how}
        circuit = {"@id": "#circuit", "@type": "CreativeWork", "name": neural.get("circuit"),
                   "description": neural.get("circuit_name"), "sha256": neural.get("circuit_sha256"),
                   "digitalfly:file": neural.get("circuit_file"), "isBasedOn": {"@id": "#connectome"},
                   "digitalfly:build": _jsonable(build) if build else "not recorded"}
        graph += [dataset_entity, circuit, *source_entities]
        run_objects += [{"@id": "#connectome"}, {"@id": "#circuit"}]
    vision = meta.get("vision") or {}
    if vision.get("flyvis"):
        flyvis = vision["flyvis"]
        graph.append({"@id": "#flyvis", "@type": "SoftwareApplication", "name": "FlyVis network",
                      "description": _jsonable({k: v for k, v in flyvis.items() if k not in ("checkpoint_sha256",)}),
                      "sha256": flyvis.get("checkpoint_sha256")})
        run_objects.append({"@id": "#flyvis"})
    if vision.get("bridge"):
        bridge = vision["bridge"]
        graph.append({"@id": "#flyvis-bridge", "@type": "CreativeWork", "name": bridge.get("file"),
                      "sha256": bridge.get("sha256"), "description": "FlyVis → circuit input bridge (FlyWire v783 synapse counts)"})
        run_objects.append({"@id": "#flyvis-bridge"})

    status = meta.get("status")
    action = {"@id": "#run", "@type": "CreateAction", "name": f"DigitalFly closed-loop run {meta.get('run_id')}",
              "identifier": meta.get("run_id"), "startTime": meta.get("created_utc"), "endTime": meta.get("exported_utc"),
              "actionStatus": {"@id": "http://schema.org/FailedActionStatus" if status == "error"
                               else "http://schema.org/CompletedActionStatus"},
              "instrument": {"@id": "#digitalfly"}, "object": run_objects,
              "result": [{"@id": e["@id"]} for e in file_entities]}
    if meta.get("error"):
        action["error"] = meta["error"]
    root = {"@id": "./", "@type": "Dataset", "name": f"DigitalFly run {meta.get('run_id')}",
            "description": "A closed-loop simulation of an embodied fly saved by DigitalFly. Structure is data-derived "
                           "where a connectome is used; signs are assumed and the sensor and motor mappings are "
                           "engineered. Results describe this simulation, not flies.",
            "identifier": key or meta.get("run_id"), "dateCreated": meta.get("created_utc"),
            "datePublished": meta.get("exported_utc"), "license": {"@id": license_entity["@id"]},
            "hasPart": [{"@id": e["@id"]} for e in file_entities], "mentions": {"@id": "#run"},
            "digitalfly:schemaVersion": schema, "digitalfly:shareSafe": bool(meta.get("share_safe")),
            "digitalfly:reproducibility": meta.get("reproducibility")}
    descriptor = {"@id": MANIFEST_FILE, "@type": "CreativeWork", "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                  "about": {"@id": "./"}}
    graph = [descriptor, root, *file_entities, action, software, *dependencies, *locks, license_entity, *settings,
             *diff_entities, *schedule_entities, *models, *graph]
    return {"@context": CONTEXT, "@graph": graph}


def add_file(manifest: dict, name: str, path: Path) -> dict:
    """List one more file in a manifest: in the graph, the folder's parts and the run's results."""
    graph = manifest["@graph"]
    entity = _file_entity(name, path)
    graph[:] = [e for e in graph if e.get("@id") != name]
    graph.insert(2, entity)
    for node in graph:
        if node.get("@id") == "./":
            node["hasPart"] = [p for p in node["hasPart"] if p["@id"] != name] + [{"@id": name}]
        if node.get("@id") == "#run":
            node["result"] = [p for p in node["result"] if p["@id"] != name] + [{"@id": name}]
    return manifest


def _schedule(meta: dict) -> list[dict]:
    """The input changes a replay re-applies: each stimulus, interventions and parameter event, in order."""
    out = []
    for event in meta.get("events") or []:
        if event.get("kind") in {"stimulus", "interventions", "parameters", "connectome_parameters"}:
            payload = {k: v for k, v in (event.get("payload") or {}).items() if k != "source"}
            out.append({"kind": event["kind"], "step": event.get("step"), "t": event.get("t") or 0,
                        "source": (event.get("payload") or {}).get("source", "manual"), "value": payload})
    return out


# The methods paragraph ---------------------------------------------------------------------------------------------

def _graph(manifest: dict) -> dict:
    return {node["@id"]: node for node in manifest["@graph"]}


def _value(node: dict | None):
    if node is None:
        return None
    value = node.get("value")
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _setting(nodes: dict, path: str):
    return _value(nodes.get(f"#setting-{path}"))


def _number(value) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:g}"
    return f"{int(value):,}" if isinstance(value, (int, float)) else str(value)


def _short(text: str | None, limit=12) -> str:
    return text[:limit] if isinstance(text, str) and text not in ("not recorded", "missing") else "not recorded"


def _describe_change(item: dict) -> str:
    value = item.get("value")
    return f"{item['parameter']} = {json.dumps(value) if not isinstance(value, str) else value}" \
        f" (default {json.dumps(item['default']) if not isinstance(item['default'], str) else item['default']})"


def methods_facts(manifest: dict) -> dict:
    """What the methods paragraph states, read from the manifest."""
    nodes = _graph(manifest)
    software, root = nodes.get("#digitalfly", {}), nodes.get("./", {})
    deps = {nodes[r["@id"]]["name"]: nodes[r["@id"]].get("version") for r in software.get("softwareRequirements", [])
            if r["@id"].startswith("#dependency-") and r["@id"] in nodes}
    locks = {nodes[r["@id"]]["name"]: nodes[r["@id"]].get("sha256") for r in software.get("softwareRequirements", [])
             if r["@id"].startswith("#lock-") and r["@id"] in nodes}
    changed = [{"parameter": n["name"], "value": _value(n), "default": _value({"value": n.get("digitalfly:default")})}
               for k, n in nodes.items() if k.startswith("#changed-")]
    schedule = [{"kind": n["propertyID"], "step": n.get("digitalfly:step"), "source": n.get("digitalfly:source"),
                 "name": n["name"], "value": _value(n)} for k, n in nodes.items() if k.startswith("#change-")]
    models = {k.removeprefix("#model-"): n for k, n in nodes.items() if k.startswith("#model-")}
    return {"run_id": nodes.get("#run", {}).get("identifier"), "version": software.get("version"),
            "commit": software.get("digitalfly:gitCommit"), "dirty": software.get("digitalfly:gitDirty"),
            "dependencies": deps, "locks": locks, "seed": _setting(nodes, "seed"), "engine": _setting(nodes, "engine"),
            "sensor": _setting(nodes, "sensor_model"), "neural": _setting(nodes, "neural_model"),
            "controller": _setting(nodes, "controller"), "circuit": _setting(nodes, "connectome_parameters.circuit"),
            "dynamics": _setting(nodes, "connectome_parameters.dynamics"),
            "stimulus": _value(nodes.get("#setting-stimulus")) or {},
            "steps": {k.removeprefix("#timestep-"): n.get("value") for k, n in nodes.items() if k.startswith("#timestep-")},
            "duration": nodes.get("#duration", {}).get("value"), "samples": nodes.get("#samples", {}).get("value"),
            "changed": changed, "schedule": schedule, "models": models, "connectome": nodes.get("#connectome"),
            "circuit_node": nodes.get("#circuit"), "sources": [nodes[p["@id"]] for p in nodes.get("#connectome", {}).get("hasPart", [])
                                                               if p["@id"] in nodes],
            "flyvis": nodes.get("#flyvis"), "license": nodes.get(root.get("license", {}).get("@id"), {}),
            "status": nodes.get("#run", {}).get("actionStatus", {}).get("@id", "").rsplit("/", 1)[-1]}


def _model_text(models: dict, name: str) -> str | None:
    node = models.get(name)
    return node.get("description") if node else None


def _strip(text: str) -> str:
    """A provenance label as prose: "X · engineered" → "X (engineered)", "X · v1" → "X (v1)", other dots → commas."""
    for label in ("engineered", "v1"):
        if text.endswith(f" · {label}"):
            text = text[:-len(label) - 3] + f" ({label})"
    return text.replace(" · ", ", ").rstrip(".")


def _lower(text: str) -> str:
    return text[0].lower() + text[1:] if text[:2] != text[:2].upper() else text


CHANGE_NAMES = {"stimulus": "target change", "interventions": "intervention change", "parameters": "parameter edit",
                "connectome_parameters": "connectome parameter edit"}


def methods_paragraph(manifest: dict) -> str:
    """A methods paragraph for one run, drafted from its manifest. Review it before use: it describes the software
    configuration, not a scientific conclusion."""
    f = methods_facts(manifest)
    sentences = []
    code = f"DigitalFly {f['version']}" + (f" (git commit {_short(f['commit'])}" + (", with uncommitted changes" if f["dirty"] is True else "") + ")"
                                           if _short(f["commit"]) != "not recorded" else "")
    flygym = f["engine"] == "flygym"
    motor = _lower(_strip(_model_text(f["models"], "motor_controller") or "an engineered controller"))
    if flygym:
        body = _strip(_model_text(f["models"], "body_engine") or "FlyGym")
        body = f"The body was simulated with {body} (female-derived morphology) and walked with the {motor}."
    else:
        body = f"The body was a kinematic toy body, not FlyGym physics, moved by a {motor}."
    sentences.append(f"We simulated an embodied fly in closed loop with {code}. {body}")
    sensor = _model_text(f["models"], "sensor_model")
    if sensor:
        sentences.append(f"Sensory input came from {'a ' * sensor.startswith('Geometric')}{_lower(_strip(sensor))}.")
    if f["neural"] == "connectome" and f["circuit_node"]:
        model = f["models"].get("connectome", {})
        neurons, connections = model.get("digitalfly:neurons"), model.get("digitalfly:connections_active")
        dataset = (f["connectome"] or {}).get("name") or "a connectome"
        spiking = f["dynamics"] == "spiking"
        dyn = ("leaky integrate-and-fire neurons with the parameters of Shiu et al. (2024), stepped at 0.1 ms"
               if spiking else "leaky rate units (Euler step 1 ms)")
        coverage = (f["connectome"] or {}).get("description")
        sentences.append(
            f"The neural model was a connectome-constrained network of {_number(neurons)} neurons and "
            f"{_number(connections)} connections taken from {dataset} (circuit {f['circuit']}, SHA-256 "
            f"{_short(f['circuit_node'].get('sha256'))}…" + (f"; {coverage}" if coverage else "") + f"), simulated as {dyn}. "
            "Connectivity was data-derived, synaptic signs were assumed from predicted neurotransmitters "
            "(acetylcholine excitatory; GABA and glutamate inhibitory), and the sensory input and motor readout were engineered.")
        readout = _value({"value": model.get("digitalfly:readout")})
        if readout:
            sentences.append(f"Turning was read out from the right-minus-left activity of {', '.join(readout)}, "
                             "with the sign from Rayshubskiy et al. (2025).")
        sources = [s for s in f["sources"] if s.get("name")]
        if sources:
            listed = "; ".join(f"{s['name']}" + (f" ({s['version']})" if s.get("version") else "")
                               + (f", SHA-256 {s['sha256'][:12]}…" if s.get("sha256") else "") for s in sources)
            sentences.append(f"The circuit was built from {listed}.")
    else:
        sentences.append(f"The neural model was {_strip(_model_text(f['models'], 'neural_model') or 'the engineered circuit')}.")
    if f["controller"] == "baseline":
        sentences.append("This was a controller-only baseline: neural output was bypassed.")
    steps = f["steps"]
    timing = ", ".join(f"{name} {value * 1000:g} ms" for name, value in steps.items() if isinstance(value, (int, float)))
    stimulus = f["stimulus"]
    target = (f"a target at ({stimulus.get('x', 0):g}, {stimulus.get('y', 0):g}) mm with intensity {stimulus.get('intensity', 1):g}"
              if stimulus else "a target")
    duration = f["duration"]
    sentences.append(f"Time steps were {timing}. The run used seed {f['seed']} and {target}, and lasted "
                     f"{duration:g} s of simulated time ({_number(f['samples'])} recorded samples)."
                     if isinstance(duration, (int, float)) else f"Time steps were {timing}; the run used seed {f['seed']}.")
    manual = [s for s in f["schedule"]]
    if manual:
        kinds = {}
        for item in manual:
            kinds.setdefault(item["kind"], []).append(item)
        parts = [f"{len(items)} {CHANGE_NAMES.get(kind, kind)}{'s' * (len(items) != 1)}" for kind, items in kinds.items()]
        protocol = any(item["source"] == "protocol" for item in manual)
        sentences.append(f"During the run, {', '.join(parts)} were applied at fixed control steps"
                         + (" by a protocol" if protocol else "") + "; the full schedule is in the run's metadata and manifest.")
    changed = [c for c in f["changed"] if c["parameter"] not in {"seed", "stimulus.x", "stimulus.y", "stimulus.intensity"}]
    if changed:
        sentences.append("Settings that differed from the defaults: " + "; ".join(_describe_change(c) for c in changed[:12])
                         + (f"; and {len(changed) - 12} more (see the manifest)" if len(changed) > 12 else "") + ".")
    else:
        sentences.append("All other settings were the defaults.")
    deps = f["dependencies"]
    stack = ", ".join(f"{name} {deps[name]}" for name in ("Python", "flygym", "mujoco", "numpy", "scipy", "numba", "torch", "flyvis")
                      if name in deps)
    if stack:
        sentences.append(f"Software: {stack}" + (f"; hashed dependency locks in the checkout: {', '.join(f'{k} {_short(v)}…' for k, v in f['locks'].items())}"
                                                  if f["locks"] else "") + ".")
    sentences.append("A run replays exactly from its seed and step-indexed input schedule on the same software stack "
                     "(absolute tolerance 1e-8).")
    if f["status"] == "FailedActionStatus":
        sentences.append("Note: this run ended in an error state.")
    return " ".join(sentences)


def methods_markdown(manifest: dict) -> str:
    facts = methods_facts(manifest)
    lines = [f"# Methods draft: run {facts['run_id']}", "", methods_paragraph(manifest), ""]
    if facts["license"].get("name"):
        lines += [f"Data license: {facts['license']['name']}. {facts['license'].get('description', '')}".rstrip(), ""]
    lines += ["Drafted automatically by DigitalFly from `ro-crate-metadata.json`. Check it against your question and "
              "edit before publishing: it states what the software did, not what the results mean.", ""]
    return "\n".join(lines)


def comparison_paragraph(manifests: list[dict], conditions: dict[str, str] | None = None,
                         statistics: dict[str, str] | None = None) -> str:
    """A methods paragraph for several runs (a comparison): what all of them share, from the first run's paragraph
    style, then what varies between them and how they were summarized. `conditions` maps run_id → condition."""
    if not manifests:
        raise ValueError("No runs to describe.")
    facts = [methods_facts(m) for m in manifests]
    changed = [{c["parameter"]: c["value"] for c in f["changed"]} for f in facts]
    keys = sorted(set().union(*changed))
    shared = {k: changed[0].get(k) for k in keys if all(_same(c.get(k), changed[0].get(k)) for c in changed)}
    varying = [k for k in keys if k not in shared and k != "seed"]
    seeds = sorted({f["seed"] for f in facts if f["seed"] is not None})
    first = methods_paragraph(manifests[0])
    # Drop the single-run sentences (seed, schedule, the defaults list): restated below for the whole set.
    keep = [s for s in _sentences(first) if not s.startswith(("Time steps were", "The run used", "During the run", "Settings that differed",
                                                               "All other settings", "Note: this run"))]
    sentences = keep
    steps = facts[0]["steps"]
    sentences.append("Time steps were " + ", ".join(f"{k} {v * 1000:g} ms" for k, v in steps.items()
                                                     if isinstance(v, (int, float))) + ".")
    by_condition = {}
    for f in facts:
        by_condition.setdefault((conditions or {}).get(f["run_id"], "all runs"), []).append(f)
    durations = sorted({f["duration"] for f in facts if isinstance(f["duration"], (int, float))})
    sentences.append(f"We compared {len(facts)} runs" + (f" in {len(by_condition)} conditions" if conditions else "")
                     + f" with seeds {', '.join(map(str, seeds))}"
                     + (f", each lasting {durations[0]:g} s of simulated time" if len(durations) == 1 else "") + ".")
    if conditions:
        sentences.append("Conditions: " + "; ".join(f"{name} (n = {len(items)})" for name, items in by_condition.items()) + ".")
    if varying:
        sentences.append("Settings that varied between runs: " + ", ".join(varying) + ".")
    shared_list = [{"parameter": k, "value": v, "default": next(c["default"] for c in facts[0]["changed"] if c["parameter"] == k)}
                   for k, v in shared.items() if k not in {"seed", "stimulus.x", "stimulus.y", "stimulus.intensity"}]
    if shared_list:
        sentences.append("Settings shared by every run that differed from the defaults: "
                         + "; ".join(_describe_change(c) for c in shared_list[:12]) + ".")
    if statistics:
        sentences.append("Statistics: " + "; ".join(f"{k}: {v}" for k, v in statistics.items()) + ".")
    return " ".join(sentences)


def _sentences(text: str) -> list[str]:
    import re
    return [s for s in re.split(r"(?<=[.)])\s+(?=[A-Z])", text) if s]


# Saved runs ---------------------------------------------------------------------------------------------------------

def run_files(directory: Path) -> dict[str, Path]:
    """The run files a manifest lists, in a fixed order: every regular file of the folder except the manifest, the
    library's own notes and replay verdicts, and NWB files made later."""
    skip = {MANIFEST_FILE, "annotations.json", "verification.json"}
    return {p.name: p for p in sorted(directory.iterdir())
            if p.is_file() and not p.is_symlink() and p.name not in skip and not p.name.startswith(".") and p.suffix != ".nwb"}


def run_manifest(directory: Path, hash_files: bool = True) -> dict:
    """A saved run's manifest: the one exported with it (schema 6 and later), else built from its metadata.json."""
    stored = directory / MANIFEST_FILE
    if stored.is_file() and not stored.is_symlink():
        return json.loads(stored.read_text())
    meta = json.loads((directory / "metadata.json").read_text())
    files = run_files(directory)
    files.pop(METHODS_FILE, None)
    manifest = build_manifest(meta, files if hash_files else dict.fromkeys(files), directory.name)
    for node in manifest["@graph"]:
        if node["@id"] == "./":
            node["digitalfly:manifestBuilt"] = ("after export, from metadata.json (this run predates manifests); "
                                                "the git commit was not recorded")
    return manifest


def run_methods(directory: Path) -> str:
    stored = directory / METHODS_FILE
    if stored.is_file() and not stored.is_symlink():
        return stored.read_text()
    return methods_markdown(run_manifest(directory, hash_files=False))
