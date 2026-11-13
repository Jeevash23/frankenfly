from collections import deque
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import time
import uuid
import zipfile
import numpy as np
from digitalfly import __version__ as APPLICATION_VERSION
from digitalfly.api.models import ConnectomeParameters, Event, Interventions, RunConfig, Sample, Stimulus, NeuralParameters
from digitalfly.neural.connectome import LIF, TRACE_TYPES, ConnectomeCircuit, load_circuit
from digitalfly.neural.model import RateCircuit
from digitalfly import plugins, provenance as provenance_module
from digitalfly.simulation.engines import FlyGymBody, ToyBody, CONTROL_DT, PHYSICS_DT, NEURAL_DT, ROOT

LIF_DT_S = LIF["dt_ms"] / 1000
RECORD_LIMIT = 30000
EVENT_LIMIT = 10000  # manual input changes, the schedule a replay re-applies; bookkeeping events do not count
SCHEDULE_KINDS = {"stimulus", "interventions", "parameters", "connectome_parameters"}
# Repeats within one control step keep only the last value: these changes leave no trace but their value. Interventions
# and connectome parameters are never merged: applying one changes the network or motor path at once (silenced
# neurons go to rest, a clamped rate is set, the motor path restarts), so replay must apply each in turn.
MERGED_KINDS = {"stimulus", "parameters", "speed"}
BOOKKEEPING_KINDS = {"run", "pause", "step", "speed", "export"}  # never replayed
BOOKKEEPING_LIMIT = 10000  # logged per run; later ones are left out after one marker event
# 4 adds lockfiles, optional dependencies, vision.flyvis/bridge and share_safe; 5 adds the target, stimulus and
# intervention telemetry columns, metrics.min_target_distance_mm, record_activity and activity_types.npz; 6 adds the
# provenance manifest (ro-crate-metadata.json), methods.md, code (git commit), connectome_sources, parameter_diff and,
# for spiking runs, spikes_readout.npz with the readout neurons' spike times.
SCHEMA_VERSION = 6
ACTIVITY_FILE = "activity_types.npz"
SPIKE_FILE = "spikes_readout.npz"
SPIKE_LIMIT = 5_000_000  # recorded readout spikes per run; past it, recording stops and the export says when
ACTIVITY_BYTES = 128 * 2**20  # per run; past it the recorded activity keeps every second sample, and so on
TARGET_COLUMNS = ["target_bearing_deg", "target_distance_mm", "stimulus_x_mm", "stimulus_y_mm", "stimulus_intensity",
                  "intervention_code"]
SIDES = {"both": "", "left": ":L", "right": ":R"}
DEPENDENCIES = ["flygym", "mujoco", "numpy", "fastapi", "pydantic", "numba", "scipy"]
OPTIONAL_DEPENDENCIES = ["llvmlite", "pillow", "torch", "torchvision", "flyvis"]
BACKEND = Path(__file__).resolve().parents[3]
LIMIT_MESSAGE = "Recording limit reached (30,000 samples, 300 simulated seconds). Export this run and reset to continue."
SCHEDULE_MESSAGE = "Input schedule reached 10,000 changes. Export this run and reset to continue."
_ABSOLUTE_PATH = re.compile(r"(?<![\w.:/\\)\]-])(?:/[^\s/'\"<>|:;,()\[\]]+){2,}/?|\b[A-Za-z]:\\[^\s'\"<>|]+")


class RunLimit(RuntimeError):
    """The run cannot advance (its protocol ended or its recording is full) but is valid: it pauses, never fails."""


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def dependency_versions() -> dict:
    """Installed versions from package metadata; optional packages only when installed (never imported here)."""
    versions = {name: version(name) for name in DEPENDENCIES}
    for name in OPTIONAL_DEPENDENCIES:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            pass
    return versions


def shareable(value, free_text=False):
    """A copy of exported metadata for publishing: absolute paths become relative to the project, or <local>
    outside it; in free text (errors and event messages) the host name becomes <local> too."""
    if isinstance(value, dict):
        return {k: shareable(v, free_text or k in {"error", "message"}) for k, v in value.items()}
    if isinstance(value, list):
        return [shareable(v, free_text) for v in value]
    if not isinstance(value, str):
        return value
    project = re.escape(str(BACKEND.parent))
    value = re.sub(project + r"(?![\w.-])", ".", re.sub(project + re.escape(os.sep), "", value))
    value = _ABSOLUTE_PATH.sub("<local>", value)
    host = socket.gethostname()
    if free_text and len(host) > 2:
        value = re.sub(rf"\b{re.escape(host)}\b", "<local>", value)
    return value


def _code_name(name: str) -> str:
    return re.sub(r"[\s;:,\"'#]", "_", name)


