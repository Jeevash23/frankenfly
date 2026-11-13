from contextlib import asynccontextmanager
from functools import lru_cache
import asyncio
import json
import os
from pathlib import Path
import re
from typing import Literal, get_args
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import Field
from digitalfly.api.models import (CONFIG_SIZE_LIMIT, SERVING_REQUEST, Interventions, RunConfig, Stimulus, Speed,
    StrictModel, NeuralParameters, ConnectomeParameters, BatchRequest, state_schema)
from digitalfly.neural.connectome import circuit_summary, list_circuits, load_circuit, trace_paths
from digitalfly.neural.model import NAMES as ENGINEERED_UNITS, RateCircuit
from digitalfly.data.builds import BuildManager, BuildRequest, catalog, catalog_ready
from digitalfly.data import jobs as background, presets
from digitalfly import scorecard as scorecards
from digitalfly import explore
from digitalfly.vision.flyvis_eyes import available as flyvis_available
from digitalfly.simulation.experiment import APPLICATION_VERSION, RECORD_LIMIT
from digitalfly.data.research import (RUN_KEY, ConnectivityGraph, save_graph, load_graph, list_graphs, list_runs,
    run_detail, delete_run)
from digitalfly.data.research import (BATCH_ID, BatchSummary, RunAnnotations, RunItem, RunPage, annotate_run,
    batch_summary, batch_summary_csv, filter_runs)
from digitalfly.simulation.engines import CONTROL_DT, NEURAL_DT, PHYSICS_DT, ROOT, select_gl
from digitalfly.simulation.worker import PUBLISH_INTERVAL, Invalid, Rejected, SimulationWorker, WorkerStopped

# Request bodies are at most 16 KB, except these. A preset holds a configuration, so all three take the same size.
BODY_LIMITS = {"/api/connectivity/import": 2_000_000, "/api/explore/neuroglancer": 1_000_000, "/api/reset": CONFIG_SIZE_LIMIT,
               "/api/batch/start": CONFIG_SIZE_LIMIT, "/api/configs": CONFIG_SIZE_LIMIT}


@lru_cache(maxsize=8)
def _summary(parameters_json: str, sha256: str):
    # Keyed by the circuit's hash as well, so a rebuilt file is never served from the cache.
    return circuit_summary(ConnectomeParameters.model_validate_json(parameters_json))


def validation_details(errors, prefix=()):
    # Do not echo nonfinite input: the JSON encoder correctly rejects NaN/Inf.
    return [{"location": [*prefix, *e["loc"]], "message": e["msg"], "type": e["type"]} for e in errors]


def extra_origins(text: str | None) -> list[str]:
    """DIGITALFLY_ALLOWED_ORIGINS: comma-separated browser origins, such as http://localhost:9000 for a
    container published on another host port, allowed in addition to this computer's own. Each one's host
    name is also accepted in the Host header. Off by default; see docs/INSTALL.md."""
    origins = []
    for item in filter(None, (part.strip().removesuffix("/") for part in (text or "").split(","))):
        if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d{1,5})?", item):
            raise ValueError(f"DIGITALFLY_ALLOWED_ORIGINS: {item!r} is not an origin like http://localhost:9000 "
                             "(scheme, host name and optional port; no path, no IPv6 literal)")
        origins.append(item.lower())
    return origins


