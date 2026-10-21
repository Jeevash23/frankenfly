"""The saved-run and connectivity libraries: paging, deletion and their boundaries; the API schema page."""
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from digitalfly.api.models import RunConfig
from digitalfly.data.research import delete_run, list_runs
from digitalfly.main import create_app
from digitalfly.simulation.engines import ROOT

KEYS = [f"202601{day:02d}T120000-{day:08x}-abcdef" for day in range(1, 8)]


def fake_run(runs: Path, key: str, samples: int, schema: int = 4):
    directory = runs / key
    directory.mkdir(parents=True)
    metadata = {"schema_version": schema, "run_id": key[:24], "created_utc": "2026-01-01T12:00:00+00:00",
                "initial_config": RunConfig(engine="toy").model_dump(), "recorded_samples": samples,
                "metrics": {}, "trial": None, "error": None, "provenance": {"body_engine": "toy"}}
    if schema >= 4:
        metadata.update(lockfiles={}, share_safe=False)
    (directory / "metadata.json").write_text(json.dumps(metadata))
    (runs / f"{key}.zip").write_bytes(b"PK")
    return directory


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_run_library_pages_newest_first_with_a_total(client, tmp_path):
    runs = tmp_path / "runs"
    for i, key in enumerate(KEYS):
        fake_run(runs, key, samples=1 if i % 3 == 0 else 50, schema=3 if i < 2 else 4)
    (runs / "notes.txt").write_text("not a run")
    (runs / f".tmp-{KEYS[0][:-6]}aaaaaa").mkdir()
    response = client.get("/api/runs")
    assert response.headers["X-Total-Count"] == "7"
    assert [r["key"] for r in response.json()["runs"]] == KEYS[::-1]  # schema 3 and 4 alike
    page = client.get("/api/runs", params={"offset": 2, "limit": 3})
    assert page.headers["X-Total-Count"] == "7" and [r["key"] for r in page.json()["runs"]] == KEYS[::-1][2:5]
    full = client.get("/api/runs", params={"include_empty": "false"})
    assert full.headers["X-Total-Count"] == "4" and all(r["samples"] > 1 for r in full.json()["runs"])
    assert client.get("/api/runs", params={"offset": 10}).json()["runs"] == []
    assert client.get("/api/runs", params={"limit": 0}).headers["X-Total-Count"] == "7"
    for bad in [{"limit": 501}, {"limit": -1}, {"offset": -1}, {"include_empty": "maybe"}]:
        assert client.get("/api/runs", params=bad).status_code == 422


def test_run_library_is_not_capped_at_100(tmp_path):
    runs = tmp_path / "runs"
    for i in range(120):
        fake_run(runs, f"20260101T{i // 60:02d}{i % 60:02d}00-{i:08x}-abcdef", samples=10)
    assert len(list_runs(runs)) == 120


def test_delete_run_removes_folder_and_zip(client, tmp_path):
    runs = tmp_path / "runs"
    fake_run(runs, KEYS[0], 10)
    fake_run(runs, KEYS[1], 10)
    assert client.delete(f"/api/runs/{KEYS[0]}", headers={"Origin": "https://evil.example"}).status_code == 403
    assert (runs / KEYS[0]).is_dir()
    response = client.delete(f"/api/runs/{KEYS[0]}")
    assert response.status_code == 200 and response.json() == {"deleted": KEYS[0]}
    assert not (runs / KEYS[0]).exists() and not (runs / f"{KEYS[0]}.zip").exists()
    assert client.delete(f"/api/runs/{KEYS[0]}").status_code == 404
    assert client.get(f"/api/runs/{KEYS[0]}").status_code == 404
    assert [r["key"] for r in client.get("/api/runs").json()["runs"]] == [KEYS[1]]
    # A JSON body is optional, and allowed.
    response = client.request("DELETE", f"/api/runs/{KEYS[1]}", json={})
    assert response.status_code == 200 and list(runs.iterdir()) == []


def test_delete_run_refuses_traversal_links_and_other_names(client, tmp_path):
    runs = tmp_path / "runs"
    fake_run(runs, KEYS[0], 10)
    outside = tmp_path / "outside"
    fake_run(outside, KEYS[1], 10)
    (runs / KEYS[1]).symlink_to(outside / KEYS[1], target_is_directory=True)
    (tmp_path / "victim.txt").write_text("keep")
    attempts = ["..", "..%2Fvictim.txt", "..%2F..%2Fvictim.txt", "%2E%2E", f"{KEYS[0]}.zip", f"{KEYS[0]}%2F..",
                f"..%2Fruns%2F{KEYS[0]}", KEYS[0].upper(), KEYS[0] + "0", "notes", KEYS[1]]
    for attempt in attempts:
        assert client.delete(f"/api/runs/{attempt}").status_code in {404, 405}, attempt
    assert (outside / KEYS[1] / "metadata.json").is_file() and (runs / KEYS[1]).is_symlink()
    assert (tmp_path / "victim.txt").read_text() == "keep" and (runs / KEYS[0]).is_dir()
    with pytest.raises(ValueError):
        delete_run("../victim.txt", runs)
    with pytest.raises(FileNotFoundError):
        delete_run(KEYS[1], runs)


def test_delete_refuses_the_run_being_recorded(client, tmp_path):
    saved = client.post("/api/export", json={}).json()
    key = Path(saved["path"]).name
    response = client.delete(f"/api/runs/{key}")
    assert response.status_code == 409 and "still being recorded" in response.json()["detail"]
    client.post("/api/reset", json=RunConfig(engine="toy").model_dump())
    assert client.delete(f"/api/runs/{key}").status_code == 200
    assert not (tmp_path / "runs" / key).exists()


def test_connectivity_library_pages_newest_first(client, tmp_path):
    data = json.loads((ROOT / "data/examples/connectivity-example.json").read_text())
    keys = []
    for i in range(3):
        data["provenance"]["dataset"] = f"example {i}"
        keys.append(client.post("/api/connectivity/import", json=data).json()["key"])
        os.utime(tmp_path / "data/connectivity" / f"{keys[-1]}.json", ns=(i * 10**9, i * 10**9))
    response = client.get("/api/connectivity", params={"limit": 2})
    assert response.headers["X-Total-Count"] == "3"
    assert [d["key"] for d in response.json()["datasets"]] == keys[::-1][:2]
    assert [d["key"] for d in client.get("/api/connectivity", params={"offset": 2}).json()["datasets"]] == keys[:1]
    assert client.get("/api/connectivity", params={"limit": 501}).status_code == 422


def test_api_schema_is_served_without_the_blank_docs_pages(client):
    for page in ["/api/docs", "/api/redoc", "/docs", "/redoc"]:
        response = client.get(page)
        assert response.status_code in {404, 503} and "swagger" not in response.text.lower(), page
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200 and "delete" in schema.json()["paths"]["/api/runs/{key}"]
