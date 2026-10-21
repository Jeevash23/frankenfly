"""One authoritative worker, bounded commands, one replaceable display snapshot.

The thread must outlive any failure: a command that fails answers its caller, and a state that cannot be
published puts the run into the error state. Neither ends the loop.
"""
from concurrent.futures import Future
from queue import Queue, Empty, Full
from threading import Event, Lock, Thread
import time
import uuid
import psutil
from digitalfly.api.models import (State, RunConfig, Stimulus, Interventions, Speed, NeuralParameters,
    ConnectomeParameters, BatchRequest, check_cell_types, silenced_types)
from digitalfly.simulation.experiment import Experiment, RECORD_LIMIT
from digitalfly.simulation.engines import CONTROL_DT

QUEUE_CAPACITY = 64
PUBLISH_INTERVAL = .1  # telemetry while running, about 10 Hz
HEARTBEAT_INTERVAL = 1.  # while not running; commands publish at once
BATCH_COMMANDS = {"run", "pause", "batch_cancel", "export", "speed"}  # none changes a controlled condition


class Rejected(ValueError):
    """The command does not fit the experiment that is running (HTTP 422); nothing was changed."""


class WorkerStopped(RuntimeError):
    """The simulation thread has exited; only restarting DigitalFly brings it back."""


class SimulationWorker:
    def __init__(self, config: RunConfig | None = None, render=True):
        self.config = config or RunConfig()
        self.render = render
        self.instance_id = uuid.uuid4().hex
        self.commands = Queue(maxsize=QUEUE_CAPACITY)
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
        self.workbench = None  # the configuration to restore when a comparison ends
        self.trials = []
        self.trial_index = 0
        self.eye_bytes = None
        self.snapshot = State(instance_id=self.instance_id, revision=0, run_id="initializing",
            status="initializing", config=self.config, interventions=Interventions()).model_dump()

    def start(self):
        self.thread.start()

    def stopped(self) -> bool:
        """True once the thread has exited after starting: commands can no longer run."""
        return self.ready.is_set() and not self.thread.is_alive()

    def submit(self, name, payload=None) -> Future:
        future = Future()
        if self.stopping.is_set():
            future.set_exception(RuntimeError("The simulation worker is shutting down."))
        elif self.stopped():
            future.set_exception(WorkerStopped("The simulation worker has stopped."))
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

    def circuits_in_use(self) -> set[str]:
        """Circuit names the running experiment has loaded or an active comparison will load (any thread)."""
        names = set()
        circuit = getattr(self.experiment, "circuit", None)
        if circuit is not None and circuit.kind == "connectome":
            names.add(circuit.data.key)
        request = self.batch_request
        if request is not None and self._batch_active() and (
                request.config.neural_model == "connectome" or "connectome_model" in request.conditions):
            names.add(request.config.connectome_parameters.circuit)
        return names

    def _batch_active(self):
        batch = self.batch
        return batch is not None and batch["status"] in {"running", "paused"}

    def _publish(self, capture=False):
        exp = self.experiment
        if capture and exp.body is not None:
            try:
                frame = exp.body.frame()
                with self.lock:
                    if frame is not None and frame != self.frame_bytes:
                        self.frame_revision += 1
                    self.frame_bytes = frame
            except Exception as exc:
                exp.body.render_error = f"Rendering failed: {exc}. Arena shows backend poses."
                if exp.body.renderer is not None:
                    exp.body.renderer.close()
                    exp.body.renderer = None
                with self.lock:
                    self.frame_bytes = None
        wall_s = exp.wall_s
        # Built from already validated parts: validating State would re-run RunConfig's checks against the circuit
        # files on disk at every publish, which costs time and can disagree with the circuit that is loaded.
        state = State.model_construct(instance_id=self.instance_id, revision=self.revision, run_id=exp.run_id,
            status=exp.status, error=exp.error, config=exp.config, interventions=exp.interventions,
            sample=exp.sample, history=list(exp.history), trail=list(exp.trail), events=exp.events[-50:],
            wall_s=wall_s, real_time_factor=exp.t / max(wall_s, 1e-9) if exp.t else 0.,
            compute_real_time_factor=exp.t / max(exp.compute_s, 1e-9) if exp.t else 0.,
            memory_mb=psutil.Process().memory_info().rss / 1e6, frame_revision=self.frame_revision,
            rendering=exp.body is not None and exp.body.renderer is not None,
            render_error=exp.body.render_error if exp.body else None,
            recording_samples=len(exp.records), recording_limit=RECORD_LIMIT, provenance=exp.provenance,
            metrics=exp.metrics, vision=exp.body.vision if exp.body else {}, batch=self.batch,
            connectome=exp.connectome_snapshot()).model_dump()
        with self.lock:
            previous = self.snapshot
        # A new revision only when something besides the memory reading changed: clients skip the rest.
        if all(value == previous.get(key) for key, value in state.items() if key != "memory_mb"):
            return
        self.revision += 1
        state["revision"] = self.revision
        with self.lock:
            self.snapshot = state
            self.eye_bytes = exp.body.eye_frame if exp.body else None

    def _publish_safely(self, capture=False):
        """Publish, never raising: a state that cannot be summarized puts the run into the error state."""
        try:
            self._publish(capture)
            return
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                if self.experiment.status != "error":
                    self.experiment.fail(exc)
                if self._batch_active():
                    self.batch.update(status="failed", error=error)
                self._publish()
                return
            except Exception:
                pass
        with self.lock:
            if self.snapshot["status"] != "error" or self.snapshot["error"] != error:
                self.revision += 1
                self.snapshot = {**self.snapshot, "revision": self.revision, "status": "error",
                                 "error": f"{error} (the state could not be displayed; Reset to recover)"}

    @staticmethod
    def _trial_config(request: BatchRequest, condition: str, seed: int) -> RunConfig:
        """One trial's configuration, validated in full like any reset, so an invalid one fails before the first trial."""
        overrides = {"seed": seed, "controller": "baseline" if condition == "baseline" else "neural",
            "initial_interventions": Interventions(zero_left=condition == "left_sensor_off",
                silence="descending" if condition == "descending_off" else "none",
                silence_dna02={"dna02_left_off": "left", "dna02_right_off": "right",
                               "dna02_both_off": "both"}.get(condition, "none"),
                silence_types=[request.cell_type] if condition == "cell_type_off" else []).model_dump()}
        if condition in {"engineered_model", "connectome_model"}:
            overrides["neural_model"] = "engineered" if condition == "engineered_model" else "connectome"
        return RunConfig.model_validate({**request.config.model_dump(), **overrides})

    def _start_trial(self):
        condition, seed, config = self.trials[self.trial_index]
        self.experiment.reset(config)
        if self.experiment.status == "error":
            self._end_batch("failed", self.experiment.error)
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
        self.experiment.trial = None  # saved
        self.trial_index += 1
        if self.trial_index == len(self.trials):
            self._end_batch("completed")
        else:
            self._start_trial()

    def _end_batch(self, status, error=None):
        """Close the comparison, then return the workbench to its configuration from before it, so neither the
        Workbench nor the next comparison inherits the last trial's model, controller or interventions. An
        unfinished trial (cancelled or failed) is saved first, marked partial. Never raises."""
        exp = self.experiment
        self.batch["status"] = status
        if error is not None:
            self.batch["error"] = error
        if exp.trial is not None and exp.step_index:
            try:
                exp.trial["partial"] = True
                self.batch["partial"] = {**exp.export(), **exp.trial, "metrics": exp.metrics}
            except Exception as exc:
                self.batch["partial_error"] = f"The unfinished trial could not be saved: {type(exc).__name__}: {exc}"
        workbench, self.workbench = self.workbench, None
        if workbench is None:
            return
        message = {"completed": "Comparison complete; every trial saved locally",
                   "cancelled": "Comparison cancelled" + ("; the unfinished trial was saved, marked partial"
                                                           if "partial" in self.batch else ""),
                   "failed": f"Comparison failed: {error}"}[status]
        try:
            exp.reset(RunConfig.model_validate(workbench.model_dump()))
            exp.event({"completed": "batch_complete", "cancelled": "batch_cancel", "failed": "batch_failed"}[status],
                      message + " · Workbench configuration restored")
        except Exception as exc:
            self.batch["restore_error"] = (f"The Workbench configuration from before the comparison could not be "
                                           f"restored: {type(exc).__name__}: {exc}")

    def _command(self, name, payload):
        exp = self.experiment
        batch_active = self._batch_active()
        if batch_active and name not in BATCH_COMMANDS:
            raise ValueError("Cancel the active comparison before changing its controlled conditions.")
        if name == "reset":
            exp.reset(RunConfig.model_validate(payload))
            with self.lock:
                self.frame_bytes = None
            self.batch = self.workbench = None
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
            interventions = Interventions.model_validate(payload)
            if exp.circuit.kind == "connectome":
                # The circuit this run loaded, not the file of that name, which may have been rebuilt since.
                try:
                    check_cell_types(silenced_types(interventions), exp.circuit.data)
                except ValueError as exc:
                    raise Rejected(str(exc)) from exc
            exp.set_interventions(interventions)
        elif name == "speed":
            exp.config.speed = Speed.model_validate(payload).speed
            exp.event("speed", f"Requested speed {exp.config.speed:g}×", payload)
            if batch_active:  # pacing only: the remaining trials keep the new speed
                for _, _, config in self.trials[self.trial_index + 1:]:
                    config.speed = exp.config.speed
        elif name == "parameters":
            exp.set_parameters(NeuralParameters.model_validate(payload))
        elif name == "connectome_parameters":
            exp.set_connectome_parameters(ConnectomeParameters.model_validate(payload))
        elif name == "batch_start":
            request = BatchRequest.model_validate(payload)
            trials = [(condition, seed, self._trial_config(request, condition, seed))
                      for seed in request.seeds for condition in request.conditions]
            self.batch_request, self.trials, self.trial_index = request, trials, 0
            self.workbench = exp.config.model_copy(update={"initial_interventions": exp.interventions.model_copy()},
                                                   deep=True)
            self.batch = {"id": uuid.uuid4().hex[:12], "status": "running", "total": len(self.trials),
                "current": 0, "results": [], "protocol": request.config.protocol.name,
                "cell_type": request.cell_type, "max_speed": request.max_speed}
            try:
                self._start_trial()
            except Exception:
                self.batch = self.workbench = None  # the first trial could not be built; the workbench is untouched
                raise
        elif name == "batch_cancel":
            if not batch_active:
                raise ValueError("No comparison is active.")
            exp.stop_clock()
            exp.status = "paused"
            exp.event("batch_cancel", "Comparison cancelled")
            self._end_batch("cancelled")
        elif name == "export":
            result = exp.export(share_safe=bool(payload.get("share_safe")))
            exp.event("export", f"Saved {len(exp.records)} samples locally")
            return result
        else:
            raise ValueError("Unknown command")

    def _handle(self, name, payload, future):
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = self._command(name, payload)
        except Exception as exc:
            self._publish_safely()
            future.set_exception(exc)
        else:
            self._publish_safely(capture=name in {"reset", "step", "pause", "stimulus", "batch_start", "batch_cancel"})
            future.set_result(result if result is not None else self.get_snapshot())
        finally:
            if not future.done():
                future.set_exception(RuntimeError("The command did not finish."))

    def _loop(self):
        try:
            self.experiment = Experiment(self.config, self.render)
            self._publish_safely(capture=True)
            self.ready.set()
            last_publish = time.perf_counter()
            while not self.stopping.is_set():
                exp = self.experiment
                try:
                    item = self.commands.get(timeout=0 if exp.status == "running" else PUBLISH_INTERVAL)
                except Empty:
                    item = None
                if item:
                    self._handle(*item)
                    self.commands.task_done()
                    continue
                if exp.status == "running":
                    start = time.perf_counter()
                    try:
                        exp.advance()
                        if exp.protocol_complete:
                            if self.batch and self.batch["status"] == "running":
                                self._finish_trial()
                            self._publish_safely(capture=True)
                    except Exception as exc:
                        exp.fail(exc)
                        if self._batch_active():
                            self._end_batch("failed", str(exc))
                    # Comparisons at maximum speed run unpaced; otherwise the display speed paces the run.
                    if not (self._batch_active() and self.batch_request.max_speed):
                        elapsed = time.perf_counter() - start
                        self.stopping.wait(max(0, CONTROL_DT / exp.config.speed - elapsed))
                now = time.perf_counter()
                if now - last_publish >= (PUBLISH_INTERVAL if exp.status == "running" else HEARTBEAT_INTERVAL):
                    self._publish_safely(capture=exp.status == "running")
                    last_publish = now
        except Exception as exc:
            with self.lock:
                self.snapshot = {**self.snapshot, "revision": self.snapshot["revision"] + 1, "status": "error",
                                 "error": f"Worker failed: {type(exc).__name__}: {exc}"}
            self.ready.set()
        finally:
            if self.experiment is not None:
                self.experiment.close()
            while not self.commands.empty():
                _, _, future = self.commands.get_nowait()
                if not future.done():
                    future.set_exception(WorkerStopped("The simulation worker stopped."))

    def close(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError("Simulation worker did not stop within 15 seconds.")