def create_app(config: RunConfig | None = None, render: bool = True):
    extra = extra_origins(os.environ.get("DIGITALFLY_ALLOWED_ORIGINS"))
    worker = SimulationWorker(config, render)
    jobs = background.JobManager()
    builds = BuildManager(jobs)
    port = int(os.environ.get("DIGITALFLY_PORT", "8000"))
    allowed_origins = {f"http://{host}:{p}" for host in ["127.0.0.1", "localhost"] for p in [port, 5173]} | set(extra)
    allowed_hosts = list(dict.fromkeys(["127.0.0.1", "localhost", *(o.split("://")[1].split(":")[0] for o in extra)]))
    connect_src = " ".join(["ws://127.0.0.1:*", "ws://localhost:*", *(o.replace("http", "ws", 1) for o in extra)])

    @asynccontextmanager
    async def lifespan(app):
        # Folders and files that interrupted exports, deletions and builds left behind more than an hour ago.
        app.state.removed_leftovers = await asyncio.to_thread(background.remove_leftovers, ROOT)
        worker.start()
        try:
            yield
        finally:
            await asyncio.to_thread(jobs.close)
            await asyncio.to_thread(worker.close)

    # No Swagger/ReDoc pages: they need a CDN and inline scripts that the CSP below blocks. The schema stays.
    app = FastAPI(title="DigitalFly", version=APPLICATION_VERSION, lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.worker = worker
    app.state.jobs = jobs
    app.state.shutdown_callback = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": validation_details(exc.errors())}, status_code=422)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"detail": "Origin is not permitted to control this local simulation."}, status_code=403)
            # A DELETE needs no body; anything with one must be JSON, which cross-site forms cannot send.
            bodyless = request.method == "DELETE" and request.headers.get("content-length", "0") == "0" \
                and "transfer-encoding" not in request.headers
            if not bodyless and not request.headers.get("content-type", "").lower().startswith("application/json"):
                return JSONResponse({"detail": "Commands require application/json."}, status_code=415)
            try:
                length = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "Invalid content length."}, status_code=400)
            limit = BODY_LIMITS.get(request.url.path, 16384)
            if length > limit or len(await request.body()) > limit:
                return JSONResponse({"detail": "Command body is too large."}, status_code=413)
        # Request bodies are validated on this event loop without reading circuit files (models.reads_files_later).
        token = SERVING_REQUEST.set(True)
        try:
            response = await call_next(request)
        finally:
            SERVING_REQUEST.reset(token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; connect-src 'self' {connect_src}; frame-ancestors 'none'"
        return response

    def stopped():
        error = worker.get_snapshot()["error"]
        return HTTPException(503, "The simulation has stopped" + (f" ({error})" if error else "")
                             + " and cannot take commands. Restart DigitalFly to continue.")

    async def command(name, payload=None):
        if not worker.ready.is_set():
            raise HTTPException(503, "Body engine is still initializing.")
        if worker.stopped():
            raise stopped()
        future = worker.submit(name, payload)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=25)
        except Invalid as exc:
            # The worker validates every configuration in full, circuit files included (see reads_files_later).
            raise HTTPException(422, validation_details(exc.errors, ("body",))) from exc
        except Rejected as exc:
            raise HTTPException(422, str(exc)) from exc
        except WorkerStopped as exc:
            raise stopped() from exc
        except ValidationError as exc:
            # Not the request: the run produced data its own records cannot hold, such as a non-finite position.
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
            raise HTTPException(500, f"The simulation produced invalid data ({exc.title}: {problems}).") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except TimeoutError as exc:
            if worker.stopped():
                raise stopped() from exc
            raise HTTPException(503, "Command timed out. Check status before retrying; an already executing command may complete.") from exc
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    def refuse_building(names):
        building = builds.building()
        if building is not None and building in names:
            raise HTTPException(409, f"The {building} circuit is being built. Wait for the build to finish, then reset.")

    @app.get("/api/health")
    def health():
        return {"service": "DigitalFly", "version": APPLICATION_VERSION, "worker_alive": worker.thread.is_alive(),
                "instance_id": worker.instance_id}

    @app.get("/api/status")
    def status():
        return worker.get_snapshot()

    @app.get("/api/capabilities")
    def capabilities():
        state = worker.get_snapshot()
        model = state["config"]["neural_model"]
        parameters = ConnectomeParameters.model_validate(state["config"]["connectome_parameters"])
        try:
            circuit = {"available": True, **load_circuit(parameters.circuit).summary()}
        except (OSError, ValueError) as exc:
            circuit = {"available": False, "error": str(exc)}
        fields = RunConfig.model_fields
        return {"engines": list(get_args(fields["engine"].annotation)), "default_engine": fields["engine"].default,
                "rendering": state["rendering"],
                "control_interval_s": CONTROL_DT, "neural_interval_s": NEURAL_DT, "physics_interval_s": PHYSICS_DT,
                "telemetry_target_hz": round(1 / PUBLISH_INTERVAL),
                # Compound-eye vision renders the eyes, so it needs a working OpenGL backend (engines.select_gl).
                "compound_eye_sensor": select_gl() is not None,
                "neural_models": {
                    "engineered": f"{len(ENGINEERED_UNITS)} engineered leaky rate units with hand-chosen weights (default)",
                    "connectome": "FlyWire v783 circuits with rate or spiking dynamics: data-derived wiring, assumed signs, engineered dynamics"},
                "default_neural_model": fields["neural_model"].default, "active_neural_model": model,
                "connectome_dynamics": list(get_args(ConnectomeParameters.model_fields["dynamics"].annotation)),
                "active_dynamics": parameters.dynamics if model == "connectome" else None,
                # True only while the active model's wiring comes from connectome data. Never an uploaded brain.
                "biological_connectome": model == "connectome",
                "whole_brain_connectome": model == "connectome" and bool(circuit.get("build", {}).get("whole_brain")),
                "connectome_circuit": circuit, "connectome_circuits_available": len(list_circuits()),
                "circuit_builder_ready": catalog_ready(),
                "flyvis": dict(zip(["available", "reason"], flyvis_available())),
                "body_morphology_sex": "female", "male_body_available": False,
                "shutdown_available": app.state.shutdown_callback is not None,
                "neural_units": len(ENGINEERED_UNITS) if model == "engineered" else circuit.get("neurons"),
                "single_authoritative_instance": True, "input_queue_capacity": worker.commands.maxsize,
                "recording_limit": RECORD_LIMIT, "provenance": state["provenance"],
                "jobs": {"available": True, "kinds": list(background.KINDS)},
                # Shipped presets can be listed and loaded; saving needs a writable configs/local/.
                "presets": {"available": presets.CONFIG_DIR.is_dir(), "writable": presets.writable()}}

    @app.post("/api/run")
    async def run(body: StrictModel):
        return await command("run")

    @app.post("/api/pause")
    async def pause(body: StrictModel):
        return await command("pause")

    @app.post("/api/step")
    async def step(body: StrictModel):
        return await command("step")

    @app.post("/api/reset")
    async def reset(body: RunConfig):
        refuse_building({body.connectome_parameters.circuit} if body.neural_model == "connectome" else set())
        return await command("reset", body.model_dump())

    @app.post("/api/stimulus")
    async def stimulus(body: Stimulus):
        return await command("stimulus", body.model_dump())

    @app.post("/api/interventions")
    async def interventions(body: Interventions):
        # Cell types are checked in the worker, against the circuit the run has loaded.
        return await command("interventions", body.model_dump())

    @app.post("/api/speed")
    async def speed(body: Speed):
        return await command("speed", body.model_dump())

    class ExportRequest(StrictModel):
        # Leaves out the platform string and replaces absolute paths and the host name, for runs to publish.
        share_safe: bool = Field(default=False, strict=True)

    @app.post("/api/export")
    async def export(body: ExportRequest):
        return await command("export", body.model_dump())

    @app.post("/api/parameters")
    async def parameters(body: NeuralParameters):
        return await command("parameters", body.model_dump())

    @app.get("/api/circuit")
    def circuit():
        config = worker.get_snapshot()["config"]
        return RateCircuit(NeuralParameters.model_validate(config["neural_parameters"])).description()

    @app.post("/api/connectome/parameters")
    async def connectome_parameters(body: ConnectomeParameters):
        return await command("connectome_parameters", body.model_dump())

    def current_parameters():
        return ConnectomeParameters.model_validate(worker.get_snapshot()["config"]["connectome_parameters"])

    @app.get("/api/connectome/circuit")
    def connectome_circuit():
        state = worker.get_snapshot()
        parameters = ConnectomeParameters.model_validate(state["config"]["connectome_parameters"])
        try:
            sha256 = load_circuit(parameters.circuit).sha256
        except (OSError, ValueError) as exc:
            raise HTTPException(404, f"Connectome circuit unavailable: {exc}") from exc
        loaded = (state["connectome"] or {}).get("circuit_sha256")
        if loaded is not None and loaded != sha256:
            # The summary must describe the wiring the run is using, not a newer file of the same name.
            raise HTTPException(409, f"The {parameters.circuit} circuit file has changed since this run loaded it. "
                                     "Reset to load the new build.")
        try:
            return _summary(parameters.model_dump_json(), sha256)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, f"Connectome circuit unavailable: {exc}") from exc

    @app.get("/api/vision/flyvis")
    def flyvis_status():
        ok, reason = flyvis_available()
        circuit = current_parameters().circuit
        try:
            from digitalfly.neural.connectome import bridge_path
            bridged = bridge_path(load_circuit(circuit)).is_file()
        except (OSError, ValueError):
            bridged = False
        return {"available": ok, "reason": reason, "circuit": circuit, "circuit_has_bridge": bridged}

    @app.get("/api/connectome/circuits")
    def connectome_circuits():
        return {"circuits": list_circuits(), "active": current_parameters().circuit}

    @app.get("/api/connectome/paths")
    def connectome_paths(source: str, target: str, max_hops: int = 4, limit: int = 10):
        if not 1 <= max_hops <= 6 or not 1 <= limit <= 50:
            raise HTTPException(422, "Choose 1-6 hops and 1-50 paths.")
        try:
            return trace_paths(current_parameters(), source, target, max_hops, limit)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/connectome/catalog")
    def connectome_catalog():
        data = catalog()
        if data is None:
            raise HTTPException(404, "The FlyWire cell-type catalog is not prepared yet. Run: "
                                     "backend/.venv/bin/python scripts/build_circuit.py prepare")
        return data

    @app.get("/api/connectome/build")
    def build_status():
        return builds.status()

    @app.post("/api/connectome/build")
    def build_start(body: BuildRequest):
        try:
            return builds.start(body, worker.circuits_in_use())
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    # Connectivity explorer (digitalfly/explore.py): the whole brain from the prepared archive, or any circuit.
    def explore_call(function, graph: str, **arguments):
        state = worker.get_snapshot()["config"]
        running = state["connectome_parameters"]["circuit"] if state["neural_model"] == "connectome" else None
        try:
            return function(explore.load_graph(graph), running=explore.running_view(running), **arguments)
        except explore.Unavailable as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    Graph = Query(explore.BRAIN, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
                  description='"brain" (the prepared FlyWire v783 archive) or a circuit name')
    Side = Literal["both", "left", "right"]
    Others = Literal["excluded", "excitatory"]

    @app.get("/api/explore/graphs")
    def explore_graphs():
        config = worker.get_snapshot()["config"]
        brain = {"key": explore.BRAIN, "title": "Whole brain (FlyWire v783)", "available": explore.brain_available(),
                 **({} if explore.brain_available() else {"reason": "Prepare the FlyWire archive first: "
                     "backend/.venv/bin/python scripts/build_circuit.py prepare"})}
        return {"graphs": [brain, *({"key": c["name"], "title": c.get("title", c["name"]), "available": "error" not in c,
                                     "neurons": c.get("neurons"), "connections": c.get("connections"),
                                     "committed": c.get("committed")} for c in list_circuits())],
                "running": config["connectome_parameters"]["circuit"] if config["neural_model"] == "connectome" else None,
                "neuroglancer": {"host": explore.NEUROGLANCER, "sources": explore.NG_SOURCES}}

    @app.get("/api/explore/lookup")
    def explore_lookup(q: str = Query(..., max_length=200), graph: str = Graph, limit: int = Query(20, ge=1, le=100)):
        try:
            return explore.lookup(explore.load_graph(graph), q, limit)
        except explore.Unavailable as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/explore/partners")
    def explore_partners(query: str = Query(..., max_length=2000), graph: str = Graph,
                         direction: Literal["upstream", "downstream"] = "upstream",
                         group: Literal["cell_type", "neuron"] = "cell_type", side: Side = "both",
                         threshold: int = Query(5, ge=1, le=1000), limit: int = Query(50, ge=1, le=500),
                         other_transmitters: Others = "excluded"):
        return explore_call(explore.partners, graph, query=query, direction=direction, group=group, side=side,
                            threshold=threshold, limit=limit, other_transmitters=other_transmitters)

    @app.get("/api/explore/paths")
    def explore_paths(source: str = Query(..., max_length=2000), target: str = Query(..., max_length=2000),
                      graph: str = Graph, mode: Literal["strongest", "shortest"] = "strongest",
                      level: Literal["cell_type", "neuron"] = "cell_type", threshold: int = Query(5, ge=1, le=1000),
                      limit: int = Query(10, ge=1, le=50), max_hops: int = Query(10, ge=1, le=20),
                      source_side: Side = "both", target_side: Side = "both", other_transmitters: Others = "excluded"):
        return explore_call(explore.paths, graph, source=source, target=target, mode=mode, level=level,
                            threshold=threshold, limit=limit, max_hops=max_hops, source_side=source_side,
                            target_side=target_side, other_transmitters=other_transmitters)

    @app.get("/api/explore/influence")
    def explore_influence(query: str = Query(..., max_length=2000), graph: str = Graph,
                          direction: Literal["from", "onto"] = "from", group: Literal["cell_type", "neuron"] = "cell_type",
                          side: Side = "both", threshold: int = Query(5, ge=1, le=1000),
                          limit: int = Query(50, ge=1, le=500), signed: bool = True,
                          other_transmitters: Others = "excluded"):
        return explore_call(explore.influence, graph, query=query, direction=direction, group=group, side=side,
                            threshold=threshold, limit=limit, signed=signed, other_transmitters=other_transmitters)

    @app.post("/api/explore/neuroglancer")
    def explore_neuroglancer(body: explore.NeuroglancerRequest):
        try:
            return explore.neuroglancer_request(body)
        except explore.Unavailable as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/batch/start")
    async def batch_start(body: BatchRequest):
        connectome = body.config.neural_model == "connectome" or "connectome_model" in body.conditions
        refuse_building({body.config.connectome_parameters.circuit} if connectome else set())
        return await command("batch_start", body.model_dump())

    @app.post("/api/batch/cancel")
    async def batch_cancel(body: StrictModel):
        return await command("batch_cancel")

    @app.get("/api/runs", responses={200: {"model": RunPage}})
    def runs(response: Response, offset: int = Query(0, ge=0), limit: int = Query(100, ge=0, le=500),
             include_empty: bool = True, model: Literal["engineered", "connectome"] | None = None,
             circuit: str | None = Query(None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"),
             batch: str | None = Query(None, pattern=BATCH_ID), tag: str | None = Query(None, pattern=r"^[A-Za-z0-9 _-]{1,24}$"),
             q: str | None = Query(None, min_length=1, max_length=200)):
        # Filters combine with AND; X-Total-Count counts the matching runs.
        records = filter_runs(list_runs(include_empty=include_empty), model, circuit, batch, tag, q)
        response.headers["X-Total-Count"] = str(len(records))
        return {"runs": records[offset:offset + limit]}

    @app.delete("/api/runs/{key}")
    def delete_saved_run(key: str):
        if not RUN_KEY.fullmatch(key):
            raise HTTPException(404, "Saved run not found.")
        state = worker.get_snapshot()
        batch = state.get("batch") or {}
        trials = {Path(r["path"]).name for r in batch.get("results", [])} if batch.get("status") in {"running", "paused"} else set()
        if key.startswith(state["run_id"] + "-") or key in trials:
            raise HTTPException(409, "This run is still being recorded. Reset, or let the comparison finish, before deleting it.")
        if jobs.active("replay", key):
            raise HTTPException(409, "A replay check of this run is waiting or running. Let it finish, or cancel it, "
                                     "before deleting the run.")
        try:
            return delete_run(key)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, "Saved run not found.") from exc
        except OSError as exc:
            raise HTTPException(500, f"The run could not be deleted: {exc.strerror or type(exc).__name__}.") from exc

    @app.get("/api/runs/{key}")
    def saved_run(key: str):
        try:
            return run_detail(key)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(404, "Saved run not found or unreadable.") from exc

    # Run library annotations, comparison summaries and the State schema.
    @app.patch("/api/runs/{key}", responses={200: {"model": RunItem}})
    def annotate_saved_run(key: str, body: RunAnnotations):
        try:
            return annotate_run(key, body)
        except (ValueError, KeyError, FileNotFoundError) as exc:  # deleted meanwhile: FileNotFoundError
            raise HTTPException(404, "Saved run not found or unreadable.") from exc
        except OSError as exc:
            raise HTTPException(500, f"The notes could not be saved: {exc.strerror or type(exc).__name__}.") from exc

    @app.get("/api/batches/{batch_id}/summary", responses={200: {"model": BatchSummary, "content": {"text/csv": {}}}})
    def comparison_summary(batch_id: str, format: Literal["json", "csv"] = "json"):
        if not re.fullmatch(BATCH_ID, batch_id):
            raise HTTPException(404, "No saved trials belong to this comparison.")
        try:
            summary = batch_summary(batch_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if format == "csv":
            return Response(batch_summary_csv(summary), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="comparison-{batch_id}.csv"'})
        return summary

    @app.get("/api/schema/state")
    def state_json_schema():
        """JSON Schema of the State that /api/ws and /api/status send."""
        return state_schema()

    @app.get("/api/atlas")
    def atlas():
        path = ROOT / "data/atlas/manifest.json"
        if not path.is_file():
            raise HTTPException(404, "Anatomy assets missing. See docs/RESEARCH.md.")
        import json
        return json.loads(path.read_text())

    @app.get("/api/atlas/{sex}")
    def atlas_data(sex: str):
        if sex not in {"female", "male"}:
            raise HTTPException(404, "Unknown anatomy dataset.")
        path = ROOT / "data/atlas" / f"{sex}.json"
        if not path.is_file():
            raise HTTPException(404, "Anatomy asset is missing.")
        return FileResponse(path, media_type="application/json")

    @app.get("/api/connectivity")
    def connectivity_library(response: Response, offset: int = Query(0, ge=0), limit: int = Query(100, ge=0, le=500)):
        datasets = list_graphs()
        response.headers["X-Total-Count"] = str(len(datasets))
        return {"datasets": datasets[offset:offset + limit]}

    @app.post("/api/connectivity/import")
    def connectivity_import(body: ConnectivityGraph):
        return save_graph(body)

    @app.get("/api/connectivity/{key}")
    def connectivity(key: str):
        try:
            return load_graph(key)
        except (ValueError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/examples/connectivity")
    def connectivity_example():
        # Served by the API so the download works in built mode and through the Vite proxy.
        path = ROOT / "data/examples/connectivity-example.json"
        if not path.is_file():
            raise HTTPException(404, "Connectivity format example is missing.")
        return FileResponse(path, media_type="application/json", filename="connectivity-example.json")

    # Background jobs (circuit builds, replay checks and scorecards, in their own processes) and named configurations.
    @app.get("/api/jobs")
    def job_list():
        return {"jobs": jobs.listing()}

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: str, body: StrictModel):
        try:
            return {"job": jobs.cancel(job_id)}
        except KeyError as exc:
            raise HTTPException(404, "Job not found.") from exc

    # Validation scorecards (digitalfly/scorecard.py): the tests, the latest card per model, and scoring as a job.
    @app.get("/api/scorecards")
    def scorecard_list():
        return {"version": scorecards.SCORECARD_VERSION, "tests": scorecards.definitions(),
                "scorecards": scorecards.latest()}

    @app.post("/api/scorecards/run", status_code=202)
    def scorecard_run(body: scorecards.ScorecardRequest):
        target = body.target()
        if body.model == "connectome":
            try:
                target.parameters().check_against_circuit()
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        key = target.key(body.engine)
        try:
            job = background.submit_scorecard(jobs, body.model, body.engine, target.parameters().circuit,
                                              body.dynamics, key=key,
                                              label=f"Scorecard: {scorecards.label_for(target)} ({body.engine})")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"job": jobs.describe(job)}

    @app.post("/api/runs/{key}/replay", status_code=202)
    def replay_saved_run(key: str, body: StrictModel):
        directory = ROOT / "runs" / key
        if not RUN_KEY.fullmatch(key) or directory.is_symlink() or not (directory / "metadata.json").is_file():
            raise HTTPException(404, "Saved run not found.")
        try:
            job = background.submit_replay(jobs, directory)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"job": jobs.describe(job)}

    @app.get("/api/configs")
    def config_list():
        return {"configs": presets.list_presets()}

    @app.get("/api/configs/{name}")
    def config_get(name: str):
        try:
            return presets.load(name)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except presets.PresetUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(422, f"The {name} preset is invalid: {exc}") from exc

    @app.post("/api/configs", status_code=201)
    def config_save(body: presets.PresetRequest):
        # Validated again here, off the event loop, against the circuit files (see models.reads_files_later).
        try:
            return presets.save(body)
        except presets.PresetConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except presets.PresetStorageError as exc:
            raise HTTPException(503, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"The preset could not be saved: {exc.strerror or type(exc).__name__}.") from exc

    @app.delete("/api/configs/{name}")
    def config_delete(name: str):
        try:
            return presets.delete(name)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except presets.PresetConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"The preset could not be deleted: {exc.strerror or type(exc).__name__}.") from exc

    class Shutdown(StrictModel):
        instance_id: str

    @app.post("/api/shutdown")
    async def shutdown(body: Shutdown, background: BackgroundTasks):
        if body.instance_id != worker.instance_id:
            raise HTTPException(409, "This is a different server session. Refresh before quitting.")
        if app.state.shutdown_callback is None:
            raise HTTPException(409, "This server was not started with the DigitalFly launcher. Stop it in its terminal.")
        background.add_task(app.state.shutdown_callback)
        return {"status": "shutting_down"}

    @app.get("/api/eyes")
    def eyes():
        data = worker.get_eyes()
        if data is None:
            raise HTTPException(404, "Select compound-eye vision to render the eye cameras.")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/exports/{filename}")
    def download(filename: str):
        if not re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{8}-[a-f0-9]{6}\.zip", filename):
            raise HTTPException(404, "Export not found.")
        path = ROOT / "runs" / filename
        if not path.is_file():
            raise HTTPException(404, "Export not found.")
        return FileResponse(path, filename=filename, media_type="application/zip")

    @app.get("/api/frame")
    def frame():
        data = worker.get_frame()
        if data is None:
            raise HTTPException(404, "No physics-rendered frame is available. Use the labeled arena view.")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    encoded = {"key": None, "text": ""}

    def telemetry_message():
        """The latest snapshot as JSON, encoded once per revision and subscriber count and shared by every client."""
        snapshot = worker.get_snapshot()
        key = (snapshot["revision"], snapshot["subscribers"])
        if encoded["key"] != key:
            # Starlette's send_json encoding, so messages stay byte-identical.
            encoded.update(key=key, text=json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False))
        return key, encoded["text"]

    @app.websocket("/api/ws")
    async def telemetry(ws: WebSocket):
        origin = ws.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await ws.close(code=1008, reason="Origin not allowed")
            return
        await ws.accept()
        worker.subscribe(1)
        async def sender():
            sent = None
            while True:
                # One latest snapshot, no per-subscriber telemetry queues, and never one this client already has.
                key, text = telemetry_message()
                if key != sent:
                    await asyncio.wait_for(ws.send_text(text), timeout=2)
                    sent = key
                await asyncio.sleep(PUBLISH_INTERVAL)
        async def receiver():
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            worker.subscribe(-1)
            for task in tasks:
                task.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

    dist = ROOT / "frontend/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint.")
        if path == "favicon.svg" and (dist / path).is_file():
            return FileResponse(dist / path)
        if not (dist / "index.html").is_file():
            raise HTTPException(503, "Frontend build missing. Run ./scripts/setup.sh first, or use the development server.")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
