from collections import deque
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import csv
import json
import platform
import time
import uuid
import zipfile
import numpy as np
from digitalfly import __version__ as APPLICATION_VERSION
from digitalfly.api.models import ConnectomeParameters, Event, Interventions, RunConfig, Sample, Stimulus, NeuralParameters
from digitalfly.neural.connectome import TRACE_TYPES, ConnectomeCircuit
from digitalfly.neural.model import RateCircuit
from digitalfly.simulation.engines import FlyGymBody, ToyBody, CONTROL_DT, PHYSICS_DT, NEURAL_DT, ROOT

RECORD_LIMIT = 30000
EVENT_LIMIT = 10000


def make_circuit(config: RunConfig):
    if config.neural_model == "connectome":
        return ConnectomeCircuit(config.connectome_parameters)
    return RateCircuit(config.neural_parameters)


class Experiment:
    def __init__(self, config: RunConfig, render=True):
        self.body = None
        self.render_enabled = render
        self.circuit = RateCircuit()
        self.status = "initializing"
        self.error = None
        self.reset(config)

    def reset(self, config: RunConfig):
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
        self.events: list[Event] = []
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
        try:
            if self.circuit.kind != config.neural_model:
                self.circuit = make_circuit(config)
            elif config.neural_model == "connectome":
                self.circuit.configure(config.connectome_parameters)
            else:
                self.circuit.configure(config.neural_parameters)
            self.circuit.reset(config.seed)
            if self.body is not None and self.body.name == config.engine and self.body.sensor_model == config.sensor_model:
                self.body.reset(config.seed)
            else:
                if self.body is not None:
                    self.body.close()
                self.body = None
                self.body = (FlyGymBody if config.engine == "flygym" else ToyBody)(config.seed, self.render_enabled, config.sensor_model)
            self.body.set_stimulus(config.stimulus)
            self.observe()
            self.initial_pose = self.sample.pose.model_copy(deep=True)
            self.record()
            self.status = "paused"
            self.event("reset", "Experiment initialized · seed " + str(config.seed), config.model_dump())
        except Exception as exc:
            self.fail(exc)

    def event(self, kind: str, message: str, payload: dict | None = None):
        if len(self.events) >= EVENT_LIMIT:
            raise RuntimeError("Input schedule reached 10,000 events. Export and reset to continue.")
        self.events.append(Event(seq=len(self.events), step=self.step_index, t=self.t,
                                 kind=kind, message=message, payload=payload or {}))

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

    def observe(self):
        self.circuit.apply_silencing(self.interventions)
        pose = self.body.pose()
        sensors = self.body.sensors(self.config.stimulus, self.interventions)
        self.sample = Sample(step=self.step_index, t=self.t, pose=pose, sensors=sensors,
            rates=self.circuit.readout(), motor=self.circuit.motor(self.config.controller == "baseline").tolist(),
            body_signals=self.body.body_signals())

    def record(self):
        # Retain full pose in the latest sample only, avoiding repeated mesh/joint history.
        # Samples are never mutated after creation, so shallow copies are safe here.
        sample = self.sample.model_copy(update={"pose": self.sample.pose.model_copy(update={"legs": []})})
        self.records.append(sample)
        if self.step_index % 2 == 0:
            self.history.append(sample.model_copy(update={"body_signals": {
                k: v for k, v in sample.body_signals.items() if k != "joint_position_rad"}}))
            if self.circuit.kind == "connectome":
                self.type_history.append(self.circuit.type_means().astype(np.float32))
        self.trail.append([sample.pose.x, sample.pose.y])

    def advance(self):
        if self.status == "error":
            raise RuntimeError("Reset the experiment before stepping after an error.")
        if len(self.records) >= RECORD_LIMIT:
            self.status = "paused"
            raise RuntimeError("Recording limit reached. Export this run and reset to continue.")
        if self.protocol_complete:
            raise RuntimeError("Protocol finished. Reset to repeat it.")
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
        sensors = self.body.sensors(self.config.stimulus, self.interventions)
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

    def set_stimulus(self, stimulus: Stimulus, source="manual"):
        self.config.stimulus = stimulus
        if self.body is not None and self.status != "error":
            self.body.set_stimulus(stimulus)
            self.observe()
        self.event("stimulus", f"Target moved to ({stimulus.x:g}, {stimulus.y:g}) mm · intensity {stimulus.intensity:g}", {**stimulus.model_dump(), "source": source})

    def set_interventions(self, interventions: Interventions, source="manual"):
        interventions.for_model(self.config.neural_model)
        self.interventions = interventions
        if self.body is not None and self.status != "error":
            self.observe()
        if self.config.neural_model == "connectome":
            silenced = ", ".join([f"DNa02 {interventions.silence_dna02}"] * (interventions.silence_dna02 != "none")
                                 + interventions.silence_types) or "none"
        else:
            silenced = interventions.silence
        self.event("interventions", f"Inputs L {'off' if interventions.zero_left else 'on'} / R {'off' if interventions.zero_right else 'on'} · silence {silenced}", {**interventions.model_dump(), "source": source})

    def set_parameters(self, parameters: NeuralParameters):
        if self.config.neural_model != "engineered":
            raise ValueError("These parameters belong to the engineered six-unit model. Use the connectome parameters instead.")
        self.config.neural_parameters = parameters
        self.circuit.configure(parameters)
        self.event("parameters", "Neural parameters updated", parameters.model_dump())

    def set_connectome_parameters(self, parameters: ConnectomeParameters):
        if self.config.neural_model != "connectome":
            raise ValueError("Connectome parameters apply when the connectome model is selected.")
        current = self.config.connectome_parameters
        if (parameters.circuit, parameters.dynamics) != (current.circuit, current.dynamics):
            raise ValueError("Changing the circuit or the dynamics starts a fresh run: use Reset with the new settings.")
        parameters.check_against_circuit()
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
        return {"type_rates": np.round(means, 4).tolist(), "turn": circuit.turn(),
                "silenced_neurons": int(len(circuit.silenced(self.interventions))),
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
            "contact_fraction": (self.contact_sum / max(self.contact_samples, 1)).tolist() if self.contact_samples else [],
            "duration_s": self.t, "protocol_complete": self.protocol_complete}

    def fail(self, exc: Exception):
        self.stop_clock()
        self.status = "error"
        self.error = f"{type(exc).__name__}: {exc}"
        if len(self.events) < EVENT_LIMIT:
            self.event("error", self.error)

    @property
    def provenance(self):
        connectome = self.config.neural_model == "connectome"
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
            "sensor_model": "FlyGym compound-eye rendering · engineered green-contrast encoder" if self.config.sensor_model == "vision" else "Geometric bilateral bearing / intensity approximation · v1",
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

    def export(self, directory: Path | None = None):
        # Caller never supplies a filesystem path. Generated IDs are confined under runs/.
        base = directory or ROOT / "runs"
        base.mkdir(parents=True, exist_ok=True)
        destination = base / f"{self.run_id}-{uuid.uuid4().hex[:6]}"
        destination.mkdir()
        metadata = {
            "schema_version": 3, "application_version": APPLICATION_VERSION, "run_id": self.run_id,
            "created_utc": self.started_at, "exported_utc": datetime.now(timezone.utc).isoformat(),
            "initial_config": self.initial_config.model_dump(), "final_config": self.config.model_dump(),
            "final_interventions": self.interventions.model_dump(), "final_sample": self.sample.model_dump() if self.sample else None,
            "status": self.status, "error": self.error, "provenance": self.provenance,
            "time_steps_s": {"physics": PHYSICS_DT if self.config.engine == "flygym" else CONTROL_DT,
                             "neural": NEURAL_DT, "control": CONTROL_DT},
            "units": {"position": "mm", "velocity": "mm/s", "yaw": "rad", "time": "s", "rates_and_commands": "dimensionless"},
            "coordinates": "Right-handed world; +z up; yaw counterclockwise from +x. Camera follows body. Arena is top-down.",
            "warmup_s": .05 if self.config.engine == "flygym" else 0,
            "rendering": {"requested": self.render_enabled, "resolution": [640, 288], "wall_target_hz": 10},
            "performance": {"active_wall_s": self.wall_s, "compute_s": self.compute_s},
            "neural": self.circuit.description(), "metrics": self.metrics, "trial": self.trial,
            "body_joint_order": [str(dof) for dof in self.body.fly.get_jointdofs_order()] if self.body is not None and self.config.engine == "flygym" else [],
            "vision": {k: v for k, v in self.body.vision.items() if k not in {"left", "right"}} if self.body else {},
            "events": [event.model_dump() for event in self.events],
            "recorded_samples": len(self.records), "complete_from_reset": True,
            "platform": platform.platform(), "python": platform.python_version(),
            "dependencies": {name: version(name) for name in ["flygym", "mujoco", "numpy", "fastapi", "pydantic", "numba", "scipy"]},
            "reproducibility": "Fixed seed and step-indexed stimulus/intervention schedule. Same pinned stack tested at absolute tolerance 1e-8; cross-device bitwise equality is not promised.",
        }
        (destination / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False))
        with (destination / "telemetry.csv").open("w", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(["step", "time_s", "x_mm", "y_mm", "z_mm", "yaw_rad", "speed_mm_s", "sensor_l", "sensor_r", "raw_sensor_l", "raw_sensor_r", *["rate_" + n.lower().replace(" ", "_") for n in self.circuit.unit_names], "motor_l", "motor_r"])
            for s in self.records:
                writer.writerow([s.step, s.t, s.pose.x, s.pose.y, s.pose.z, s.pose.yaw, s.pose.velocity,
                                 s.sensors.left, s.sensors.right, s.sensors.raw_left, s.sensors.raw_right, *s.rates, *s.motor])
        with (destination / "body_signals.jsonl").open("w") as output:
            for s in self.records:
                if s.body_signals:
                    output.write(json.dumps({"step": s.step, "t": s.t, **s.body_signals}, allow_nan=False)+"\n")
        archive = destination.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for file in destination.iterdir():
                output.write(file, file.name)
        return {"run_id": self.run_id, "samples": len(self.records), "path": str(destination),
                "download_url": f"/api/exports/{archive.name}"}

    def close(self):
        if self.body is not None:
            self.body.close()