def intervention_code(interventions: Interventions) -> str:
    """A short label of the interventions in effect, for telemetry: L and R with 1 for a sensor input on and 0 for
    off, then each silenced group or cell type, for example "L0R1;DNa02:left;DNp09:silence;LC10a:L:scale0.5"."""
    parts = [f"L{int(not interventions.zero_left)}R{int(not interventions.zero_right)}"]
    if interventions.silence != "none":
        parts.append(f"units:{interventions.silence}")  # the engineered model's unit groups
    if interventions.silence_dna02 != "none":
        parts.append(f"DNa02:{interventions.silence_dna02}")
    parts += [f"{_code_name(name)}:silence" for name in interventions.silence_types]
    for item in interventions.cell_types:  # a side (none for both) and a mode with its value
        mode = item.mode if item.mode == "silence" else f"{item.mode}{item.value:g}"
        parts.append(f"{_code_name(item.name)}{SIDES[item.side]}:{mode}")
    return ";".join(parts)


def _write_spikes(path: Path, record: list, units: dict) -> None:
    """spikes_readout.npz: every recorded spike as (time, unit), sorted by time, and the units' identities."""
    substeps = np.concatenate([np.full(len(hit), step, dtype=np.int64) for step, hit in record]) if record \
        else np.zeros(0, dtype=np.int64)
    neurons = np.concatenate([hit for _, hit in record]).astype(np.int64) if record else np.zeros(0, dtype=np.int64)
    position = {int(neuron): i for i, neuron in enumerate(units["neuron_index"])}
    unit = np.array([position[int(n)] for n in neurons], dtype=np.int64)
    order = np.lexsort((unit, substeps))
    np.savez_compressed(path, spike_time_s=np.round(substeps[order] * LIF_DT_S, 8), spike_unit=unit[order],
                        **{f"unit_{k}": np.asarray(v) for k, v in units.items()})


