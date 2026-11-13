"""Drive a running DigitalFly app from Python: the same commands as the browser, over its local HTTP API.

    from digitalfly.client import Client
    fly = Client()                                   # the app at http://127.0.0.1:8000 (scripts/start.sh)
    fly.reset({"engine": "toy", "neural_model": "connectome", "seed": 3})
    fly.stimulus(10, 5)
    fly.run()
    state = fly.wait_until(lambda s: s["sample"]["t"] >= 2)
    fly.pause()
    fly.connectome_parameters(output_gain=2)        # merged into the run's current parameters
    fly.interventions(silence_dna02="left")         # likewise merged into the current interventions
    saved = fly.export(share_safe=True)

Every method returns the server's JSON (a command returns the new state, as /api/status does). The app runs
one experiment for every client, the browser included, so these commands change what the browser shows.
A refused command raises ClientError with the HTTP status and the server's message. Commands carry the Origin
header of the app's own address, which the server accepts. `stream` reads live telemetry over the WebSocket
and needs the `websockets` package (installed with the app); everything else uses the standard library only,
so this file also works when copied into another environment. For many trials without the app, use
digitalfly.toolkit, which is faster and runs in parallel.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000"


class ClientError(Exception):
    """A refused or failed request: `status` is the HTTP status, `detail` the server's explanation."""

    def __init__(self, status: int, detail):
        self.status, self.detail = status, detail
        if isinstance(detail, list):  # validation errors: one "location: message" each
            detail = "; ".join(f"{'.'.join(str(p) for p in d.get('location', []))}: {d.get('message')}"
                               if isinstance(d, dict) else str(d) for d in detail)
        super().__init__(f"HTTP {status}: {detail}")


