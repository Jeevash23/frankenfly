"""Plugins (digitalfly.plugins): discovery through entry points, the example plugin's contributions, and the rule
that runs made without plugins are unchanged while runs made with one record it."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly import plugins, provenance, scorecard, toolkit
from digitalfly.api.models import RunConfig
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples/plugins/digitalfly-example-plugin"


def install(site: Path, name: str, version: str, entry_points: str):
    """An installed distribution as importlib.metadata sees one: a dist-info folder on sys.path."""
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    (info / "entry_points.txt").write_text(f"[{plugins.GROUP}]\n{entry_points}\n")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A folder of installed distributions on sys.path, with the example plugin's source importable. The plugin cache
    is restored afterwards, so other tests see the real installation."""
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(EXAMPLE / "src"))
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.setattr(plugins, "_cache", None)
    monkeypatch.delenv("DIGITALFLY_PLUGINS", raising=False)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(site), str(EXAMPLE / "src"), str(ROOT / "backend/src")]))
    return site


@pytest.fixture
def example(site):
    install(site, "digitalfly-example-plugin", "0.1.0", "example = digitalfly_example_plugin:plugin")
    plugins.discover(refresh=True)
    return site


def export(tmp_path, config, steps=60):
    exp = Experiment(config, render=False)
    try:
        for _ in range(steps):
            exp.advance()
        return exp, Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()


def test_the_example_plugin_is_discovered_with_its_contributions(example):
    listing = plugins.describe()
    assert listing["api_version"] == plugins.API_VERSION == 1 and listing["enabled"]
    (item,) = [p for p in listing["plugins"] if p["name"] == "example"]
    assert item["status"] == "ok" and item["error"] is None
    assert item["distribution"] == "digitalfly-example-plugin" and item["version"] == "0.1.0"
    names = {kind: [c["name"] for c in entries] for kind, entries in item["contributions"].items()}
    assert names == {"sensors": ["crossed"], "stimuli": ["zigzag"], "scorecard_tests": ["target_side"],
                     "metrics": ["straightness"], "commands": ["straightness"]}
    assert item["contributions"]["stimuli"][0]["parameters"]["jumps"] == 4


def test_broken_incompatible_and_duplicate_plugins_are_listed_not_fatal(site, tmp_path):
    (tmp_path / "old_plugin.py").write_text("from digitalfly.plugins import Plugin\nplugin = Plugin(api_version=99)\n")
    sys.path.insert(0, str(tmp_path))
    try:
        install(site, "broken", "1.0", "broken = no_such_module:plugin")
        install(site, "old", "2.0", "old = old_plugin:plugin")
        install(site, "twin-a", "1.0", "twin = old_plugin:plugin")
        install(site, "twin-b", "1.0", "twin = old_plugin:plugin")
        found = {p.name + p.value: p for p in plugins.discover(refresh=True)}
        assert found["brokenno_such_module:plugin"].status == "error"
        assert "ModuleNotFoundError" in found["brokenno_such_module:plugin"].error
        assert found["oldold_plugin:plugin"].status == "incompatible"
        assert "API 99" in found["oldold_plugin:plugin"].error
        assert [p.status for p in plugins.discover() if p.name == "twin"] == ["error", "error"]
        with pytest.raises(plugins.PluginError, match="cannot be used"):
            plugins.sensor("old:anything")
        with pytest.raises(plugins.PluginError, match="No plugin named nope"):
            plugins.sensor("nope:anything")
    finally:
        sys.path.remove(str(tmp_path))


def test_plugins_can_be_turned_off(example, monkeypatch):
    monkeypatch.setenv("DIGITALFLY_PLUGINS", "0")
    assert plugins.discover(refresh=True) == [] and not plugins.describe()["enabled"]
    with pytest.raises(plugins.PluginError, match="turned off"):
        plugins.sensor("example:crossed")


def test_defaults_and_runs_without_plugins_are_unchanged(tmp_path, example):
    """An installed plugin changes nothing that does not name it: the default configuration (and so every config hash),
    the export's metadata and manifest."""
    config = RunConfig(engine="toy", seed=4)
    assert "plugins" not in config.model_dump() and "plugins" not in json.loads(config.model_dump_json())
    assert RunConfig.model_validate(config.model_dump()) == config
    assert toolkit.config_hash(config) == toolkit.config_hash(RunConfig.model_validate({"engine": "toy", "seed": 4}))
    _, run = export(tmp_path, config)
    meta = json.loads((run / "metadata.json").read_text())
    assert "plugins" not in meta and "plugins" not in meta["initial_config"]
    nodes = {n["@id"] for n in json.loads((run / provenance.MANIFEST_FILE).read_text())["@graph"]}
    assert not any(n.startswith("#plugin-") for n in nodes)
    assert "plugin" not in (run / provenance.METHODS_FILE).read_text()


