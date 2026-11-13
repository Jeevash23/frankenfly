"""NWB export of a saved run (optional: needs pynwb, from backend/requirements-nwb.lock).

    from digitalfly import nwb
    path = nwb.export_run(Path("runs/<run key>"))        # runs/<run key>/<run key>.nwb
    nwb.validate(path)                                     # [] when pynwb's validator finds nothing

What goes where (NWB 2.x core types only, no extensions):
  acquisition    nothing: no instrument recorded anything
  stimulus       target_position (x, y; m) and target_intensity, piecewise constant: each value holds from its timestamp
                 until the next one
  processing/behavior   Position/body_position (x, y, z; m), CompassDirection/heading (yaw; rad),
                 BehavioralTimeSeries: speed (m/s), motor_command (left, right; dimensionless) and, for the FlyGym
                 body, joint angles, ground contact forces and CPG phases
  processing/model      sensor_input (left, right) and raw_sensor_input, readout_activity (one column per recorded
                 readout: each side of every readout cell type, the input population, the circuit mean, the speed
                 drive) with a readout_columns table naming each column's cell type, side and FlyWire root IDs; and,
                 when the run recorded it, cell_type_activity with a cell_types table
  units          the readout neurons' spike times (spiking runs since export schema 6), with cell type, side and
                 FlyWire root ID
  intervals/interventions   one row per interval of constant interventions: its code (as in telemetry.csv) and the
                 full interventions as JSON
  scratch        digitalfly_manifest: the run's RO-Crate provenance manifest (JSON)

Positions are stored in millimetres with conversion 0.001 to metres, so data × conversion is in NWB's SI units.
Spiking readout activity is firing rate ÷ the rate scale, stored with conversion = rate scale, so it reads in Hz.
Works for every saved run the library lists (export schema 2 and later): older runs lack only what they never
recorded (spike times, per-type activity, target columns, which are rebuilt from the event schedule).
"""
from datetime import datetime
import csv
import json
import math
from pathlib import Path
import numpy as np
from digitalfly import provenance

SPECIES = "Drosophila melanogaster"
NCBI_TAXON = "http://purl.obolibrary.org/obo/NCBITaxon_7227"
FRAME = "World frame of the simulation: right-handed, +z up, origin at the arena centre; yaw counterclockwise from +x"


def available() -> bool:
    try:
        import pynwb  # noqa: F401
    except ImportError:
        return False
    return True


def _require():
    try:
        import pynwb
    except ImportError as exc:
        raise RuntimeError("NWB export needs pynwb: backend/.venv/bin/python -m pip install --require-hashes "
                           "-r backend/requirements-nwb.lock") from exc
    return pynwb


