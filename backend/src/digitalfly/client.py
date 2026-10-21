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