def test_a_plugin_sensor_drives_the_run_and_is_recorded(tmp_path, example):
    plain_exp, _ = export(tmp_path / "plain", RunConfig(engine="toy", seed=4), steps=1)
    crossed = RunConfig(engine="toy", seed=4, plugins={"sensor": "example:crossed"})
    exp, run = export(tmp_path / "crossed", crossed, steps=1)
    first = exp.records[0].sensors
    plain = plain_exp.records[0].sensors
    assert first.left == pytest.approx(plain.right) and first.right == pytest.approx(plain.left)
    assert first.left != pytest.approx(first.right)  # the target is to one side
    meta = json.loads((run / "metadata.json").read_text())
    assert meta["initial_config"]["plugins"]["sensor"] == "example:crossed"
    assert meta["plugins"] == [{"plugin": "example", "distribution": "digitalfly-example-plugin", "version": "0.1.0",
                                "api_version": 1, "kind": "sensors", "contribution": "crossed"}]
    nodes = {n["@id"]: n for n in json.loads((run / provenance.MANIFEST_FILE).read_text())["@graph"]}
    entity = nodes["#plugin-example-sensors-crossed"]
    assert entity["version"] == "0.1.0" and {"@id": entity["@id"]} in nodes["#run"]["object"]
    assert "example:crossed (sensors, digitalfly-example-plugin 0.1.0)" in (run / provenance.METHODS_FILE).read_text()
    # Input interventions still apply after the plugin.
    zeroed = Experiment(RunConfig.model_validate({**crossed.model_dump(), "initial_interventions": {"zero_left": True}}),
                        render=False)
    try:
        assert zeroed.sample.sensors.left == 0 and zeroed.sample.sensors.raw_left == pytest.approx(first.raw_left)
    finally:
        zeroed.close()


def test_plugin_choices_are_validated(example):
    with pytest.raises(ValueError, match="no sensor missing"):
        RunConfig(engine="toy", plugins={"sensor": "example:missing"})
    with pytest.raises(ValueError, match="plugin:name|pattern"):
        RunConfig(engine="toy", plugins={"sensor": "crossed"})
    with pytest.raises(ValueError, match="has none"):
        RunConfig(engine="toy", plugins={"stimulus": "example:zigzag"})
    with pytest.raises(ValueError, match="geometric"):
        RunConfig(engine="flygym", sensor_model="vision", plugins={"sensor": "example:crossed"})


def test_a_stimulus_program_writes_a_protocol_that_replays_without_it(example, monkeypatch):
    protocol = plugins.stimulus_protocol("example:zigzag", jumps=3, every_steps=20)
    assert protocol["duration_steps"] == 60 and [e["step"] for e in protocol["events"]] == [0, 20, 40]
    config = RunConfig(engine="toy", protocol=protocol,
                       plugins={"stimulus": "example:zigzag", "stimulus_parameters": {"jumps": 3, "every_steps": 20}})
    assert plugins.used_by(config)[0]["kind"] == "stimuli"
    with pytest.raises(plugins.PluginError, match="no parameter speed"):
        plugins.stimulus_protocol("example:zigzag", speed=2)
    # Without the plugin installed the configuration still validates: the protocol is plain data.
    monkeypatch.setenv("DIGITALFLY_PLUGINS", "0")
    plugins.discover(refresh=True)
    again = RunConfig.model_validate(config.model_dump())
    assert again.protocol == config.protocol
    assert plugins.used_by(again)[0]["installed"] is False


def test_metrics_and_the_api_listing(tmp_path, example, monkeypatch):
    _, run = export(tmp_path / "runs", RunConfig(engine="toy", seed=2), steps=80)
    result = plugins.run_metrics(run)
    (metric,) = result["metrics"]
    assert metric["metric"] == "example:straightness" and metric["version"] == "0.1.0"
    assert 0 < metric["value"]["straightness"] <= 1 and metric["value"]["path_mm"] > 0
    with pytest.raises(plugins.PluginError, match="no metric"):
        plugins.run_metrics(run, ["example:missing"])
    from digitalfly.main import create_app
    for module in ("digitalfly.simulation.experiment", "digitalfly.main", "digitalfly.data.research"):
        monkeypatch.setattr(f"{module}.ROOT", tmp_path)
    with TestClient(create_app(RunConfig(engine="toy"), render=False), base_url="http://127.0.0.1:8000") as client:
        listing = client.get("/api/plugins").json()
        assert [p["name"] for p in listing["plugins"]] == ["example"]
        response = client.get(f"/api/runs/{run.name}/metrics", params={"metric": "example:straightness"})
        assert response.status_code == 200 and response.json()["metrics"][0]["value"] == metric["value"]
        assert client.get(f"/api/runs/{run.name}/metrics", params={"metric": "x:y"}).status_code == 422
        assert client.get("/api/runs/nope/metrics").status_code == 404


def test_plugin_scorecard_tests_run_only_when_asked_for(example):
    card = scorecard.run(scorecard.Target("engineered"), engine="toy", seeds=[1], duration_s=1.5, tests=[],
                         plugins=["example:target_side"])
    (test,) = card["tests"]
    assert test["id"] == "example:target_side" and test["status"] in {"pass", "partial", "fail"}
    assert test["plugin"]["version"] == "0.1.0" and card["plugins"] == [test["plugin"]]
    assert {t["condition"] for t in card["trials"]} == {"example:target_side: target +45°",
                                                        "example:target_side: target -45°"}
    assert [t["id"] for t in scorecard.definitions()] == scorecard.TEST_IDS  # the built-in list is unchanged
    with pytest.raises(plugins.PluginError):
        scorecard.run(scorecard.Target("engineered"), engine="toy", seeds=[1], tests=[], plugins=["example:nope"])


def test_toolkit_lists_plugins_and_runs_their_commands(tmp_path, example):
    _, run = export(tmp_path, RunConfig(engine="toy", seed=2), steps=40)
    python = sys.executable
    done = subprocess.run([python, "scripts/toolkit.py", "plugins", "--json"], cwd=ROOT, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    assert [p["name"] for p in json.loads(done.stdout)["plugins"]] == ["example"]
    done = subprocess.run([python, "scripts/toolkit.py", "example:straightness", str(run)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "straightness" in done.stdout, done.stderr
    done = subprocess.run([python, "scripts/toolkit.py", "metrics", str(run), "--out", str(tmp_path / "m")], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "example:straightness" in done.stdout, done.stderr
    assert json.loads((tmp_path / "m.json").read_text())["runs"][0]["metrics"][0]["plugin"] == "example"
