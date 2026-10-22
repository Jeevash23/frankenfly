"""scripts/benchmark.py: the neural-step microbenchmark and the FlyVis timing (or why it was skipped)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/benchmark.py"), *args], capture_output=True, text=True,
                          timeout=300, cwd=ROOT)


def load_benchmark():
    spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts/benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_neural_step_benchmark(toy_brain, tmp_path):
    benchmark = load_benchmark()
    whole = json.loads(toy_brain.read_text())
    whole["provenance"]["build"]["whole_brain"] = True
    (toy_brain.parent / "toy-whole.json").write_text(json.dumps(whole))
    # Committed circuits and local whole-brain builds; other local circuits only when named.
    names = benchmark.neural_circuits()
    assert names[-1] == "toy-whole" and set(names[:-1]) == {
        "fafb783-dna02", "fafb783-dna02-balanced", "fafb783-steering", "fafb783-steering-balanced"}
    timed = benchmark.time_neural_step("toy-whole", "spiking", steps=20, warmup=2)
    assert timed["neurons"] == 10 and timed["whole_brain"] and timed["ms_per_step"] > 0 and timed["steps"] == 20
    done = run("--neural", "--circuit", "fafb783-dna02", "--steps", "5", "--warmup", "1", "--out", str(tmp_path / "neural.json"))
    assert done.returncode == 0, done.stderr
    report = json.loads((tmp_path / "neural.json").read_text())
    assert [(r["circuit"], r["dynamics"]) for r in report["rows"]] == [("fafb783-dna02", "rate"), ("fafb783-dna02", "spiking")]
    assert report["rows"][0]["neurons"] == 3000 and "per 1 ms neural step" in done.stdout
    assert run("--neural", "--vision").returncode == 2


@pytest.mark.skipif(importlib.util.find_spec("flyvis") is not None, reason="FlyVis is installed: --flyvis times it")
def test_the_flyvis_benchmark_says_why_it_skipped(tmp_path):
    done = run("--flyvis", "--out", str(tmp_path / "flyvis.json"))
    assert done.returncode == 0, done.stderr
    report = json.loads((tmp_path / "flyvis.json").read_text())
    assert report["available"] is False and "vision lock" in report["skipped"]
