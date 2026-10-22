"""Atomic writes never go through a link placed at their temporary name: replay verdicts, circuit files, run
annotations and exports each write a new file, created exclusively under an unpredictable name."""
import importlib.util
import json
import os
import uuid
from pathlib import Path
import pytest
from digitalfly.api.models import RunConfig
from digitalfly.data import research
from digitalfly.data.jobs import _writer_alive
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]
GUESSED = uuid.UUID(int=1)


def script(name):
    spec = importlib.util.spec_from_file_location(f"{name}_safe_writes", ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def target(tmp_path):
    """A file a link planted in a writable folder points at; it must keep its content."""
    path = tmp_path / "elsewhere.txt"
    path.write_text("keep")
    return path


def export_toy_run(folder: Path) -> Path:
    exp = Experiment(RunConfig(engine="toy", seed=2), render=False)
    try:
        for _ in range(3):
            exp.advance()
        return Path(exp.export(folder)["path"])
    finally:
        exp.close()


def test_replay_verdicts_are_never_written_through_a_link(tmp_path, target, monkeypatch):
    replay = script("replay")
    run = tmp_path / "run"
    run.mkdir()
    (run / f".replay.json.{os.getpid()}.part").symlink_to(target)  # the name used before: the job's process id
    replay.save_verdict(run, {"ok": True})
    assert json.loads((run / "replay.json").read_text()) == {"ok": True} and not (run / "replay.json").is_symlink()
    assert target.read_text() == "keep"
    monkeypatch.setattr(replay.uuid, "uuid4", lambda: GUESSED)  # a guessed name is refused, never followed
    (run / f".replay.json.{GUESSED.hex}.part").symlink_to(target)
    with pytest.raises(FileExistsError):
        replay.save_verdict(run, {"ok": False})
    assert target.read_text() == "keep" and json.loads((run / "replay.json").read_text()) == {"ok": True}


def test_circuit_files_are_never_written_through_a_link(tmp_path, target, monkeypatch):
    build = script("build_circuit")
    path = tmp_path / "local/mine.json"
    path.parent.mkdir()
    (path.parent / f".mine.json.{os.getpid()}.part").symlink_to(target)  # the name used before
    parts = []
    build.write_atomic(path, lambda handle: parts.append(Path(handle.name)) or handle.write(b"{}"))
    assert path.read_bytes() == b"{}" and not path.is_symlink() and target.read_text() == "keep"
    # Hidden, and ending in the builder's process id, which the app's leftover cleanup reads.
    assert parts[0].name.startswith(".mine.json.") and parts[0].name.endswith(".part") and _writer_alive(parts[0])
    monkeypatch.setattr(build.uuid, "uuid4", lambda: GUESSED)
    (path.parent / f".mine.json.{GUESSED.hex[:12]}.{os.getpid()}.part").symlink_to(target)
    with pytest.raises(FileExistsError):
        build.write_atomic(path, lambda handle: handle.write(b"[]"))
    assert target.read_text() == "keep" and path.read_bytes() == b"{}"


def test_run_annotations_are_never_written_through_a_link(tmp_path, target, monkeypatch):
    run = export_toy_run(tmp_path)
    monkeypatch.setattr(research.uuid, "uuid4", lambda: GUESSED)
    for name in (GUESSED.hex, GUESSED.hex[:6]):  # the names a guessed random part gives now and gave before
        (run / f".annotations.json.{name}.tmp").symlink_to(target)
    with pytest.raises(FileExistsError):
        research.annotate_run(run.name, research.RunAnnotations(notes="mine"), tmp_path)
    assert target.read_text() == "keep" and not (run / "annotations.json").exists()


def test_exports_are_never_written_through_a_link(tmp_path, target):
    exp = Experiment(RunConfig(engine="toy", seed=2), render=False)
    try:
        exp.advance()
        job, again = exp.export_job(tmp_path), exp.export_job(tmp_path)
    finally:
        exp.close()
    (tmp_path / f".tmp-{job.name}.zip").symlink_to(target)  # placed once the staging folder showed the name
    with pytest.raises(FileExistsError):
        job.write()
    assert target.read_text() == "keep" and not list(tmp_path.glob(f"*{job.name}*"))
    assert Path(again.write()["path"]).is_dir() and (tmp_path / f"{again.name}.zip").is_file()
