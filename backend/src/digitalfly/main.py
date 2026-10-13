from contextlib import asynccontextmanager
from functools import lru_cache
import asyncio
import json
import os
from pathlib import Path
import re
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from digitalfly.api.models import (Interventions, RunConfig, Stimulus, Speed, StrictModel, NeuralParameters,
    ConnectomeParameters, BatchRequest, check_cell_types, silenced_types)
from digitalfly.neural.connectome import circuit_summary, list_circuits, load_circuit, trace_paths
from digitalfly.neural.model import RateCircuit
from digitalfly.data.builds import BuildManager, BuildRequest, catalog
from digitalfly.simulation.experiment import APPLICATION_VERSION
from digitalfly.data.research import ConnectivityGraph, save_graph, load_graph, list_graphs, list_runs, run_detail
from digitalfly.simulation.engines import ROOT
from digitalfly.simulation.worker import SimulationWorker


@lru_cache(maxsize=8)
def _summary(parameters_json: str, sha256: str):
    # Keyed by the circuit's hash as well, so a rebuilt file is never served from the cache.
    return circuit_summary(ConnectomeParameters.model_validate_json(parameters_json))


def create_app(config: RunConfig | None = None, render: bool = True):
    worker = SimulationWorker(config, render)
    builds = BuildManager()
    port = int(os.environ.get("DIGITALFLY_PORT", "8000"))
    allowed_origins = {f"http://{host}:{p}" for host in ["127.0.0.1", "localhost"] for p in [port, 5173]}

    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        try:
            yield
        finally:
            await asyncio.to_thread(builds.close)
            await asyncio.to_thread(worker.close)

    app = FastAPI(title="DigitalFly", version=APPLICATION_VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.worker = worker
    app.state.shutdown_callback = None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo nonfinite input: the JSON encoder correctly rejects NaN/Inf.
        details = [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"detail": "Origin is not permitted to control this local simulation."}, status_code=403)
            if not request.headers.get("content-type", "").lower().startswith("application/json"):
                return JSONResponse({"detail": "Commands require application/json."}, status_code=415)
            try:
                length = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "Invalid content length."}, status_code=400)
            limit = 2_000_000 if request.url.path == "/api/connectivity/import" else 16384
            if length > limit or len(await request.body()) > limit:
                return JSONResponse({"detail": "Command body is too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'"
        return response

    async def command(name, payload=None):
        if not worker.ready.is_set():
            raise HTTPException(503, "Body engine is still initializing.")
        future = worker.submit(name, payload)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=25)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(503, "Command timed out. Check status before retrying; an already executing command may complete.") from exc
        except Exception as exc:
            raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    @app.get("/api/health")
    def health():
        return {"service": "DigitalFly", "worker_alive": worker.thread.is_alive(), "instance_id": worker.instance_id}

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
        return {"engines": ["flygym", "toy"], "default_engine": "flygym", "rendering": state["rendering"],
                "control_interval_s": .01, "neural_interval_s": .001, "physics_interval_s": .0001,
                "telemetry_target_hz": 10, "compound_eye_sensor": True,
                "neural_models": {
                    "engineered": "Six engineered leaky rate units with hand-chosen weights (default)",
                    "connectome": "FlyWire v783 circuits with rate or spiking dynamics: data-derived wiring, assumed signs, engineered dynamics"},
                "default_neural_model": "engineered", "active_neural_model": model,
                "connectome_dynamics": ["rate", "spiking"], "active_dynamics": parameters.dynamics if model == "connectome" else None,
                # True only while the active model's wiring comes from connectome data. Never an uploaded brain.
                "biological_connectome": model == "connectome",
                "whole_brain_connectome": model == "connectome" and bool(circuit.get("build", {}).get("whole_brain")),
                "connectome_circuit": circuit, "connectome_circuits_available": len(list_circuits()),
                "circuit_builder_ready": catalog() is not None,
                "body_morphology_sex": "female", "male_body_available": False,
                "shutdown_available": app.state.shutdown_callback is not None,
                "neural_units": 6 if model == "engineered" else circuit.get("neurons"),
                "single_authoritative_instance": True, "input_queue_capacity": 64,
                "recording_limit": 30000, "provenance": state["provenance"]}

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
        return await command("reset", body.model_dump())

    @app.post("/api/stimulus")
    async def stimulus(body: Stimulus):
        return await command("stimulus", body.model_dump())

    @app.post("/api/interventions")
    async def interventions(body: Interventions):
        config = worker.get_snapshot()["config"]
        if config["neural_model"] == "connectome":
            circuit = ConnectomeParameters.model_validate(config["connectome_parameters"]).circuit
            try:
                check_cell_types(silenced_types(body), circuit)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        return await command("interventions", body.model_dump())

    @app.post("/api/speed")
    async def speed(body: Speed):
        return await command("speed", body.model_dump())

    @app.post("/api/export")
    async def export(body: StrictModel):
        return await command("export")

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
        parameters = current_parameters()
        try:
            return _summary(parameters.model_dump_json(), load_circuit(parameters.circuit).sha256)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, f"Connectome circuit unavailable: {exc}") from exc

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
            return builds.start(body)
        except FileNotFoundError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/batch/start")
    async def batch_start(body: BatchRequest):
        return await command("batch_start", body.model_dump())

    @app.post("/api/batch/cancel")
    async def batch_cancel(body: StrictModel):
        return await command("batch_cancel")

    @app.get("/api/runs")
    def runs():
        return {"runs": list_runs()}

    @app.get("/api/runs/{key}")
    def saved_run(key: str):
        try:
            return run_detail(key)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(404, "Saved run not found or unreadable.") from exc

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
    def connectivity_library():
        return {"datasets": list_graphs()}

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

    @app.websocket("/api/ws")
    async def telemetry(ws: WebSocket):
        origin = ws.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            await ws.close(code=1008, reason="Origin not allowed")
            return
        await ws.accept()
        worker.subscribe(1)
        async def sender():
            while True:
                # One latest snapshot, no per-subscriber telemetry queues.
                await asyncio.wait_for(ws.send_json(worker.get_snapshot()), timeout=2)
                await asyncio.sleep(.1)
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
