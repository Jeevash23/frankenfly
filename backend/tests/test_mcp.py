"""The MCP server (digitalfly.mcp): its tools against the real app through FastAPI's TestClient (no server needed),
the audit log, the guards on destructive tools, and the MCP protocol itself when the optional SDK is installed."""
import asyncio
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly import mcp as server
from digitalfly.api.models import RunConfig
from digitalfly.client import Client, ClientError

TOY = {"engine": "toy", "neural_model": "connectome", "seed": 3, "speed": 2}
READ_ONLY = {"status", "list_circuits", "list_jobs", "get_scorecards", "list_runs", "get_run", "comparison_summary",
             "list_presets", "explore_partners", "explore_route", "explore_influence", "neuroglancer_link",
             "list_plugins", "run_metrics"}


class AppClient(Client):
    """digitalfly.client.Client with its HTTP requests sent to a TestClient instead of the network."""

    def __init__(self, test_client: TestClient):
        super().__init__("http://127.0.0.1:8000")
        self.test_client = test_client

    def request(self, method, path, body=None, query=None, headers=None):
        response = self.test_client.request(method, path, params=query, json=body if body is not None else None,
                                            headers={**({"Origin": self.origin} if method != "GET" else {}),
                                                     **(headers or {})})
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text
            raise ClientError(response.status_code, detail)
        return (response.json() if response.content else None), dict(response.headers)

    def download(self, path, destination):
        response = self.test_client.get(path)
        if response.status_code >= 400:
            raise ClientError(response.status_code, response.json().get("detail"))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(response.content)
        return {"path": str(destination), "bytes": len(response.content)}


@pytest.fixture
def toolbox(tmp_path, monkeypatch):
    from digitalfly.main import create_app
    for module in ("digitalfly.simulation.experiment", "digitalfly.main", "digitalfly.data.research"):
        monkeypatch.setattr(f"{module}.ROOT", tmp_path)  # exports and the run library stay in the test folder
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield server.Toolbox(AppClient(client), server.AuditLog(tmp_path / "audit" / "mcp.jsonl"),
                             downloads=tmp_path / "downloads")


def test_tools_are_annotated_and_nothing_destructive_is_exposed(toolbox):
    specs = {s.name: s for s in toolbox.specs()}
    assert {n for n, s in specs.items() if s.read_only} == READ_ONLY
    assert all(s.description.startswith("[read-only]") for n, s in specs.items() if n in READ_ONLY)
    assert not any(word in name for name in specs for word in ("delete", "remove", "overwrite", "save_preset"))
    # Tools that replace the live run are marked destructive and need an explicit discard_current.
    import inspect
    for name in ("reset_run", "start_comparison"):
        assert specs[name].destructive and inspect.signature(specs[name].function).parameters["discard_current"].default is False
    assert {n for n, s in specs.items() if s.destructive} == {"reset_run", "start_comparison"}


def test_an_agent_drives_a_short_run_and_reads_it_back(toolbox, tmp_path):
    status = toolbox.call("status")
    assert status["app"]["worker_alive"] and status["status"] == "paused"
    assert "history" not in status and "legs" not in (status["sample"]["pose"] or {})
    state = toolbox.call("reset_run", {"config": TOY, "discard_current": True})
    assert state["status"] == "paused" and state["t"] == 0
    assert toolbox.call("step_run", {"count": 3})["step"] == 3
    toolbox.call("set_stimulus", {"x": 0, "y": 12})
    toolbox.call("set_interventions", {"interventions": {"silence_dna02": "left"}})
    assert toolbox.call("status")["interventions"]["silence_dna02"] == "left"
    toolbox.call("set_connectome_parameters", {"parameters": {"output_gain": 2}})
    ran = toolbox.call("run_for", {"seconds": .2, "timeout_s": 60})  # short: stepped
    assert ran["status"] == "paused" and ran["t"] == pytest.approx(.23)
    ran = toolbox.call("run_for", {"seconds": 1, "timeout_s": 60})  # run, paused near the end, then stepped
    assert ran["status"] == "paused" and ran["t"] == pytest.approx(1.23)
    saved = toolbox.call("export_run", {"share_safe": True})
    assert saved["samples"] > 30 and saved["key"] == Path(saved["path"]).name
    listing = toolbox.call("list_runs", {"limit": 5})
    assert listing["total"] == 1 and listing["runs"][0]["key"] == saved["key"]
    detail = toolbox.call("get_run", {"key": saved["key"], "manifest": True})
    assert "trajectory" not in detail and detail["manifest"]["@context"][0].startswith("https://w3id.org/ro/crate")
    assert detail["methods"].startswith("# Methods draft")
    assert toolbox.call("get_run", {"key": saved["key"], "trajectory": True, "methods": False})["trajectory"]
    assert toolbox.call("list_plugins")["api_version"] == 1
    assert toolbox.call("list_circuits")["active"] == "fafb783-dna02"
    assert toolbox.call("explore_partners", {"query": "DNa02", "graph": "fafb783-dna02", "limit": 5})["rows"]
    # Replacing a recorded run needs discard_current; the refusal says how to keep it.
    with pytest.raises(server.ToolFailure, match="export_run first"):
        toolbox.call("reset_run", {})
    assert toolbox.call("reset_run", {"settings": {"seed": 5}, "discard_current": True})["t"] == 0
    # A refused command reaches the agent with the server's reason.
    with pytest.raises(server.ToolFailure, match="refused.*422"):
        toolbox.call("set_stimulus", {"x": 99, "y": 0})


