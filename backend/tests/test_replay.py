"""scripts/replay.py on an exported toy run, and its refusal to replay against a changed circuit file."""
import json
import subprocess
import sys
from pathlib import Path
from digitalfly import toolkit
from digitalfly.simulation.experiment import Experiment

ROOT = Path(__file__).resolve().parents[2]


def replay(run, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run), *args], capture_output=True,
                          text=True, timeout=120)


def test_replay_refuses_a_circuit_that_changed_since_the_run(tmp_path):
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome", "seed": 5}, stimulus=toolkit.target(30, 10))
    exp = Experiment(config, render=False)
    try:
        for _ in range(40):
            exp.advance()
        run = Path(exp.export(tmp_path)["path"])
    finally:
        exp.close()
    done = replay(run)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["passed"] is True
    metadata = json.loads((run / "metadata.json").read_text())
    recorded = metadata["neural"]["circuit_sha256"]
    metadata["neural"]["circuit_sha256"] = "0" * 64  # as if the run had used an earlier build of fafb783-dna02
    (run / "metadata.json").write_text(json.dumps(metadata))
    refused = replay(run)
    assert refused.returncode == 1 and "fafb783-dna02 circuit has changed" in refused.stderr
    assert f"{recorded[:12]}… now" in refused.stderr and "--allow-circuit-mismatch" in refused.stderr
    forced = replay(run, "--allow-circuit-mismatch")  # the file is in fact the same, so the replay itself matches
    assert forced.returncode == 0, forced.stderr
