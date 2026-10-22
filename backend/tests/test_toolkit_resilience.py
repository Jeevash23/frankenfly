"""Toolkit sweeps that lose a worker process, trial logs (new folders, dotted names, torn lines, other code versions),
the example's summary, --vary JSON axes, settings inside empty groups and the ablation scan's refusals."""
import importlib.util
import json
import multiprocessing
import os
import signal
import subprocess
import sys
from pathlib import Path
import pytest
from digitalfly import robustness, toolkit
from digitalfly.api.models import ConnectomeParameters

ROOT = Path(__file__).resolve().parents[2]
CONNECTOME = {"engine": "toy", "neural_model": "connectome"}
TOY = ConnectomeParameters(circuit="toy-brain", global_gain=.05)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kill_a_worker(killed):
    """An on_result callback that kills one pool worker (SIGKILL, as the out-of-memory killer does) after the first
    result, while the other trials are still running or waiting."""
    def callback(index, row):
        if not killed:
            worker = next(p for p in multiprocessing.active_children() if p.is_alive())
            os.kill(worker.pid, signal.SIGKILL)
            killed.append(worker.pid)
    return callback


def test_a_killed_worker_process_costs_no_trials(capsys):
    configs = toolkit.grid(CONNECTOME, seed=[1, 2, 3, 4, 5, 6], stimulus=[toolkit.target(45, 12)])
    expected = toolkit.run_trials(configs, duration_s=.5)
    killed = []
    rows = toolkit.run_trials(configs, workers=2, duration_s=.5, on_result=kill_a_worker(killed))
    assert killed and [r["error"] for r in rows] == [None] * 6
    assert rows == expected  # the trials it took down ran again, from their own reset
    assert "A worker process died (killed, or out of memory?); " in capsys.readouterr().err


def test_a_killed_worker_process_costs_no_robustness_variants():
    found = robustness.variants(ConnectomeParameters(), {"synapse_threshold": [5, 10, 20], "seed": [1, 2]})
    expected = robustness.run(found, ("bias",), ms=200)
    killed = []
    rows = robustness.run(found, ("bias",), workers=2, ms=200, on_result=kill_a_worker(killed))
    assert killed and rows == expected and not any(r["error"] for r in rows)


def exit_on_two(task):
    """A task that kills its own worker process every time (os._exit skips all cleanup, like a crash)."""
    index, value = task
    if value == 2:
        os._exit(1)
    return index, value * 10


def test_only_the_task_that_kills_its_worker_fails():
    done = {}
    toolkit._parallel(exit_on_two, [(k, k) for k in range(6)], 2, done.__setitem__,
                      lambda task, error: f"failed: {error}")
    assert {k: v for k, v in done.items() if k != 2} == {0: 0, 1: 10, 3: 30, 4: 40, 5: 50}
    assert done[2].startswith("failed: BrokenProcessPool: ") and "on its own" in done[2]


def test_trial_logs_make_their_folder_and_keep_dots_in_names(tmp_path):
    log = toolkit.TrialLog(tmp_path / "new" / "folder" / "gain-1.5")  # neither folder exists yet
    log.add({"config_hash": "a", "error": None, "seed": 1})
    other = toolkit.TrialLog(tmp_path / "new" / "folder" / "gain-1.0")
    other.add({"config_hash": "b", "error": None, "seed": 2})
    assert sorted(p.name for p in (tmp_path / "new" / "folder").iterdir()) == [
        "gain-1.0.csv", "gain-1.0.jsonl", "gain-1.5.csv", "gain-1.5.jsonl"]
    assert toolkit.TrialLog(tmp_path / "new" / "folder" / "gain-1.5.jsonl", resume=True).saved.keys() == {"a"}


def test_resuming_skips_a_torn_last_line_and_names_rows_from_other_code(tmp_path):
    messages = []
    log = toolkit.TrialLog(tmp_path / "sweep", log=messages.append)
    for key in "abc":
        log.add({"config_hash": key, "error": None, "seed": 1})
    lines = (tmp_path / "sweep.jsonl").read_text().splitlines()
    stamp = json.loads(lines[0])["code"]
    assert stamp == toolkit.code_version() and set(stamp) == {"digitalfly", "git_commit", "git_dirty"}
    older = {**json.loads(lines[1]), "code": {"digitalfly": "0.5.0", "git_commit": "1" * 40, "git_dirty": False}}
    unstamped = {k: v for k, v in json.loads(lines[2]).items() if k != "code"}  # written before v0.6
    (tmp_path / "sweep.jsonl").write_text("\n".join([lines[0], json.dumps(older), json.dumps(unstamped)])
                                          + '\n{"config_hash": "d", "err')  # the process died mid-write
    resumed = toolkit.TrialLog(tmp_path / "sweep", resume=True, log=messages.append)
    assert sorted(resumed.saved) == ["a", "b", "c"] and "code" not in resumed.saved["a"]
    assert messages[0] == "Skipped 1 unreadable line in " + str(tmp_path / "sweep.jsonl") + " (an interrupted write?)."
    assert messages[1].startswith("2 of 3 saved rows were computed by other code (digitalfly 0.5.0 at commit 11111111; "
                                  "not recorded) and are reused") and "without --resume" in messages[1]
    resumed.add({"config_hash": "e", "error": None, "seed": 1})  # starts on a line of its own after the torn one
    assert json.loads((tmp_path / "sweep.jsonl").read_text().splitlines()[-1])["config_hash"] == "e"
    assert resumed.rows_for(["c", "x", "a"]) == [resumed.saved["c"], resumed.saved["a"]]
    resumed.add({"config_hash": "a", "error": "RuntimeError: again", "seed": 1})
    assert resumed.rows_for(["a"])[0]["error"] == "RuntimeError: again"  # the latest row for a hash