def _plain(value):
    """A dict for JSON: pydantic models (RunConfig, Stimulus, ...) become their JSON form."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _query(options: dict) -> dict:
    """Query parameters: booleans as true/false, as the server reads them."""
    return {k: str(v).lower() if isinstance(v, bool) else v for k, v in options.items()}


class Client:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 30.0):
        parts = urllib.parse.urlsplit(url.rstrip("/"))
        if parts.scheme != "http" or not parts.hostname:
            raise ValueError(f"Give the app's address, such as {DEFAULT_URL}, not {url!r}.")
        self.url, self.timeout = f"{parts.scheme}://{parts.netloc}", timeout
        self.origin = f"http://{parts.hostname}:{parts.port or 80}"  # the server accepts commands from its own address
        # The app is local: never route its requests through a proxy from the environment.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method: str, path: str, body=None, query: dict | None = None, headers: dict | None = None):
        """(JSON body, response headers) of one API call; raises ClientError for an HTTP error status."""
        url = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = None if body is None else json.dumps(_plain(body), allow_nan=False).encode()
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Accept": "application/json", **({"Content-Type": "application/json"} if data is not None else {}),
            **({"Origin": self.origin} if method != "GET" else {}), **(headers or {})})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                text = response.read()
                return (json.loads(text) if text else None), dict(response.headers)
        except urllib.error.HTTPError as exc:
            text = exc.read()
            try:
                detail = json.loads(text).get("detail", text.decode(errors="replace"))
            except (ValueError, AttributeError):
                detail = text.decode(errors="replace") or exc.reason
            raise ClientError(exc.code, detail) from None

    def _get(self, path, **query):
        return self.request("GET", path, query=query or None)[0]

    def _post(self, path, body=None):
        return self.request("POST", path, {} if body is None else body)[0]

    # Reading
    def health(self) -> dict:
        return self._get("/api/health")

    def status(self) -> dict:
        """The live state: status, run_id, config, interventions, sample, metrics, events, connectome activity…"""
        return self._get("/api/status")

    def capabilities(self) -> dict:
        return self._get("/api/capabilities")

    def runs(self, offset: int = 0, limit: int = 100, include_empty: bool = True) -> dict:
        """One page of saved runs, newest first: {"runs": [...], "total": count of all saved runs}."""
        body, headers = self.request("GET", "/api/runs", query={"offset": offset, "limit": limit,
                                                                 "include_empty": str(include_empty).lower()})
        total = {k.lower(): v for k, v in headers.items()}.get("x-total-count")
        return {**body, "total": int(total) if total is not None else None}

    def saved_run(self, key: str) -> dict:
        """A saved run's summary and decimated trajectory, by its folder name (a `runs()` entry's key)."""
        return self._get(f"/api/runs/{urllib.parse.quote(key)}")

    # Commands
    def reset(self, config=None, **settings) -> dict:
        """Start a new run from `config` (a dict or RunConfig; fields left out take the server's defaults, which
        include the FlyGym engine) or, without it, from the current run's configuration, as the browser's Reset
        does. `settings` then change single values, with dotted names for nested ones:
        reset(seed=4, **{"connectome_parameters.dynamics": "spiking"})."""
        data = json.loads(json.dumps(_plain(config))) if config is not None else self.status()["config"]
        for key, value in settings.items():
            node = data
            *parents, last = key.split(".")
            for part in parents:
                if not isinstance(node.get(part), dict):
                    node[part] = {}
                node = node[part]
            node[last] = _plain(value)
        return self._post("/api/reset", data)

    def run(self) -> dict:
        return self._post("/api/run")

    def pause(self) -> dict:
        return self._post("/api/pause")

    def step(self, count: int = 1) -> dict:
        """Advance `count` control intervals (10 ms each) while paused; returns the last state."""
        state = None
        for _ in range(count):
            state = self._post("/api/step")
        return state

    def stimulus(self, x: float, y: float, intensity: float = 1.0) -> dict:
        """Move the target to (x, y) mm in the arena."""
        return self._post("/api/stimulus", {"x": x, "y": y, "intensity": intensity})

    def speed(self, speed: float) -> dict:
        return self._post("/api/speed", {"speed": speed})

    def interventions(self, interventions=None, replace: bool = False, **fields) -> dict:
        """Set interventions (zero_left, zero_right, silence, silence_dna02, silence_types, ...). The given fields
        are merged into the run's current interventions unless replace=True, which leaves the rest at defaults."""
        current = {} if replace else self.status()["interventions"]
        return self._post("/api/interventions", {**current, **(_plain(interventions) or {}), **fields})

    def connectome_parameters(self, parameters=None, replace: bool = False, **fields) -> dict:
        """Change the connectome model's parameters mid-run (gains, motor path, …), merged into the run's current
        ones unless replace=True. The circuit, dynamics and populations change only with reset()."""
        current = {} if replace else self.status()["config"]["connectome_parameters"]
        return self._post("/api/connectome/parameters", {**current, **(_plain(parameters) or {}), **fields})

    def export(self, share_safe: bool = False) -> dict:
        """Save the run under runs/ ({run_id, samples, path, download_url}); share_safe leaves out local paths,
        the host name and the platform string, for runs to publish."""
        return self._post("/api/export", {"share_safe": share_safe})

    # Connectivity explorer (whole brain from the prepared archive, or a circuit by name; see docs/USAGE.md)
    def explore_graphs(self) -> dict:
        """The graphs the explorer can query ("brain" and every circuit) and the running circuit."""
        return self._get("/api/explore/graphs")

    def partners(self, query: str, direction: str = "upstream", graph: str = "brain", **options) -> dict:
        """Upstream or downstream partners of cell types or FlyWire root IDs (comma-separated), by cell type
        (group="cell_type") or neuron; options: side, threshold, limit, other_transmitters."""
        return self._get("/api/explore/partners", query=query, direction=direction, graph=graph, **_query(options))

    def paths(self, source: str, target: str, mode: str = "strongest", level: str = "cell_type", graph: str = "brain",
              **options) -> dict:
        """Strongest or shortest paths between cell types or neurons; options: threshold, limit, max_hops,
        source_side, target_side, other_transmitters."""
        return self._get("/api/explore/paths", source=source, target=target, mode=mode, level=level, graph=graph,
                         **_query(options))

    def influence(self, query: str, direction: str = "from", graph: str = "brain", **options) -> dict:
        """Steady-state influence (BANC-style linear model) of the query on every neuron (direction="from"), or of
        every neuron on the query ("onto"); options: group, side, threshold, limit, signed, other_transmitters."""
        return self._get("/api/explore/influence", query=query, direction=direction, graph=graph, **_query(options))

    def neuroglancer(self, groups=None, circuit: str | None = None, graph: str = "brain", **options) -> dict:
        """A Neuroglancer link ({url, state, neurons, truncated, ...}) for groups of neurons, each {label, ids} or
        {label, cell_type, side}, and/or a whole circuit; options: title, limit."""
        body = {"graph": graph, "groups": list(groups or []), **({"circuit": circuit} if circuit else {}), **options}
        return self._post("/api/explore/neuroglancer", body)

    # Circuits, background jobs and the scorecard
    def circuits(self) -> dict:
        """Committed and local circuits ({"circuits": [...], "active": name})."""
        return self._get("/api/connectome/circuits")

    def build_circuit(self, name: str, seeds, **options) -> dict:
        """Start building a circuit in a background job (seed cell types; options: hops, threshold, cap, whole_brain,
        balance_sides). A second build is refused while one runs. Follow it with build_status() or jobs()."""
        return self._post("/api/connectome/build", {"name": name, "seeds": list(seeds), **options})

    def build_status(self) -> dict:
        return self._get("/api/connectome/build")

    def jobs(self) -> dict:
        """Background jobs (circuit builds, replay checks, scorecards): {"jobs": [...]}, newest first."""
        return self._get("/api/jobs")

    def cancel_job(self, job_id: str) -> dict:
        return self._post(f"/api/jobs/{urllib.parse.quote(job_id)}/cancel")

    def scorecards(self) -> dict:
        """The scorecard's tests and the latest card for each model scored."""
        return self._get("/api/scorecards")

    def run_scorecard(self, model: str = "connectome", circuit: str | None = None, dynamics: str = "rate",
                      engine: str = "toy") -> dict:
        """Score a model in a background job ({"job": ...}); the card then appears in scorecards()."""
        return self._post("/api/scorecards/run", {"model": model, "dynamics": dynamics, "engine": engine,
                                                  **({"circuit": circuit} if circuit else {})})

    # Comparisons (matched-seed trials run by the app, saved to the run library)
    def start_comparison(self, config, conditions=("control",), seeds=(42, 43), custom_conditions=(),
                         cell_type: str | None = None, max_speed: bool = False) -> dict:
        """Run each condition for each seed with `config` (which needs a protocol), saving every trial."""
        return self._post("/api/batch/start", {"config": _plain(config), "conditions": list(conditions),
                                               "seeds": list(seeds), "custom_conditions": [_plain(c) for c in custom_conditions],
                                               "max_speed": max_speed, **({"cell_type": cell_type} if cell_type else {})})

    def cancel_comparison(self) -> dict:
        return self._post("/api/batch/cancel")

    def comparison_summary(self, batch_id: str) -> dict:
        """Per-condition statistics and matched-seed differences of a comparison's saved trials."""
        return self._get(f"/api/batches/{urllib.parse.quote(batch_id)}/summary")

    def comparison_methods(self, batch_id: str) -> str:
        return self._get(f"/api/batches/{urllib.parse.quote(batch_id)}/methods")["markdown"]

    # Saved runs: provenance, methods, NWB, replay checks and plugin metrics
    def manifest(self, key: str) -> dict:
        """A saved run's RO-Crate provenance manifest."""
        return self._get(f"/api/runs/{urllib.parse.quote(key)}/manifest")

    def methods(self, key: str) -> str:
        """A methods paragraph drafted from a saved run's manifest (Markdown); review it before use."""
        return self._get(f"/api/runs/{urllib.parse.quote(key)}/methods")["markdown"]

    def replay_check(self, key: str) -> dict:
        """Replay a saved run in a background job and compare it with the recording ({"job": ...})."""
        return self._post(f"/api/runs/{urllib.parse.quote(key)}/replay")

    def run_metrics(self, key: str, metrics=None) -> dict:
        """Installed plugins' metrics computed on a saved run (all of them, or the named plugin:metric ones)."""
        return self.request("GET", f"/api/runs/{urllib.parse.quote(key)}/metrics",
                            query=[("metric", m) for m in metrics or []] or None)[0]

    def plugins(self) -> dict:
        """Installed plugins, their status and contributions."""
        return self._get("/api/plugins")

    def download(self, path: str, destination) -> dict:
        """Save a binary API response (an NWB file, a run's ZIP) to `destination`: {path, bytes}."""
        from pathlib import Path
        request = urllib.request.Request(self.url + path, headers={"Accept": "*/*"})
        destination = Path(destination)
        try:
            with self._opener.open(request, timeout=max(self.timeout, 120)) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_name(f".{destination.name}.part")
                with partial.open("wb") as output:
                    while chunk := response.read(1 << 20):
                        output.write(chunk)
                partial.replace(destination)
        except urllib.error.HTTPError as exc:
            text = exc.read()
            try:
                detail = json.loads(text).get("detail", text.decode(errors="replace"))
            except (ValueError, AttributeError):
                detail = text.decode(errors="replace") or exc.reason
            raise ClientError(exc.code, detail) from None
        return {"path": str(destination), "bytes": destination.stat().st_size}

    def nwb(self, key: str, destination=None) -> dict:
        """Write a saved run as NWB on the server (needs pynwb there) and save the file (default ./KEY.nwb)."""
        return self.download(f"/api/runs/{urllib.parse.quote(key)}/nwb", destination or f"{key}.nwb")

    # Waiting and watching
    def wait_until(self, predicate, timeout: float = 60.0, interval: float = 0.1) -> dict:
        """Poll the state until predicate(state) is true and return that state. Raises TimeoutError, or
        ClientError when the run enters the error state first."""
        deadline = time.monotonic() + timeout
        while True:
            state = self.status()
            if predicate(state):
                return state
            if state.get("status") == "error":
                raise ClientError(409, f"The run failed while waiting: {state.get('error')}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"The condition did not hold within {timeout:g} s (simulated time "
                                   f"{(state.get('sample') or {}).get('t')} s, status {state.get('status')}).")
            time.sleep(interval)

    def stream(self, count: int | None = None, timeout: float = 30.0):
        """Yield live telemetry states from the app's WebSocket (about 10 a second while running, only when the
        state changes): `count` of them, or until the caller stops. Needs the `websockets` package."""
        try:
            from websockets.sync.client import connect
        except ImportError:
            raise RuntimeError("stream() needs the websockets package (pip install websockets); "
                               "wait_until() works without it.") from None
        url = "ws" + self.url[len("http"):] + "/api/ws"
        options = {"origin": self.origin, "max_size": 16 * 2 ** 20, "open_timeout": timeout}
        try:
            connection = connect(url, proxy=None, **options)  # a local app: never through a proxy
        except TypeError:  # websockets before 15 has no proxy option and never used one
            connection = connect(url, **options)
        with connection:
            received = 0
            while count is None or received < count:
                yield json.loads(connection.recv(timeout=timeout))
                received += 1
