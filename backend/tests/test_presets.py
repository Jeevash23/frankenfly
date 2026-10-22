"""Named configurations: the shipped presets, local ones saved through the API, and their validation."""
import json
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import RunConfig
from digitalfly.data import presets
from digitalfly.main import create_app

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ["default", "first-experiment", "flyvis-eyes", "spiking-dna02", "steering-circuit"]
NO_FLYVIS = (False, "FlyVis is not installed.")


@pytest.fixture
def configs(tmp_path, monkeypatch):
    folder = tmp_path / "configs"
    shutil.copytree(ROOT / "configs", folder, ignore=shutil.ignore_patterns("local"))
    monkeypatch.setattr(presets, "CONFIG_DIR", folder)
    monkeypatch.setattr("digitalfly.vision.flyvis_eyes.available", lambda *args: NO_FLYVIS)
    return folder


@pytest.fixture
def client(configs, tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_every_shipped_preset_is_valid(configs, monkeypatch):
    listed = {entry["name"]: entry for entry in presets.list_presets()}
    assert sorted(listed) == SHIPPED and [e["name"] for e in presets.list_presets()][0] == "default"
    assert all(entry["source"] == "shipped" and entry["description"] for entry in listed.values())
    for name in SHIPPED:
        if name == "flyvis-eyes":
            continue
        assert listed[name]["available"] and "error" not in listed[name], listed[name]
        config = RunConfig.model_validate(presets.load(name)["config"])
        assert config == presets.load_config(name)
    assert presets.load("steering-circuit")["config"]["connectome_parameters"]["circuit"] == "fafb783-steering"
    assert presets.load("spiking-dna02")["config"]["connectome_parameters"]["dynamics"] == "spiking"
    assert presets.load("first-experiment")["config"]["protocol"]["events"][0]["stimulus"]["y"] == -8
    assert presets.load("default")["config"] == RunConfig.model_validate_json((ROOT / "configs/default.json").read_text()).model_dump()
    # FlyVis eyes are listed either way, and the preset is valid wherever FlyVis is installed.
    entry = listed["flyvis-eyes"]
    assert entry["available"] is False and entry["reason"] == NO_FLYVIS[1] and "error" not in entry
    with pytest.raises(presets.PresetUnavailable, match="not installed"):
        presets.load("flyvis-eyes")
    monkeypatch.setattr("digitalfly.vision.flyvis_eyes.available", lambda *args: (True, ""))
    assert presets.load("flyvis-eyes")["config"]["sensor_model"] == "flyvis"


def test_presets_are_listed_read_saved_and_deleted_through_the_api(client, configs):
    listed = client.get("/api/configs").json()["configs"]
    assert [entry["name"] for entry in listed] == ["default"] + SHIPPED[1:]
    flyvis = next(entry for entry in listed if entry["name"] == "flyvis-eyes")
    assert flyvis["available"] is False and flyvis["reason"] == NO_FLYVIS[1]
    assert client.get("/api/configs/flyvis-eyes").status_code == 409
    steering = client.get("/api/configs/steering-circuit").json()
    assert steering["source"] == "shipped" and steering["config"]["neural_model"] == "connectome"
    assert client.get("/api/configs/missing").status_code == 404 and client.get("/api/configs/Bad..name").status_code == 404
    config = {**RunConfig(engine="toy", seed=7).model_dump(), "speed": 1.5}
    saved = client.post("/api/configs", json={"name": "my_toy-1", "description": "Fast toy", "config": config})
    assert saved.status_code == 201 and saved.json() == {"name": "my_toy-1", "source": "local", "description": "Fast toy",
                                                         "config": config}
    stored = json.loads((configs / "local/my_toy-1.json").read_text())
    assert stored == {"name": "my_toy-1", "description": "Fast toy", "config": config}
    assert not list((configs / "local").glob(".*"))  # written through a hidden partial file, renamed into place
    assert client.get("/api/configs/my_toy-1").json() == saved.json()
    entry = client.get("/api/configs").json()["configs"][-1]
    assert entry == {"name": "my_toy-1", "source": "local", "description": "Fast toy", "available": True}
    replaced = client.post("/api/configs", json={"name": "my_toy-1", "config": {**config, "seed": 8}}).json()
    assert replaced["config"]["seed"] == 8 and replaced["description"].startswith("toy body · engineered")
    # Shipped presets cannot be replaced or deleted; names, descriptions and configurations are checked.
    assert client.post("/api/configs", json={"name": "default", "config": config}).status_code == 409
    for bad in [{"name": "Upper", "config": config}, {"name": "-dash", "config": config}, {"name": "a" * 49, "config": config},
                {"name": "../x", "config": config}, {"name": "ok", "description": "x" * 201, "config": config},
                {"name": "ok", "config": {**config, "engine": "warp"}}, {"name": "ok", "config": config, "extra": 1},
                {"name": "ok", "config": {**config, "unknown": 1}}, {"name": "ok"}]:
        assert client.post("/api/configs", json=bad).status_code == 422, bad
    missing_circuit = {**config, "neural_model": "connectome", "connectome_parameters": {"circuit": "not-built"}}
    refused = client.post("/api/configs", json={"name": "ok", "config": missing_circuit})
    assert refused.status_code == 422 and "not-built" in refused.json()["detail"]  # checked off the event loop
    assert not (configs / "local/ok.json").exists()
    # Bodies up to the 1 MB file limit are accepted (other commands stop at 16 KB).
    body = json.dumps({"name": "padded", "config": config}) + " " * 30000
    headers = {"content-type": "application/json"}
    assert client.post("/api/configs", content=body, headers=headers).status_code == 201
    assert client.post("/api/configs", content=body + " " * presets.SIZE_LIMIT, headers=headers).status_code == 413
    assert client.delete("/api/configs/padded").json() == {"deleted": "padded"}
    assert client.delete("/api/configs/padded").status_code == 404
    assert client.delete("/api/configs/default").status_code == 409 and (configs / "default.json").is_file()


def test_damaged_local_presets_are_listed_with_an_error(client, configs):
    local = configs / "local"
    local.mkdir()
    (local / "broken.json").write_text("{not json")
    (local / "wrong.json").write_text(json.dumps({"description": "Old", "config": {"engine": "warp"}}))
    (local / "huge.json").write_text(json.dumps({"description": "x", "config": {}}) + " " * presets.SIZE_LIMIT)
    (local / "gone-circuit.json").write_text(json.dumps({"neural_model": "connectome", "connectome_parameters": {"circuit": "gone"}}))
    (local / "good.json").write_text(json.dumps({"engine": "toy"}))
    (local / "Not-A-Name.json").write_text("{}")
    (local / "default.json").write_text(json.dumps({"engine": "toy"}))  # never shadows the shipped preset
    listed = {entry["name"]: entry for entry in client.get("/api/configs").json()["configs"] if entry["source"] == "local"}
    assert sorted(listed) == ["broken", "gone-circuit", "good", "huge", "wrong"]
    assert "not valid JSON" in listed["broken"]["error"] and not listed["broken"]["available"]
    assert listed["wrong"]["description"] == "Old" and "engine" in listed["wrong"]["error"]
    assert "1 MB" in listed["huge"]["error"]
    assert listed["gone-circuit"]["available"] is False and "no circuit named gone" in listed["gone-circuit"]["reason"]
    assert listed["good"] == {"name": "good", "source": "local", "description": "toy body · engineered six-unit model · geometric sensing",
                              "available": True}
    assert client.get("/api/configs/broken").status_code == 422 and client.get("/api/configs/gone-circuit").status_code == 409
    assert client.get("/api/configs/default").json()["source"] == "shipped"


def test_launch_config_takes_a_preset_name_or_a_file(configs, tmp_path):
    assert presets.load_config("steering-circuit").connectome_parameters.circuit == "fafb783-steering"
    bare, wrapped = tmp_path / "bare.json", tmp_path / "wrapped.json"
    bare.write_text(json.dumps({"engine": "toy", "seed": 3}))
    wrapped.write_text(json.dumps({"description": "mine", "config": {"engine": "toy", "seed": 4}}))
    assert presets.load_config(str(bare)).seed == 3 and presets.load_config(str(wrapped)).seed == 4
    with pytest.raises(FileNotFoundError, match="Presets: default, first-experiment"):
        presets.load_config("no-such-preset")
    bare.write_text(json.dumps({"engine": "toy", "sensor_model": "vision"}))
    with pytest.raises(ValueError, match="OpenGL"):
        presets.load_config(str(bare))