def test_every_call_is_audited_before_and_after(toolbox):
    toolbox.call("status")
    with pytest.raises(server.ToolFailure):
        toolbox.call("get_run", {"key": "missing-run"})
    entries = toolbox.audit.entries()
    assert [(e["event"], e["tool"]) for e in entries] == [("call", "status"), ("result", "status"),
                                                           ("call", "get_run"), ("result", "get_run")]
    assert entries[0]["read_only"] and entries[2]["arguments"] == {"key": "missing-run"}
    assert entries[1]["outcome"] == "ok" and entries[1]["summary"]["status"] == "paused"
    assert entries[3]["outcome"] == "error" and "404" in entries[3]["error"]
    assert len({e["session"] for e in entries}) == 1 and entries[0]["call"] == entries[1]["call"]
    assert (toolbox.audit.path.stat().st_mode & 0o777) == 0o600
    before = toolbox.audit.path.read_text()
    toolbox.call("list_jobs")
    assert toolbox.audit.path.read_text().startswith(before)  # only ever appended


def test_a_call_is_refused_when_it_cannot_be_audited(toolbox, tmp_path):
    (tmp_path / "blocked").write_text("a file where the log's folder should be")
    toolbox.audit = server.AuditLog(tmp_path / "blocked" / "mcp.jsonl")
    ran = []
    toolbox.client.run = lambda: ran.append(True)
    with pytest.raises(server.AuditError, match="refused"):
        toolbox.call("start_run")
    assert not ran


def test_comparisons_and_toolkit_commands_are_bounded(toolbox, monkeypatch):
    protocol = {"name": "short", "duration_steps": 20, "events": []}
    state = toolbox.call("start_comparison", {"config": {**TOY, "protocol": protocol}, "conditions": ["control"],
                                              "seeds": [1]})
    assert state["batch"]["status"] in {"running", "complete"}
    with pytest.raises(server.ToolFailure, match="--out is chosen by the server"):
        toolbox.call("run_toolkit", {"command": "trials", "arguments": ["--out", "/tmp/x"]})
    with pytest.raises(server.ToolFailure, match="not 'jump'"):
        toolbox.call("run_toolkit", {"command": "jump"})
    with pytest.raises(server.ToolFailure, match="1 to 4 workers"):
        toolbox.call("run_toolkit", {"command": "ablation", "arguments": ["--workers=16"]})
    seen = []
    monkeypatch.setattr(toolbox, "_run_process", lambda line, timeout, stem: seen.append((line, stem)) or {})
    toolbox.call("run_trials", {"settings": {"neural_model": "connectome", "connectome_parameters.output_gain": 2},
                                "vary": {"connectome_parameters.dynamics": ["rate", "spiking"]}, "bearings": "-45,45"})
    line, stem = seen[0]
    assert line[2] == "trials" and "--bearings=-45,45" in line and "--set=neural_model=connectome" in line
    assert "--set=connectome_parameters.output_gain=2" in line
    assert "--vary=connectome_parameters.dynamics=rate,spiking" in line
    assert line[-2] == "--out" and Path(line[-1]) == stem and stem.parent.name == "mcp"
    toolbox.call("run_toolkit", {"command": "scorecard", "arguments": ["--model", "engineered"]})
    assert seen[1][0][-1] == "--no-publish"  # toolkit scorecards never replace the app's latest card


def test_toolkit_trials_run_in_a_separate_process(toolbox, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "ROOT", tmp_path)  # results go to the test folder
    result = toolbox.call("run_trials", {"seeds": "1", "bearings": "45", "distances": "12", "duration_s": .5,
                                         "timeout_s": 300})
    assert result["returncode"] == 0, result["output"]
    assert result["report"]["command"] == "trials" and len(result["report"]["trials"]) == 1
    assert any(p.endswith(".json") for p in result["saved"])


def test_the_mcp_protocol_lists_and_calls_the_tools(toolbox):
    pytest.importorskip("mcp", reason="the optional MCP SDK (backend/requirements-mcp.lock) is not installed")
    from mcp import Client as MCPClient
    mcp_server = server.build_server(toolbox)

    async def session():
        async with MCPClient(mcp_server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            status = await client.call_tool("status", {"events": 2})
            refused = await client.call_tool("get_run", {"key": "missing-run"})
            invalid = await client.call_tool("step_run", {"count": 0})
            return tools, status, refused, invalid
    tools, status, refused, invalid = asyncio.run(session())
    assert set(tools) == {s.name for s in toolbox.specs()}
    assert all(tools[n].annotations.read_only_hint for n in READ_ONLY)
    assert tools["reset_run"].annotations.destructive_hint and not tools["reset_run"].annotations.read_only_hint
    assert not tools["start_run"].annotations.read_only_hint and not tools["start_run"].annotations.destructive_hint
    assert "discard_current" in tools["reset_run"].input_schema["properties"]
    assert not status.is_error and json.loads(status.content[0].text)["status"] == "paused"
    assert refused.is_error and "404" in refused.content[0].text
    assert invalid.is_error  # validated against the tool's schema before anything runs
    assert [e["tool"] for e in toolbox.audit.entries() if e["event"] == "call"] == ["status", "get_run"]