def test_the_batch_example_summarizes_only_this_batch(tmp_path):
    def batch(*args):
        done = subprocess.run([sys.executable, str(ROOT / "examples/batch_seeds.py"), "--duration", ".2",
                               "--out", str(tmp_path / "batch"), *args], capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stderr
        return done.stdout
    assert "| rate | 4 |" in batch("--seeds", "1-2")
    again = batch("--seeds", "1", "--resume")  # a smaller batch in the same log: its own 2 trials per dynamics
    assert "Running 0 of 4 trials" in again and "| rate | 2 |" in again and "| spiking | 2 |" in again


def test_command_line_outputs_keep_dots_in_names(tmp_path):
    out = tmp_path / "gain-1.5"
    done = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "bias", "--levels", ".5", "--differences=0",
                           "--ms", "5", "--out", str(out)], capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert done.returncode == 0, done.stderr
    assert f"Saved {out}.json and {out}.csv" in done.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gain-1.5.csv", "gain-1.5.json"]


def test_evaluation_logs_keep_dots_in_names(tmp_path, capsys):
    evaluate = load("evaluate_models", "scripts/evaluate_models.py")
    for duration in (".1", ".15"):  # each log once took the name evaluation-toy-quick-0.jsonl
        evaluate.main(["--engine", "toy", "--quick", "--models", "engineered", "--duration", duration,
                       "--out", str(tmp_path / f"evaluation-toy-quick-0{duration}s.json")])
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        f"evaluation-toy-quick-0.{d}s.{ending}" for d in ("15", "1") for ending in ("csv", "json", "jsonl")]
    assert (tmp_path / "evaluation-toy-quick-0.1s.jsonl").read_text().count("\n") == 18
    assert "Saved " + str(tmp_path / "evaluation-toy-quick-0.15s.json") in capsys.readouterr().out


def test_vary_reads_json_lists_of_objects_as_one_axis():
    cli = load("toolkit_cli", "scripts/toolkit.py")
    found = cli.axes(['stimulus=[{"x": 5, "y": 5}, {"x": 5, "y": -5}]', "seed=1,2",
                      'connectome_parameters.readout_types=[["DNa02"],["DNa02","DNp09"]]',
                      'connectome_parameters.readout_weights=[null,{"DNa02":2}]'])
    assert found == {"stimulus": [{"x": 5, "y": 5}, {"x": 5, "y": -5}], "seed": [1, 2],
                     "connectome_parameters.readout_types": [["DNa02"], ["DNa02", "DNp09"]],
                     "connectome_parameters.readout_weights": [None, {"DNa02": 2}]}
    with pytest.raises(SystemExit, match="not a JSON list"):
        cli.axes(['stimulus=[{"x": 5}'])


def test_dotted_settings_fill_an_empty_group_and_bad_ones_fail_in_one_line():
    config = toolkit.configure(CONNECTOME, **{"connectome_parameters.readout_weights.DNa02": 2})
    assert config.connectome_parameters.readout_weights == {"DNa02": 2}
    found = robustness.variants(ConnectomeParameters(), {"readout_weights.DNa02": [1, .5]})
    assert [v["parameters"].readout_weights for v in found] == [{"DNa02": 1}, {"DNa02": .5}]
    with pytest.raises(ValueError, match="seed is a single setting, not a group"):
        toolkit.configure(toolkit.configure(CONNECTOME), **{"seed.x": 1})
    for args, message in [
            (["trials", "--vary", "connectome_parameters.readout_weights.DNa02=1,9"],
             "Invalid setting connectome_parameters.readout_weights.DNa02: Input should be less than or equal to 5"),
            (["trials", "--set", "seed.x=1"], "Invalid setting seed: Input should be a valid integer"),
            (["trials", "--vary", "seed.x=1,2"], "ValueError: Cannot set seed.x: seed is a single setting, not a group."),
            (["robustness", "--ms", "5", "--vary", "readout_weights.DNa02=1,9"],
             "Invalid setting readout_weights.DNa02: Input should be less than or equal to 5")]:
        done = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), *args], capture_output=True, text=True,
                              timeout=120, cwd=ROOT)
        assert done.returncode == 1 and done.stderr.strip().splitlines() == [message], done.stderr


def test_ablation_refuses_named_readout_types_and_names_the_types_it_checks(toy_brain):
    with pytest.raises(ValueError, match="Readout types are not scanned, since the turn is read from them: DNx"):
        toolkit.ablation_scan(TOY, cell_types=["LCa", "DNx"], ms=5)
    with pytest.raises(ValueError, match=r"take 0–500 Hz\): LCa, Inh\.$"):
        toolkit.ablation_scan(TOY, cell_types=["LCa", "Inh"], ms=5, mode="activate", value=2)
    with pytest.raises(ValueError, match=r"take 0–500 Hz\): every cell type\.$"):
        toolkit.ablation_scan(TOY, ms=5, mode="activate", value=2)
