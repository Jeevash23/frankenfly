"""One authoritative worker, bounded commands, one replaceable display snapshot."""
from concurrent.futures import Future
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
import time
import uuid
import psutil
from digitalfly.api.models import (State, RunConfig, Stimulus, Interventions, Speed, NeuralParameters,
    ConnectomeParameters, BatchRequest)
from digitalfly.simulation.experiment import Experiment, RECORD_LIMIT
from digitalfly.simulation.engines import CONTROL_DT


class SimulationWorker:
    def __init__(self, config: RunConfig | None = None, render=True):
        self.config = config or RunConfig()
        self.render = render
        self.instance_id = uuid.uuid4().hex
        self.commands = Queue(maxsize=64)
        self.stopping = Event()
        self.ready = Event()
        self.lock = Lock()
        self.thread = Thread(target=self._loop, name="digitalfly-simulation", daemon=False)
        self.experiment = None
        self.frame_bytes = None
        self.frame_revision = 0
        self.subscribers = 0
        self.revision = 0
        self.batch = None
        self.batch_request = None
        self.trials = []
        self.trial_index = 0
        self.eye_bytes = None
        self.snapshot = State(instance_id=self.instance_id, revision=0, run_id="initializing",
            status="initializing", config=self.config, interventions=Interventions()).model_dump()

    def start(self):
        self.thread.start()

    def submit(self, name, payload=None) -> Future:
        future = Future()
        if self.stopping.is_set():
            future.set_exception(RuntimeError("The simulation worker is shutting down."))
        else:
            try:
                self.commands.put_nowait((name, payload or {}, future))
            except Full:
                future.set_exception(RuntimeError("Command queue is full. Wait and retry."))
        return future

    def get_snapshot(self):
        with self.lock:
            return {**self.snapshot, "subscribers": self.subscribers}

    def get_frame(self):
        with self.lock:
            return self.frame_bytes

    def get_eyes(self):
        with self.lock:
            return self.eye_bytes

    def subscribe(self, delta):
        with self.lock:
            self.subscribers = max(0, self.subscribers + delta)

    def _publish(self, capture=False):
        exp = self.experiment
        if capture and exp.body is not None:
            try:
                frame = exp.body.frame()
                with self.lock:
                    self.frame_bytes = frame
                    self.frame_revision += 1
            except Exception as exc:
                exp.body.render_error = f"Rendering failed: {exc}. Arena shows backend poses."
                if exp.body.renderer is not None:
                    exp.body.renderer.close()
                    exp.body.renderer = None
                with self.lock:
                    self.frame_bytes = None
        self.revision += 1
        wall_s = exp.wall_s
        state = State(instance_id=self.instance_id, revision=self.revision, run_id=exp.run_id,
            status=exp.status, error=exp.error, config=exp.config, interventions=exp.interventions,
            sample=exp.sample, history=list(exp.history), trail=list(exp.trail), events=exp.events[-50:],
            wall_s=wall_s, real_time_factor=exp.t / max(wall_s, 1e-9) if exp.t else 0,
            compute_real_time_factor=exp.t / max(exp.compute_s, 1e-9) if exp.t else 0,
            memory_mb=psutil.Process().memory_info().rss / 1e6, frame_revision=self.frame_revision,
            rendering=exp.body is not None and exp.body.renderer is not None,
            render_error=exp.body.render_error if exp.body else None,
            recording_samples=len(exp.records), recording_limit=RECORD_LIMIT, provenance=exp.provenance,
            metrics=exp.metrics, vision=exp.body.vision if exp.body else {}, batch=self.batch,
            connectome=exp.connectome_snapshot())
        with self.lock:
            self.snapshot = state.model_dump()
            self.eye_bytes = exp.body.eye_frame if exp.body else None

    def _start_trial(self):
        condition, seed = self.trials[self.trial_index]
        config = self.batch_request.config.model_copy(deep=True)
        config.seed = seed
        config.controller = "baseline" if condition == "baseline" else "neural"
        if condition in {"engineered_model", "connectome_model"}:
            config.neural_model = "engineered" if condition == "engineered_model" else "connectome"
        config.initial_interventions = Interventions(zero_left=condition == "left_sensor_off",
            silence="descending" if condition == "descending_off" else "none",
            silence_dna02={"dna02_left_off": "left", "dna02_right_off": "right",
                           "dna02_both_off": "both"}.get(condition, "none"),
            silence_types=[self.batch_request.cell_type] if condition == "cell_type_off" else [])
        self.experiment.reset(config)
        if self.experiment.status == "error":
            self.batch["status"] = "failed"
            self.batch["error"] = self.experiment.error
            return
        self.experiment.trial = {"batch_id": self.batch["id"], "condition": condition, "seed": seed,
            "index": self.trial_index + 1, "total": len(self.trials), "neural_model": config.neural_model,
            "cell_type": self.batch_request.cell_type if condition == "cell_type_off" else None}
        self.batch.update(status="running", current=self.trial_index+1, condition=condition, seed=seed)
        self.experiment.start_clock()
        self.experiment.status = "running"
        self.experiment.event("trial_start", f"Comparison {self.trial_index+1}/{len(self.trials)} · {condition} · seed {seed}")

    def _finish_trial(self):
        result = self.experiment.export()
        self.batch["results"].append({**result, **self.experiment.trial, "metrics": self.experiment.metrics})
        self.trial_index += 1
        if self.trial_index == len(self.trials):
            self.batch["status"] = "completed"
            self.experiment.event("batch_complete", "Comparison complete; every trial saved locally")
        else:
            self._start_trial()

    def _command(self, name, payload):
        exp = self.experiment
        batch_active = self.batch and self.batch["status"] in {"running", "paused"}
        if batch_active and name not in {"run", "pause", "batch_cancel", "export"}:
            raise ValueError("Cancel the active comparison before changing its controlled conditions.")
        if name == "reset":
            with self.lock:
                self.frame_bytes = None
            exp.reset(RunConfig.model_validate(payload))
            self.batch = None
        elif name == "run":
            if exp.status == "error":
                raise ValueError("Reset the experiment to recover from the error.")
            if len(exp.records) >= RECORD_LIMIT:
                raise ValueError("Recording limit reached. Export and reset before continuing.")
            if exp.protocol_complete:
                raise ValueError("Protocol completed. Reset to repeat it.")
            if exp.status != "running":
                exp.event("run", "Simulation started")
                exp.start_clock()
                exp.status = "running"
                if batch_active:
                    self.batch["status"] = "running"
        elif name == "pause":
            if exp.status == "running":
                exp.stop_clock()
                exp.status = "paused"
                exp.event("pause", "Simulation paused")
                if batch_active:
                    self.batch["status"] = "paused"
        elif name == "step":
            if exp.status != "paused":
                raise ValueError("Step is available only while paused.")
            exp.check_advance()  # a finished protocol or full recording: refused, and the run stays valid
            start = time.perf_counter()
            exp.event("step", "Advanced one control interval · 10 ms")
            try:
                exp.advance()
            except Exception as exc:
                exp.fail(exc)
                raise
            finally:
                exp.active_wall_s += time.perf_counter() - start
        elif name == "stimulus":
            exp.set_stimulus(Stimulus.model_validate(payload))
        elif name == "interventions":
            exp.set_interventions(Interventions.model_validate(payload))
        elif name == "speed":
            exp.config.speed = Speed.model_validate(payload).speed
            exp.event("speed", f"Requested speed {exp.config.speed:g}×", payload)
        elif name == "parameters":
            exp.set_parameters(NeuralParameters.model_validate(payload))
        elif name == "connectome_parameters":
            exp.set_connectome_parameters(ConnectomeParameters.model_validate(payload))
        elif name == "batch_start":
            self.batch_request = BatchRequest.model_validate(payload)
            self.trials = [(condition, seed) for seed in self.batch_request.seeds for condition in self.batch_request.conditions]
            self.trial_index = 0
            self.batch = {"id": uuid.uuid4().hex[:12], "status": "running", "total": len(self.trials),
                "current": 0, "results": [], "protocol": self.batch_request.config.protocol.name,
                "cell_type": self.batch_request.cell_type}
            self._start_trial()
        elif name == "batch_cancel":
            if not batch_active:
                raise ValueError("No comparison is active.")
            exp.stop_clock()
            exp.status = "paused"
            self.batch["status"] = "cancelled"
            exp.event("batch_cancel", "Comparison cancelled; current partial trial retained for export")
        elif name == "export":
            result = exp.export(share_safe=bool(payload.get("share_safe")))
            exp.event("export", f"Saved {len(exp.records)} samples locally")
            return result
        else:
            raise ValueError("Unknown command")

    def _loop(self):
        try:
            self.experiment = Experiment(self.config, self.render)
            self._publish(capture=True)
            self.ready.set()
            last_publish = time.perf_counter()
            while not self.stopping.is_set():
                exp = self.experiment
                try:
                    item = self.commands.get(timeout=0 if exp.status == "running" else .1)
                except Empty:
                    item = None
                if item:
                    name, payload, future = item
                    if future.set_running_or_notify_cancel():
                        try:
                            result = self._command(name, payload)
                            self._publish(capture=name in {"reset", "step", "pause", "stimulus", "batch_start", "batch_cancel"})
                            future.set_result(result if result is not None else self.get_snapshot())
                        except Exception as exc:
                            self._publish()
                            future.set_exception(exc)
                    self.commands.task_done()
                    continue
                if exp.status == "running":
                    start = time.perf_counter()
                    try:
                        exp.advance()
                        if exp.protocol_complete:
                            if self.batch and self.batch["status"] == "running":
                                self._finish_trial()
                            self._publish(capture=True)
                    except Exception as exc:
                        exp.fail(exc)
                        if self.batch and self.batch["status"] in {"running", "paused"}:
                            self.batch.update(status="failed", error=str(exc))
                    elapsed = time.perf_counter() - start
                    self.stopping.wait(max(0, CONTROL_DT / exp.config.speed - elapsed))
                now = time.perf_counter()
                if now - last_publish >= .1:
                    self._publish(capture=exp.status == "running")
                    last_publish = now
        except Exception as exc:
            with self.lock:
                self.snapshot = {**self.snapshot, "status": "error", "error": f"Worker failed: {type(exc).__name__}: {exc}"}
            self.ready.set()
        finally:
            if self.experiment is not None:
                self.experiment.close()
            while not self.commands.empty():
                _, _, future = self.commands.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError("Simulation worker stopped."))

    def close(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError("Simulation worker did not stop within 15 seconds.")