def _write_activity(path: Path, rows: list, steps: list, names: list, counts) -> None:
    """activity_types.npz, streamed row by row, so the recording is never copied into one more array."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open("activity.npy", "w", force_zip64=True) as output:
            np.lib.format.write_array_header_1_0(output, {"descr": "<f4", "fortran_order": False,
                                                          "shape": (len(rows), len(names))})
            for row in rows:
                output.write(row.tobytes())
        arrays = {"step": np.asarray(steps, dtype=np.int64),
                  "time_s": np.asarray([round(step * CONTROL_DT, 8) for step in steps], dtype=np.float64),
                  "type_names": np.asarray(names, dtype=str), "neurons_per_type": np.asarray(counts, dtype=np.int64)}
        for name, array in arrays.items():
            with archive.open(f"{name}.npy", "w") as output:
                np.lib.format.write_array(output, array, allow_pickle=False)


class ExportJob:
    """One export, captured on the simulation thread and written by write(), on any thread. The capture is cheap:
    the metadata as JSON text and references to the recorded samples, which never change once recorded, so the run
    can go on while the files are written."""

    def __init__(self, exp: "Experiment", base: Path, share_safe: bool):
        if not exp.recording:
            raise ValueError("This experiment keeps no recording (record=False), so there is nothing to export.")
        self.base, self.run_id = base, exp.run_id
        self.name = f"{exp.run_id}-{uuid.uuid4().hex[:6]}"
        self.metadata = json.dumps(exp.metadata(share_safe), indent=2, allow_nan=False)
        self.records = list(exp.records)
        self.unit_names = list(exp.circuit.unit_names)
        codes = {}
        self.inputs = [(start, stimulus.x, stimulus.y, stimulus.intensity,
                        codes.setdefault(id(interventions), intervention_code(interventions)))
                       for start, stimulus, interventions in exp.inputs]
        self.activity = None
        if exp.activity is not None:
            data = exp.circuit.data
            self.activity = (list(exp.activity), list(exp.activity_steps), list(data.type_names), data.type_counts.copy())
        self.spikes = None
        units = exp.spike_units()
        if units is not None:
            self.spikes = (exp.circuit.spike_record()[0], units)

    def write(self) -> dict:
        """Save the run as a folder and a ZIP. Files are written into a hidden temporary folder inside the runs folder
        that is renamed into place only when complete, so an interrupted export never lists as a run."""
        base, name = self.base, self.name
        base.mkdir(parents=True, exist_ok=True)
        destination, archive = base / name, base / f"{name}.zip"
        staging, staged_archive = base / f".tmp-{name}", base / f".tmp-{name}.zip"
        try:
            staging.mkdir()
            (staging / "metadata.json").write_text(self.metadata)
            self.write_telemetry(staging / "telemetry.csv")
            with (staging / "body_signals.jsonl").open("w") as output:
                for s in self.records:
                    if s.body_signals:
                        output.write(json.dumps({"step": s.step, "t": s.t, **s.body_signals}, allow_nan=False)+"\n")
            if self.activity is not None:
                _write_activity(staging / ACTIVITY_FILE, *self.activity)
            if self.spikes is not None:
                _write_spikes(staging / SPIKE_FILE, *self.spikes)
            self.write_provenance(staging)
            # Created exclusively, as the staging folder is: a link placed at either name is never written through.
            with (staged_archive.open("xb") as handle,
                  zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as output):
                for file in sorted(staging.iterdir()):
                    # The activity file is compressed already.
                    output.write(file, file.name, compress_type=zipfile.ZIP_STORED if file.suffix == ".npz" else None)
            os.replace(staged_archive, archive)
            os.replace(staging, destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            staged_archive.unlink(missing_ok=True)
            if not destination.exists():
                archive.unlink(missing_ok=True)
            raise
        return {"run_id": self.run_id, "samples": len(self.records), "path": str(destination),
                "download_url": f"/api/exports/{archive.name}"}

    def write_provenance(self, staging: Path):
        """methods.md, drafted from the manifest, then ro-crate-metadata.json, which lists every file with its hash
        (methods.md included). Built here, off the simulation thread, from the captured metadata."""
        meta = json.loads(self.metadata)
        files = provenance_module.run_files(staging)
        manifest = provenance_module.build_manifest(meta, files, self.name)
        methods = staging / provenance_module.METHODS_FILE
        methods.write_text(provenance_module.methods_markdown(manifest))
        provenance_module.add_file(manifest, methods.name, methods)
        (staging / provenance_module.MANIFEST_FILE).write_text(json.dumps(manifest, indent=2, allow_nan=False))

    def write_telemetry(self, path: Path):
        """One row per sample. The target columns describe the target in effect for that sample: its bearing from the
        sample's heading (degrees, positive to the left, within ±180) and its distance from the sample's position."""
        with path.open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["step", "time_s", "x_mm", "y_mm", "z_mm", "yaw_rad", "speed_mm_s", "sensor_l", "sensor_r",
                             "raw_sensor_l", "raw_sensor_r", *["rate_" + n.lower().replace(" ", "_") for n in self.unit_names],
                             "motor_l", "motor_r", *TARGET_COLUMNS])
            ends = [start for start, *_ in self.inputs[1:]] + [len(self.records)]
            for (start, x, y, intensity, code), end in zip(self.inputs, ends):
                for s in self.records[start:end]:
                    p = s.pose
                    bearing = math.atan2(y - p.y, x - p.x) - p.yaw
                    writer.writerow([s.step, s.t, p.x, p.y, p.z, p.yaw, p.velocity, s.sensors.left, s.sensors.right,
                                     s.sensors.raw_left, s.sensors.raw_right, *s.rates, *s.motor,
                                     math.degrees(math.atan2(math.sin(bearing), math.cos(bearing))),
                                     math.hypot(x - p.x, y - p.y), x, y, intensity, code])


def make_circuit(config: RunConfig):
    if config.neural_model == "connectome":
        return ConnectomeCircuit(config.connectome_parameters)
    return RateCircuit(config.neural_parameters)


class Experiment:
    def __init__(self, config: RunConfig, render=True, record=True):
        """record=False keeps no per-sample recording, for long programmatic trials: there is then no 30,000-sample
        (300 s) limit, while the current sample, metrics, events and the bounded display history still update.
        Such a run cannot be exported. The app always records."""
        self.body = None
        self.render_enabled = render
        self.recording = bool(record)
        self.circuit = RateCircuit()
        self.status = "initializing"
        self.error = None
        try:
            self.reset(config)
        except Exception as exc:
            # Nothing to keep yet: an empty run in the error state reports why; Reset recovers.
            self._new_run(config)
            self.fail(exc)

    def reset(self, config: RunConfig):
        """Start a new run. The circuit, and the body when it changes, are built before anything is replaced, so a
        configuration that cannot be built raises and leaves the current run as it was; a later failure leaves the
        new run in the error state. Either way the configuration matches the circuit and body in use."""
        circuit = make_circuit(config)
        circuit.reset(config.seed)
        if self.recording and getattr(circuit, "spiking", None) is not None:
            circuit.record_spikes(np.concatenate([np.concatenate([left, right]) for _, left, right in circuit.readouts]))
        if circuit.kind == "connectome":
            scheduled = [e.interventions for e in config.protocol.events if e.interventions] if config.protocol else []
            for interventions in [config.initial_interventions] + scheduled:
                circuit.manipulation(interventions)  # a cell type or side this circuit lacks fails here, before anything changes
        # A plugin sensor (RunConfig.plugins) is found before anything changes; without one nothing plugin-related runs.
        sensor_plugin = plugins.sensor(config.plugins.sensor)[1] if config.plugins and config.plugins.sensor else None
        reuse = self.body is not None and self.body.name == config.engine and self.body.sensor_model == config.sensor_model
        body = self.body if reuse else (FlyGymBody if config.engine == "flygym" else ToyBody)(
            config.seed, self.render_enabled, config.sensor_model)
        previous, self.circuit, self.body = self.body, circuit, body
        self.sensor_plugin = sensor_plugin
        self._new_run(config)
        try:
            if reuse:
                body.reset(config.seed)
            elif previous is not None:
                previous.close()
            body.set_stimulus(config.stimulus)
            self.observe()
            self.initial_pose = self.sample.pose.model_copy(deep=True)
            self.record()
            self.status = "paused"
            self.event("reset", "Experiment initialized · seed " + str(config.seed), config.model_dump())
        except Exception as exc:
            self.fail(exc)

    def _new_run(self, config: RunConfig):
        self.status = "initializing"
        self.config = config.model_copy(deep=True)
        self.initial_config = config.model_copy(deep=True)
        self.interventions = config.initial_interventions.model_copy(deep=True)
        self.step_index = 0
        self.sample = None
        self.history = deque(maxlen=201)
        self.type_history = deque(maxlen=201)
        self.trail = deque(maxlen=600)
        self.records: list[Sample] = []
        # (index of the first record, stimulus, interventions) whenever either changes, for the telemetry columns.
        self.inputs: list[tuple] = []
        self.min_target_distance = None
        types = config.record_activity == "types" and self.circuit.kind == "connectome"
        self.activity, self.activity_steps, self.activity_every = ([] if types else None), [], 1
        self.events: list[Event] = []
        self.spike_limit_t = None  # simulated time at which spike recording stopped at SPIKE_LIMIT
        self.schedule_events = self.bookkeeping_events = 0
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.compute_s = self.active_wall_s = 0.
        self._run_started = None
        self.path_length = self.turning = self.speed_sum = 0.
        self.contact_sum = np.zeros(6)
        self.contact_samples = 0
        self.protocol_applied = set()
        self.protocol_complete = False
        self.trial = None
        self.error = None

    def _merges(self, kind: str, source=None) -> bool:
        last = self.events[-1] if self.events else None
        return (kind in MERGED_KINDS and last is not None and last.kind == kind and last.step == self.step_index
                and last.payload.get("source") == source)

    def _schedule_room(self, kind: str, source=None):
        """Refuse a manual input change before it is applied once the schedule is full: it could not be replayed."""
        if source != "protocol" and self.schedule_events >= EVENT_LIMIT and not self._merges(kind, source):
            raise ValueError(SCHEDULE_MESSAGE)

    def event(self, kind: str, message: str, payload: dict | None = None):
        """Log an event. Manual input changes count toward EVENT_LIMIT; protocol and bookkeeping events (run,
        pause, step, speed, export, ...) never do. A repeat of a stimulus, engineered-parameter or speed change
        within the same control step replaces the previous one (see MERGED_KINDS), so replay is unchanged. Past
        BOOKKEEPING_LIMIT run, pause, step, speed and export events, one marker says that later ones are left out."""
        payload = payload or {}
        if self._merges(kind, payload.get("source")):
            self.events[-1] = self.events[-1].model_copy(update={"message": message, "payload": payload})
            return
        if kind in BOOKKEEPING_KINDS:
            self.bookkeeping_events += 1
            if self.bookkeeping_events > BOOKKEEPING_LIMIT:
                if self.bookkeeping_events == BOOKKEEPING_LIMIT + 1:
                    self.event("log_limit", "Further run, pause, step, speed and export events omitted "
                                            f"({BOOKKEEPING_LIMIT:,} logged); they do not affect replay")
                return
        self.events.append(Event(seq=len(self.events), step=self.step_index, t=self.t,
                                 kind=kind, message=message, payload=payload))
        if kind in SCHEDULE_KINDS and payload.get("source") != "protocol":
            self.schedule_events += 1
            if self.schedule_events == EVENT_LIMIT:
                self.event("limit", "Input schedule reached 10,000 changes: further input changes are refused. "
                                    "Export this run and reset to continue.")

    @property
    def t(self):
        return round(self.step_index * CONTROL_DT, 8)

    @property
    def wall_s(self):
        return self.active_wall_s + (time.perf_counter() - self._run_started if self._run_started is not None else 0)

    def start_clock(self):
        if self._run_started is None:
            self._run_started = time.perf_counter()

    def stop_clock(self):
        if self._run_started is not None:
            self.active_wall_s += time.perf_counter() - self._run_started
            self._run_started = None

    def sense(self):
        """Sensor values for this interval; with FlyVis eyes, the circuit's visual drive too."""
        sensors = self.body.sensors(self.config.stimulus, self.interventions)
        if getattr(self, "sensor_plugin", None) is not None:
            sensors = self.plugin_sensors(sensors)
        if getattr(self.body, "flyvis", None) is not None and self.circuit.kind == "connectome":
            responses = self.body.flyvis.responses.copy()
            responses[0] *= not self.interventions.zero_left
            responses[1] *= not self.interventions.zero_right
            left, right = self.circuit.set_visual(responses)
            sensors = sensors.model_copy(update={"left": left, "right": right})
        elif getattr(self.circuit, "visual", None) is not None:
            self.circuit.set_visual(None)
        return sensors

    def plugin_sensors(self, geometric):
        """The plugin sensor's values in place of the geometric encoder's; input interventions still apply."""
        pose, stimulus = self.body.pose(legs=False), self.config.stimulus
        reading = plugins.SensorReading(
            t=self.t, step=self.step_index, x=pose.x, y=pose.y, yaw=pose.yaw, velocity=pose.velocity,
            target_x=stimulus.x, target_y=stimulus.y, intensity=stimulus.intensity, geometric_left=geometric.raw_left,
            geometric_right=geometric.raw_right, bearing_rad=geometric.bearing_rad, distance_mm=geometric.distance_mm)
        left, right = plugins.encode(self.sensor_plugin, reading)
        return geometric.model_copy(update={"left": 0 if self.interventions.zero_left else left,
                                            "right": 0 if self.interventions.zero_right else right,
                                            "raw_left": left, "raw_right": right})

    def observe(self):
        self.circuit.apply_silencing(self.interventions)
        pose = self.body.pose()
        sensors = self.sense()
        self.sample = Sample(step=self.step_index, t=self.t, pose=pose, sensors=sensors,
            rates=self.circuit.readout(), motor=self.circuit.motor(self.config.controller == "baseline").tolist(),
            body_signals=self.body.body_signals())

    def record(self):
        # Retain full pose in the latest sample only, avoiding repeated mesh/joint history.
        # Samples are never mutated after creation, so shallow copies are safe here.
        sample = self.sample.model_copy(update={"pose": self.sample.pose.model_copy(update={"legs": []})})
        stimulus = self.config.stimulus
        distance = math.hypot(stimulus.x - sample.pose.x, stimulus.y - sample.pose.y)
        if self.min_target_distance is None or distance < self.min_target_distance:
            self.min_target_distance = distance
        means = None
        if self.recording:
            last = self.inputs[-1] if self.inputs else None
            if last is None or last[1] is not stimulus or last[2] is not self.interventions:
                self.inputs.append((len(self.records), stimulus, self.interventions))
            self.records.append(sample)
            spiking = getattr(self.circuit, "spiking", None)
            if spiking is not None and spiking.record_mask is not None and spiking.recorded_count >= SPIKE_LIMIT:
                self.circuit.record_spikes(None)
                self.spike_limit_t = self.t
            if self.activity is not None and self.step_index % self.activity_every == 0:
                means = self.circuit.type_means()
                self.activity.append(means.astype("<f4"))
                self.activity_steps.append(self.step_index)
                if len(self.activity) * means.size * 4 > ACTIVITY_BYTES:  # from now on, every second sample
                    self.activity, self.activity_steps = self.activity[::2], self.activity_steps[::2]
                    self.activity_every *= 2
        if self.step_index % 2 == 0:
            self.history.append(sample.model_copy(update={"body_signals": {
                k: v for k, v in sample.body_signals.items() if k != "joint_position_rad"}}))
            if self.circuit.kind == "connectome":
                self.type_history.append((self.circuit.type_means() if means is None else means).astype(np.float32))
        self.trail.append([sample.pose.x, sample.pose.y])

    def check_advance(self):
        """Raise RunLimit when a finished protocol or a full recording stops the run; the run stays valid."""
        if self.protocol_complete:
            raise RunLimit("Protocol finished. Reset to repeat it.")
        if self.recording and len(self.records) >= RECORD_LIMIT:
            raise RunLimit(LIMIT_MESSAGE)

    def advance(self):
        if self.status == "error":
            raise RuntimeError("Reset the experiment before stepping after an error.")
        self.check_advance()
        before = time.perf_counter()
        protocol = self.config.protocol
        if protocol:
            for index, event in enumerate(protocol.events):
                if event.step == self.step_index and index not in self.protocol_applied:
                    if event.stimulus is not None:
                        self.set_stimulus(event.stimulus, source="protocol")
                    if event.interventions is not None:
                        self.set_interventions(event.interventions, source="protocol")
                    self.protocol_applied.add(index)
        previous_x, previous_y, previous_yaw = self.body.planar()
        sensors = self.sense()
        for _ in range(round(CONTROL_DT / NEURAL_DT)):
            self.circuit.advance(sensors, self.interventions, NEURAL_DT)
        motor = self.circuit.motor(self.config.controller == "baseline")
        self.body.advance(motor)
        self.step_index += 1
        # The sample contains the sensory observation actually used for this interval.
        self.sample = Sample(step=self.step_index, t=self.t, pose=self.body.pose(),
                             sensors=sensors, rates=self.circuit.readout(), motor=motor.tolist(),
                             body_signals=self.body.body_signals())
        pose = self.sample.pose
        self.path_length += float(np.hypot(pose.x-previous_x, pose.y-previous_y))
        self.turning += float(np.arctan2(np.sin(pose.yaw-previous_yaw), np.cos(pose.yaw-previous_yaw)))
        self.speed_sum += pose.velocity
        contacts = self.sample.body_signals.get("contact")
        if contacts is not None:
            self.contact_sum += contacts
            self.contact_samples += 1
        self.record()
        self.compute_s += time.perf_counter() - before
        if protocol and self.step_index >= protocol.duration_steps:
            self.protocol_complete = True
            self.stop_clock()
            self.status = "paused"
            self.event("protocol_complete", f"{protocol.name} completed · {self.t:g} simulated seconds")
        elif self.recording and len(self.records) >= RECORD_LIMIT:
            self.stop_clock()
            self.status = "paused"
            self.event("limit", LIMIT_MESSAGE)

    def _observe_change(self, undo, body_change=None):
        """body_change(), then observe(), after an input change. A failure may leave the body or circuit changed in
        a way no event records (silenced neurons at rest, a moved target), so undo() restores what it can and the
        run enters the error state: its export still replays, and Reset recovers."""
        try:
            if body_change is not None:
                body_change()
            self.observe()
        except Exception as exc:
            undo()
            self.fail(exc)
            raise

    def set_stimulus(self, stimulus: Stimulus, source="manual"):
        self._schedule_room("stimulus", source)
        previous, self.config.stimulus = self.config.stimulus, stimulus
        if self.body is not None and self.status != "error":
            self._observe_change(lambda: setattr(self.config, "stimulus", previous),
                                 lambda: self.body.set_stimulus(stimulus))
        self.event("stimulus", f"Target moved to ({stimulus.x:g}, {stimulus.y:g}) mm · intensity {stimulus.intensity:g}", {**stimulus.model_dump(), "source": source})

    def set_interventions(self, interventions: Interventions, source="manual"):
        self._schedule_room("interventions", source)
        # Checked against the circuit that is running, and kept only once they apply.
        interventions.for_model(self.circuit.kind)
        if self.circuit.kind == "connectome":
            self.circuit.manipulation(interventions)
        previous, self.interventions = self.interventions, interventions
        if self.body is not None and self.status != "error":
            self._observe_change(lambda: setattr(self, "interventions", previous))
        others = ""
        if self.circuit.kind == "connectome":
            silenced = ", ".join([f"DNa02 {interventions.silence_dna02}"] * (interventions.silence_dna02 != "none")
                                 + interventions.silence_types
                                 + [c.target for c in interventions.cell_types if c.mode == "silence"]) or "none"
            others = "".join(f" · {c.label(self.circuit.parameters.dynamics)}"
                             for c in interventions.cell_types if c.mode != "silence")
        else:
            silenced = interventions.silence
        self.event("interventions", f"Inputs L {'off' if interventions.zero_left else 'on'} / R {'off' if interventions.zero_right else 'on'} · silence {silenced}{others}", {**interventions.model_dump(), "source": source})

    def set_parameters(self, parameters: NeuralParameters):
        self._schedule_room("parameters")
        if self.circuit.kind != "engineered":
            raise ValueError("These parameters belong to the engineered six-unit model. Use the connectome parameters instead.")
        self.config.neural_parameters = parameters
        self.circuit.configure(parameters)
        self.event("parameters", "Neural parameters updated", parameters.model_dump())

    def set_connectome_parameters(self, parameters: ConnectomeParameters):
        self._schedule_room("connectome_parameters")
        if self.circuit.kind != "connectome":
            raise ValueError("Connectome parameters apply when the connectome model is selected.")
        current = self.config.connectome_parameters
        fixed = ["circuit", "dynamics", "backend", "readout_types", "input_types", "speed_types"]
        if [getattr(parameters, k) for k in fixed] != [getattr(current, k) for k in fixed]:
            # These change what is recorded (the rate columns) or how it is computed, so they belong to a new run.
            raise ValueError("Changing the circuit, dynamics, backend or populations starts a fresh run: "
                             "use Reset with the new settings.")
        data = self.circuit.data
        try:
            on_disk = load_circuit(parameters.circuit).sha256
        except (OSError, ValueError):
            on_disk = None
        if on_disk != data.sha256:
            # configure() reads the file by name: a rebuilt file would replace this run's wiring mid-run.
            raise ValueError(f"The {data.key} circuit file has changed since this run loaded it. "
                             "Reset to load the new build.")
        parameters.check_against_circuit(data)
        self.config.connectome_parameters = parameters
        self.circuit.configure(parameters)
        self.event("connectome_parameters", "Connectome parameters updated", parameters.model_dump())

    def connectome_snapshot(self):
        """Live, display-only activity summary for the connectome model; not recorded."""
        if self.circuit.kind != "connectome":
            return None
        circuit = self.circuit
        means = circuit.type_means()
        readout = {circuit.data.type_names.index(name) for name, _, _ in circuit.readouts}
        order = [int(i) for i in np.argsort(-means, kind="stable") if i not in readout][:TRACE_TYPES]
        traces = np.array([row[order] for row in self.type_history]) if self.type_history else np.zeros((0, len(order)))
        manipulation = circuit.manipulation(self.interventions)
        return {"circuit": circuit.data.key, "circuit_sha256": circuit.data.sha256,
                "dynamics": circuit.parameters.dynamics, "unit_names": circuit.unit_names,
                "readout_types": [name for name, _, _ in circuit.readouts],
                "type_rates": np.round(means, 4).tolist(), "turn": circuit.turn(),
                "motor_clipped_fraction": circuit.motor_clipped_fraction,
                "silenced_neurons": int(len(manipulation.silenced)),
                "manipulated_neurons": {"silence": int(len(manipulation.silenced)), "scale": int(len(manipulation.scaled)),
                                        "activate": int(len(manipulation.activated))},
                "trace_t": [s.t for s in self.history][-len(traces):] if len(traces) else [],
                "top_types": [{"index": i, "name": circuit.data.type_names[i],
                               "trace": np.round(traces[:, k], 4).tolist()} for k, i in enumerate(order)]}

    @property
    def metrics(self):
        if not self.sample:
            return {}
        pose = self.sample.pose
        return {"path_length_mm": self.path_length,
            "displacement_mm": float(np.hypot(pose.x-self.initial_pose.x, pose.y-self.initial_pose.y)),
            "mean_speed_mm_s": self.speed_sum / max(self.step_index, 1),
            "net_turn_deg": float(np.degrees(self.turning)),
            "target_distance_mm": float(np.hypot(pose.x-self.config.stimulus.x, pose.y-self.config.stimulus.y)),
            "min_target_distance_mm": self.min_target_distance,
            "contact_fraction": (self.contact_sum / max(self.contact_samples, 1)).tolist() if self.contact_samples else [],
            "duration_s": self.t, "protocol_complete": self.protocol_complete}

    def fail(self, exc: Exception):
        """Enter the error state, except for a RunLimit: a finished protocol or a full recording only pauses."""
        self.stop_clock()
        if isinstance(exc, RunLimit):
            self.status = "paused" if self.status == "running" else self.status
            return
        if self.status == "error" and self.error == f"{type(exc).__name__}: {exc}":
            return  # reported already, by the input change that failed within this step
        self.status = "error"
        self.error = f"{type(exc).__name__}: {exc}"
        self.event("error", self.error)

    @property
    def provenance(self):
        connectome = self.circuit.kind == "connectome"
        if connectome:
            info = self.circuit.description()
            readout = ", ".join(item["cell_type"] for item in info["readout"])
            dynamics = ("spiking (leaky integrate-and-fire, Shiu et al. 2024 parameters)" if info["dynamics"] == "spiking"
                        else "rate")
            source = ("neuron model and constants from Shiu et al. 2024" if info["dynamics"] == "spiking"
                      else "dynamics engineered")
            neural = (f"Connectome-constrained {dynamics} model · {info['neurons']:,} neurons and {info['connections_active']:,} "
                      f"connections ({info['circuit']}) · structure data-derived, signs assumed, {source}")
            wiring = (f"{info['dataset']} · circuit {info['circuit']} · {info['license']} · "
                      f"sha256 {info['circuit_sha256'][:12]}")
            speed = (f"forward drive = tonic + speed gain × {', '.join(info['speed_population'])}" if info["speed_population"]
                     else "forward drive is an engineered tonic term")
            mode = ("Controller-only baseline; neural output bypassed" if self.config.controller == "baseline" else
                    f"Connectome closed loop: turning from right − left of {readout} (direction from Rayshubskiy et al. 2025); {speed}")
        else:
            neural = "Six engineered leaky rate units · v1 · hand-chosen weights"
            wiring = "No biological connectome loaded"
            mode = "Controller-only baseline; neural output bypassed" if self.config.controller == "baseline" else "Engineered neural closed loop"
        return {
            "body_engine": "FlyGym 2.1.0 / MuJoCo 3.9.0 · NeuroMechFly" if self.config.engine == "flygym" else "Toy demo: not FlyGym physics",
            "sensor_model": {"vision": "FlyGym compound-eye rendering · engineered green-contrast encoder",
                             "flyvis": "FlyGym compound-eye rendering → FlyVis optic-lobe network (Lappalainen et al. 2024; FIB-25/FIB-19 connectivity, task-trained) → circuit visual neurons by FlyWire v783 synapse counts; pooling engineered"
                             }.get(self.config.sensor_model, "Geometric bilateral bearing / intensity approximation · v1"),
            "neural_model": neural,
            "motor_controller": "FlyGym hybrid turning controller · engineered" if self.config.engine == "flygym" else "Differential kinematic controller · engineered",
            "connectivity_source": wiring,
            "input_mapping": (self.circuit.description()["input_mapping"] if connectome
                              else "Engineered: each sensor drives its sensory unit"),
            "controller_mode": mode,
            "viewport": "MuJoCo rendered body / pose-synchronized arena schematic",
            "body_sex": "Female-derived NeuroMechFly morphology; no separate male biomechanics" if self.config.engine == "flygym" else "Unspecified; kinematic demonstration",
            "anatomy_atlas": ("Female DNa02 skeletons are tinted with this model's DNa02 output when it has one; other anatomy is display-only" if connectome
                              else "Published male/female anatomical samples are separate from this controller"),
        }

    def vision_provenance(self) -> dict:
        """The eye renderer's settings and, with FlyVis eyes, the FlyVis release and network, its checkpoint's
        hash, and the bridge file the circuit reads."""
        vision = {k: v for k, v in self.body.vision.items() if k not in {"left", "right"}} if self.body else {}
        flyvis = getattr(self.body, "flyvis", None)
        if flyvis is not None:
            from digitalfly.vision.flyvis_eyes import network_dir
            vision["flyvis"] = {**flyvis.describe(), "checkpoint": f"{flyvis.name}/best_chkpt",
                                "checkpoint_sha256": _sha256(network_dir(flyvis.name) / "best_chkpt")}
            if self.circuit.kind == "connectome":
                from digitalfly.neural.connectome import bridge_path
                path = bridge_path(self.circuit.data)
                vision["bridge"] = {"file": path.name, "sha256": _sha256(path), "circuit_sha256": self.circuit.data.sha256}
        return vision

    def spike_units(self) -> dict | None:
        """The neurons whose spike times this run records (its readout neurons, spiking dynamics), with their cell
        type, side and FlyWire root ID; None when it records none."""
        spiking = getattr(self.circuit, "spiking", None)
        if not self.recording or spiking is None or (spiking.record_mask is None and self.spike_limit_t is None):
            return None
        data, rows = self.circuit.data, []
        for name, left, right in self.circuit.readouts:
            rows += [(int(i), name, side) for side, members in (("left", left), ("right", right)) for i in members]
        return {"neuron_index": [r[0] for r in rows], "root_id": [str(data.ids[r[0]]) for r in rows],
                "cell_type": [r[1] for r in rows], "side": [r[2] for r in rows]}

    def metadata(self, share_safe=False) -> dict:
        neural = self.circuit.description()
        activity = None
        if self.activity is not None:
            activity = {"file": ACTIVITY_FILE, "kind": "types", "samples": len(self.activity),
                        "cell_types": len(self.circuit.data.type_names), "every_steps": self.activity_every,
                        "values": "mean activity of each cell type's neurons after each recorded control step, "
                                  "as in the rate columns", "units": neural["readout_units"],
                        "arrays": {"activity": "float32, samples × cell types", "step": "control step of each sample",
                                   "time_s": "simulated time of each sample", "type_names": "cell types, in column order",
                                   "neurons_per_type": "neurons averaged in each column"}}
        spikes = None
        units = self.spike_units()
        if units is not None:
            spikes = {"file": SPIKE_FILE, "units": len(units["neuron_index"]), "spikes": self.circuit.spiking.recorded_count,
                      "neurons": "every neuron of the readout cell types, left and right",
                      "time": "spike_time_s: the start of the 0.1 ms substep whose update crossed the threshold "
                              "(as Brian2's SpikeMonitor), from the reset",
                      "stopped_at_s": self.spike_limit_t, "limit": SPIKE_LIMIT,
                      "arrays": {"spike_time_s": "float64, sorted", "spike_unit": "row of the unit arrays",
                                 "unit_neuron_index": "neuron index in the circuit file", "unit_root_id": "FlyWire root ID",
                                 "unit_cell_type": "cell type", "unit_side": "left or right"}}
        connectome_sources = None
        if self.circuit.kind == "connectome":
            prov = self.circuit.data.provenance
            connectome_sources = {"sources": prov.get("sources") or [], "build": prov.get("build"),
                                  "citations": prov.get("citations") or [], "attribution": prov.get("attribution")}
        metadata = {
            "schema_version": SCHEMA_VERSION, "application_version": APPLICATION_VERSION, "run_id": self.run_id,
            "code": provenance_module.code_version(),
            "created_utc": self.started_at, "exported_utc": datetime.now(timezone.utc).isoformat(),
            "initial_config": self.initial_config.model_dump(), "final_config": self.config.model_dump(),
            "final_interventions": self.interventions.model_dump(), "final_sample": self.sample.model_dump() if self.sample else None,
            "status": self.status, "error": self.error, "provenance": self.provenance,
            "time_steps_s": {"physics": PHYSICS_DT if self.config.engine == "flygym" else CONTROL_DT,
                             "neural": NEURAL_DT, "control": CONTROL_DT},
            "units": {"position": "mm", "velocity": "mm/s", "yaw": "rad", "time": "s", "rates_and_commands": "dimensionless",
                      "target_bearing": "deg"},
            "coordinates": "Right-handed world; +z up; yaw counterclockwise from +x. Camera follows body. Arena is top-down.",
            "warmup_s": .05 if self.config.engine == "flygym" else 0,
            "rendering": {"requested": self.render_enabled, "resolution": [640, 288], "wall_target_hz": 10},
            "performance": {"active_wall_s": self.wall_s, "compute_s": self.compute_s},
            "neural": neural, "metrics": self.metrics, "trial": self.trial, "activity": activity, "spikes": spikes,
            "connectome_sources": connectome_sources,
            **({"plugins": used} if (used := plugins.used_by(self.initial_config)) else {}),
            "parameter_diff": provenance_module.parameter_diff(self.initial_config.model_dump(mode="json")),
            "body_joint_order": [str(dof) for dof in self.body.fly.get_jointdofs_order()] if self.body is not None and self.config.engine == "flygym" else [],
            "vision": self.vision_provenance(),
            "events": [event.model_dump() for event in self.events],
            "recorded_samples": len(self.records), "complete_from_reset": True,
            "platform": platform.platform(), "python": platform.python_version(),
            "dependencies": dependency_versions(),
            "lockfiles": {path.name: _sha256(path) for path in sorted(BACKEND.glob("requirements*.lock"))},
            "share_safe": share_safe,
            "reproducibility": "Fixed seed and step-indexed stimulus/intervention schedule. Same pinned stack tested at absolute tolerance 1e-8; cross-device bitwise equality is not promised.",
        }
        if share_safe:
            del metadata["platform"]
            metadata = shareable(metadata)
        return metadata

    def export_job(self, directory: Path | None = None, share_safe=False) -> ExportJob:
        """Capture this run for export (see ExportJob); its write() saves it under runs/. share_safe=True leaves out
        the platform string and replaces absolute paths and the host name (see shareable), for runs to publish."""
        # Caller never supplies a filesystem path. Generated IDs are confined under runs/.
        return ExportJob(self, directory or ROOT / "runs", share_safe)

    def export(self, directory: Path | None = None, share_safe=False):
        """Save the run as a folder and a ZIP under runs/, atomically (see ExportJob.write), on this thread."""
        return self.export_job(directory, share_safe).write()

    def close(self):
        if self.body is not None:
            self.body.close()