def _telemetry(path: Path) -> tuple[list[str], dict[str, np.ndarray]]:
    with path.open(newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        rows = list(reader)
    columns = {}
    for i, name in enumerate(header):
        values = [row[i] if i < len(row) else "" for row in rows]
        if name == "intervention_code":
            columns[name] = np.array(values, dtype=object)
            continue
        columns[name] = np.array([float(v) if v not in ("", None) else math.nan for v in values], dtype=np.float64)
    return header, columns


def _compressed(data):
    from hdmf.backends.hdf5.h5_utils import H5DataIO
    array = np.asarray(data)
    return H5DataIO(array, compression="gzip", compression_opts=4) if array.size > 1024 else array


def _schedule(meta: dict, kind: str, initial):
    """[(t, step, value, source)] for one input kind: the initial value at t = 0, then each logged change at the time
    of the step it was made in (it applies to that step's control interval and after)."""
    out = [(0.0, 0, initial, "initial")]
    for event in meta.get("events") or []:
        if event.get("kind") == kind:
            payload = dict(event.get("payload") or {})
            source = payload.pop("source", "manual")
            out.append((float(event.get("t") or 0), int(event.get("step") or 0), payload, source))
    merged = []
    for item in out:  # a change at the same step replaces the previous value
        if merged and merged[-1][1] == item[1] and item[3] != "initial":
            merged[-1] = item
        else:
            merged.append(item)
    return merged


def _code(interventions: dict) -> str:
    from digitalfly.api.models import Interventions
    from digitalfly.simulation.experiment import intervention_code
    try:
        return intervention_code(Interventions.model_validate(interventions))
    except ValueError:
        return "unparsed"


def _readout_rows(meta: dict, names: list[str]) -> list[dict]:
    neural = meta.get("neural") or {}
    readout = {r["cell_type"]: r for r in neural.get("readout") or []}
    inputs = (neural.get("input_population") or {}).get("cell_types")
    inputs = ", ".join(inputs) if isinstance(inputs, list) else inputs
    rows = []
    for name in names:
        base, side = (name[:-2], {"L": "left", "R": "right"}[name[-1]]) if name[-2:] in (" L", " R") else (name, "both")
        ids = []
        if base in readout:
            ids, kind = readout[base].get(side, []), "readout cell type"
        elif base in ("Visual input", "Input"):
            base, kind = inputs or base, "input population"
        elif base == "Circuit mean":
            base, kind = "all neurons of the circuit", "circuit mean"
        elif base == "Speed drive":
            base, kind = ", ".join(neural.get("speed_population") or []) or base, "speed population"
        else:
            kind = "engineered unit"
        rows.append({"column": name, "cell_type": base, "side": side, "kind": kind, "root_ids": " ".join(map(str, ids))})
    return rows


def build(directory: Path):
    """The NWBFile of a saved run folder."""
    pynwb = _require()
    from pynwb import NWBFile, TimeSeries
    from pynwb.behavior import BehavioralTimeSeries, CompassDirection, Position
    from pynwb.epoch import TimeIntervals
    from pynwb.file import Subject
    from hdmf.common import DynamicTable, VectorData

    meta = json.loads((directory / "metadata.json").read_text())
    manifest = provenance.run_manifest(directory, hash_files=False)
    methods = provenance.methods_paragraph(manifest)
    config, neural = meta.get("initial_config") or {}, meta.get("neural") or {}
    header, columns = _telemetry(directory / "telemetry.csv")
    n = len(columns["step"])
    dt = (meta.get("time_steps_s") or {}).get("control", .01)
    time = columns["time_s"]
    regular = n < 2 or np.allclose(np.diff(time), dt, atol=1e-9)
    timing = {"starting_time": float(time[0]) if n else 0.0, "rate": 1 / dt} if regular else {"timestamps": time}
    flygym = config.get("engine") == "flygym"
    connectome = neural.get("kind") == "connectome"
    code = meta.get("code") or {}
    citations = (meta.get("connectome_sources") or {}).get("citations") or []
    dois = sorted({"doi:" + c.split("doi:")[1].strip().rstrip(".") for c in citations if "doi:" in c})

    nwb = NWBFile(
        session_description=f"DigitalFly closed-loop simulation {meta['run_id']}: "
                            + ("connectome" if connectome else "engineered") + " brain, "
                            + ("FlyGym body" if flygym else "toy body") + f", seed {config.get('seed')}",
        identifier=directory.name, session_id=meta["run_id"],
        session_start_time=datetime.fromisoformat(meta["created_utc"]),
        experiment_description=methods,
        data_collection="Simulated, not recorded: every signal comes from the DigitalFly model. Results describe this "
                        "simulation, not flies.",
        source_script=f"DigitalFly {meta.get('application_version')}"
                      + (f" (git {code['git_commit']})" if code.get("git_commit") else "") + f"; {provenance.REPOSITORY}",
        source_script_file_name="digitalfly", keywords=["Drosophila", "simulation", "closed loop", "embodied"]
                                                         + (["connectome", "FlyWire"] if connectome else []),
        related_publications=dois or None,
        notes=f"Export schema {meta.get('schema_version')}; provenance manifest in scratch/digitalfly_manifest.",
    )
    nwb.subject = Subject(subject_id="digitalfly-simulated-fly", species=SPECIES, sex="F" if flygym else "U",
                          description="A simulated fly, not an animal: "
                                      + ((meta.get("provenance") or {}).get("body_sex") or "body model"))

    # Stimulus: the target, piecewise constant from each change.
    stimulus = _schedule(meta, "stimulus", config.get("stimulus") or {})
    t_stim = np.array([s[0] for s in stimulus])
    xy = np.array([[s[2].get("x", math.nan), s[2].get("y", math.nan)] for s in stimulus])
    nwb.add_stimulus(TimeSeries(name="target_position", data=xy, timestamps=t_stim, unit="meters", conversion=1e-3,
                                description="Target (green object) position (x, y), stored in mm; each value holds from "
                                            "its timestamp until the next. " + FRAME,
                                comments="Applied from the control interval starting at each timestamp."))
    nwb.add_stimulus(TimeSeries(name="target_intensity", data=np.array([s[2].get("intensity", math.nan) for s in stimulus]),
                                timestamps=t_stim, unit="n.a.",
                                description="Target intensity (dimensionless, 0-2), piecewise constant like target_position."))

    # Behavior.
    behavior = nwb.create_processing_module("behavior", "Body kinematics of the simulated fly, per control step")
    position = Position(name="Position")
    position.create_spatial_series(name="body_position", data=_compressed(np.column_stack([columns["x_mm"], columns["y_mm"],
                                                                                             columns["z_mm"]])),
                                   reference_frame=FRAME, unit="meters", conversion=1e-3,
                                   description="Thorax position (x, y, z), stored in mm", **timing)
    behavior.add(position)
    compass = CompassDirection(name="CompassDirection")
    compass.create_spatial_series(name="heading", data=_compressed(columns["yaw_rad"]), reference_frame=FRAME,
                                  unit="radians", description="Body yaw, counterclockwise from +x", **timing)
    behavior.add(compass)
    series = [TimeSeries(name="speed", data=_compressed(columns["speed_mm_s"]), unit="m/s", conversion=1e-3,
                         description="Forward speed, stored in mm/s", **timing),
              TimeSeries(name="motor_command", data=_compressed(np.column_stack([columns["motor_l"], columns["motor_r"]])),
                         unit="n.a.", description="Descending motor command (left, right) sent to the walking "
                                                  "controller; dimensionless amplitudes, 1.4 × clip(command, 0, 1)",
                         **timing)]
    signals = directory / "body_signals.jsonl"
    if signals.is_file():
        series += _body_series(signals, meta, TimeSeries)
    behavior.add(BehavioralTimeSeries(name="BehavioralTimeSeries", time_series=series))

    # The neural model.
    model = nwb.create_processing_module("model", "Inputs and activity of the simulated nervous system")
    model.add(TimeSeries(name="sensor_input", data=_compressed(np.column_stack([columns["sensor_l"], columns["sensor_r"]])),
                         unit="n.a.", description="Bilateral sensor values (left, right) after input interventions, "
                                                  "dimensionless 0-1: what the neural model received", **timing))
    model.add(TimeSeries(name="raw_sensor_input",
                         data=_compressed(np.column_stack([columns["raw_sensor_l"], columns["raw_sensor_r"]])),
                         unit="n.a.", description="Bilateral sensor values before interventions", **timing))
    names = list(neural.get("unit_names") or [c.removeprefix("rate_") for c in header if c.startswith("rate_")])
    rate_columns = [c for c in header if c.startswith("rate_")]
    spiking = connectome and neural.get("dynamics") == "spiking"
    scale = ((neural.get("parameters") or {}).get("spiking") or {}).get("rate_scale_hz", 100) if spiking else None
    model.add(TimeSeries(name="readout_activity", data=_compressed(np.column_stack([columns[c] for c in rate_columns])
                                                                    if rate_columns else np.zeros((n, 0))),
                         unit="Hz" if spiking else "n.a.", conversion=float(scale) if spiking else 1.0,
                         description=("Spike-train firing rate (exponential window) ÷ the rate scale; × conversion "
                                      "gives Hz. " if spiking else "Dimensionless rate activity. ")
                                     + "Columns as in readout_columns: " + ", ".join(names), **timing))
    rows = _readout_rows(meta, names)
    model.add(DynamicTable(name="readout_columns", description="Columns of readout_activity, in order",
                           columns=[VectorData(name=k, description=d, data=[r[k] for r in rows]) for k, d in
                                    [("column", "column name in telemetry.csv (rate_ prefix removed)"),
                                     ("cell_type", "cell type (or population) averaged in this column"),
                                     ("side", "left, right or both"), ("kind", "what the column is"),
                                     ("root_ids", "FlyWire root IDs of the neurons averaged, space-separated "
                                                  "(readout cell types only)")]]))
    activity = directory / "activity_types.npz"
    if activity.is_file():
        with np.load(activity, allow_pickle=False) as data:
            values, times = data["activity"], data["time_s"]
            types, counts = data["type_names"].tolist(), data["neurons_per_type"].tolist()
        model.add(TimeSeries(name="cell_type_activity", data=_compressed(values), timestamps=times,
                             unit="Hz" if spiking else "n.a.", conversion=float(scale) if spiking else 1.0,
                             description="Mean activity of each cell type's neurons (columns as in cell_types), in the "
                                         "units of readout_activity"))
        model.add(DynamicTable(name="cell_types", description="Columns of cell_type_activity, in order",
                               columns=[VectorData(name="cell_type", description="cell type", data=types),
                                        VectorData(name="neurons", description="neurons averaged", data=counts)]))

    # Spike times of the readout neurons.
    spikes = directory / "spikes_readout.npz"
    if spikes.is_file():
        with np.load(spikes, allow_pickle=False) as data:
            times, units = data["spike_time_s"], data["spike_unit"]
            unit = {k.removeprefix("unit_"): data[k].tolist() for k in data.files if k.startswith("unit_")}
        nwb.add_unit_column(name="cell_type", description="FlyWire cell type")
        nwb.add_unit_column(name="side", description="left or right")
        nwb.add_unit_column(name="root_id", description="FlyWire v783 root ID")
        nwb.add_unit_column(name="neuron_index", description="index of the neuron in the circuit file")
        end = float(time[-1]) if n else 0.0
        stopped = (meta.get("spikes") or {}).get("stopped_at_s")
        for i in range(len(unit["neuron_index"])):
            nwb.add_unit(spike_times=times[units == i], cell_type=unit["cell_type"][i], side=unit["side"][i],
                         root_id=str(unit["root_id"][i]), neuron_index=int(unit["neuron_index"][i]),
                         obs_intervals=[[0.0, float(stopped) if stopped is not None else end]])
        nwb.units.fields["description"] = "Readout neurons of the leaky integrate-and-fire model (Shiu et al. 2024 parameters)"

    # Interventions, as intervals of constant interventions.
    end = float(time[-1]) + dt if n else 0.0
    changes = _schedule(meta, "interventions", config.get("initial_interventions") or {})
    intervals = TimeIntervals(name="interventions", description="Intervals of constant interventions (sensor inputs on or "
                                                                 "off, silenced, scaled or activated cell types)")
    intervals.add_column(name="code", description="Short label, as telemetry.csv's intervention_code")
    intervals.add_column(name="interventions", description="The full interventions, as JSON")
    intervals.add_column(name="source", description="initial, manual or protocol")
    for i, (t, _, value, source) in enumerate(changes):
        stop = changes[i + 1][0] if i + 1 < len(changes) else max(end, t)
        intervals.add_row(start_time=t, stop_time=stop, code=_code(value), interventions=json.dumps(value, sort_keys=True),
                          source=source)
    nwb.add_time_intervals(intervals)

    nwb.add_scratch(json.dumps(manifest, indent=1), name="digitalfly_manifest",
                    description="RO-Crate 1.1 provenance manifest of this run (JSON-LD)")
    return nwb


def _body_series(path: Path, meta: dict, TimeSeries) -> list:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        return []
    t = np.array([r["t"] for r in rows], dtype=np.float64)
    legs = ", ".join(rows[0].get("leg_order") or [])
    out = []
    for key, unit, conversion, text in [
            ("joint_position_rad", "radians", 1.0, "Joint angles, columns in body_joint_order: "
             + ", ".join(meta.get("body_joint_order") or [])),
            ("ground_contact_force", "N", 1e-6, f"Ground contact force per leg ({legs}), stored in µN"),
            ("cpg_phase_rad", "radians", 1.0, f"Central pattern generator phase per leg ({legs})")]:
        values = [r.get(key) for r in rows]
        if all(isinstance(v, list) and v for v in values) and len({len(v) for v in values}) == 1:
            out.append(TimeSeries(name=key.removesuffix("_rad"), data=_compressed(np.array(values, dtype=np.float64)),
                                  timestamps=t, unit=unit, conversion=conversion, description=text))
    return out


def write(nwbfile, path: Path) -> Path:
    from pynwb import NWBHDF5IO
    path = Path(path)
    staging = path.with_name(f".tmp-{path.name}")
    try:
        with NWBHDF5IO(str(staging), "w") as io:
            io.write(nwbfile)
        staging.replace(path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return path


def export_run(directory: Path, path: Path | None = None) -> Path:
    """Write a saved run as NWB, by default to <run folder>/<run key>.nwb, atomically; returns the path."""
    directory = Path(directory)
    return write(build(directory), path or directory / f"{directory.name}.nwb")


def validate(path: Path) -> list[str]:
    """pynwb's validator: the problems it reports, as text (empty when the file conforms to the NWB schema)."""
    pynwb = _require()
    errors = pynwb.validate(path=str(path))
    return [str(error) for error in errors]
