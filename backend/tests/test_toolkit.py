"""The research toolkit: configurations, trials, worker-independence, bias curves, ablation and the CLI."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from digitalfly import toolkit
from digitalfly.api.models import ConnectomeParameters, RunConfig

ROOT = Path(__file__).resolve().parents[2]


def test_configure_and_grid_reach_nested_settings():
    config = toolkit.configure({"engine": "toy"}, neural_model="connectome",
                               **{"connectome_parameters.dynamics": "spiking", "stimulus": toolkit.target(90, 10)})
    assert isinstance(config, RunConfig) and config.connectome_parameters.dynamics == "spiking"
    assert config.stimulus.x == pytest.approx(0, abs=1e-6) and config.stimulus.y == 10
    configs = toolkit.grid(config, seed=[1, 2], **{"connectome_parameters.output_gain": [1, 3]})
    assert [(c.seed, c.connectome_parameters.output_gain) for c in configs] == [(1, 1), (1, 3), (2, 1), (2, 3)]
    with pytest.raises(ValueError):
        toolkit.configure({"engine": "toy"}, **{"connectome_parameters.global_gain": -1})


def test_trials_report_behavior_and_do_not_depend_on_workers():
    configs = toolkit.grid({"engine": "toy", "neural_model": "connectome"}, seed=[1, 2],
                           stimulus=[toolkit.target(45, 12), toolkit.target(-90, 12)])
    serial = toolkit.run_trials(configs, workers=1, duration_s=1.0)
    parallel = toolkit.run_trials(configs, workers=2, duration_s=1.0)
    assert serial == parallel and len(serial) == 4
    first = serial[0]
    assert first["circuit"] == "fafb783-dna02" and first["readout_types"] == "DNa02" and first["dynamics"] == "rate"
    assert first["target_bearing_deg"] == pytest.approx(45) and first["first_turn_toward"] in (True, None)
    with_trace = toolkit.run_trial(configs[0], duration_s=.5, trajectory_every=10)
    assert len(with_trace["trajectory"]) == 5 and with_trace["final_distance_mm"] == pytest.approx(
        toolkit.run_trial(configs[0], duration_s=.5)["final_distance_mm"])


def test_bias_curve_and_ablation_on_the_toy_circuit(toy_brain):
    parameters = ConnectomeParameters(circuit="toy-brain", global_gain=.05)
    curve = toolkit.bias_curve(parameters, levels=(.5,), differences=(-.4, 0., .4), ms=200)
    turns = {row["right_minus_left"]: row["turn"] for row in curve["rows"]}
    assert turns[-.4] < 0 < turns[.4] and set(curve["equal_input_turn"]) == {.5}
    assert curve["mirror_asymmetry"] is not None and curve["mirror_asymmetry"] >= 0
    scan = toolkit.ablation_scan(parameters, left=.8, right=.2, ms=200)
    rows = {row["cell_type"]: row for row in scan["rows"]}
    assert "DNx" not in rows and scan["types_scanned"] == 5  # the readout is never silenced
    assert rows["LCa"]["turn"] == pytest.approx(0) and rows["LCa"]["change"] == pytest.approx(-scan["intact_turn"])
    assert rows["Solo"]["change"] == 0 and scan["rows"][0]["cell_type"] == "LCa"


def test_a_failing_trial_becomes_an_error_row_and_the_sweep_continues(monkeypatch):
    configs = toolkit.grid({"engine": "toy"}, seed=[1, 2, 3], stimulus=[toolkit.target(45, 12)])
    expected = toolkit.run_trials(configs, duration_s=.3)
    real = toolkit.run_trial

    def flaky(config, **kwargs):
        if config.seed == 2:
            raise FloatingPointError("nonfinite body state")
        return real(config, **kwargs)
    monkeypatch.setattr(toolkit, "run_trial", flaky)
    seen = []
    rows = toolkit.run_trials(configs, duration_s=.3, on_result=lambda index, row: seen.append(index))
    assert seen == [0, 1, 2] and rows[0] == expected[0] and rows[2] == expected[2]
    failed = rows[1]
    assert failed["error"] == "FloatingPointError: nonfinite body state" and failed["seed"] == 2
    assert failed["config"]["seed"] == 2 and failed["config_hash"] == expected[1]["config_hash"]
    assert "reached" not in failed and expected[1]["error"] is None


def test_parallel_sweeps_keep_going_when_a_worker_trial_fails(toy_brain):
    # Spawned workers do not see the test's local circuit, so its trial fails there; the others must not.
    good = [toolkit.configure({"engine": "toy", "seed": s}, stimulus=toolkit.target(45, 12)) for s in (1, 2)]
    bad = toolkit.configure({"engine": "toy", "neural_model": "connectome", "connectome_parameters": {"circuit": "toy-brain"}})
    streamed = []
    rows = toolkit.run_trials([good[0], bad, good[1]], workers=2, duration_s=.3,
                              on_result=lambda index, row: streamed.append(index))
    assert sorted(streamed) == [0, 1, 2] and rows[0] == toolkit.run_trials(good[:1], duration_s=.3)[0]
    assert rows[2]["seed"] == 2 and rows[2]["error"] is None
    assert "toy-brain" in rows[1]["error"] and rows[1]["config"]["connectome_parameters"]["circuit"] == "toy-brain"


def worker_environment(names):
    import os
    return {name: os.environ.get(name) for name in names}


def test_worker_processes_inherit_the_thread_cap(monkeypatch):
    import os
    monkeypatch.setenv("OMP_NUM_THREADS", "77")
    monkeypatch.delenv("OPENBLAS_NUM_THREADS", raising=False)
    with toolkit.thread_limit(2) as threads, toolkit._pool(2) as pool:
        seen = pool.submit(worker_environment, toolkit.THREAD_VARIABLES).result()
    assert threads == max(1, (os.cpu_count() or 1) // 2) and set(seen.values()) == {str(threads)}
    assert os.environ["OMP_NUM_THREADS"] == "77" and "OPENBLAS_NUM_THREADS" not in os.environ  # restored


def test_config_hashes_identify_trials():
    config = toolkit.configure({"engine": "toy", "neural_model": "connectome"}, stimulus=toolkit.target(45, 12))
    key = toolkit.config_hash(config, duration_s=2)
    assert key == toolkit.config_hash(config.model_dump(), duration_s=2.0) and len(key) == 16
    assert key != toolkit.config_hash(config, duration_s=3) and key != toolkit.config_hash(toolkit.configure(config, seed=7), duration_s=2)
    assert toolkit.config_hash(config) == toolkit.config_hash(config, duration_s=10.0, reach_mm=toolkit.REACH_MM)


def test_intervals_and_paired_differences():
    low, high = toolkit.wilson_interval(5, 10)
    assert low == pytest.approx(.2366, abs=1e-4) and high == pytest.approx(.7634, abs=1e-4)
    assert toolkit.wilson_interval(0, 10)[0] == 0 and toolkit.wilson_interval(10, 10)[1] == 1
    assert toolkit.wilson_interval(0, 0) is None and toolkit.bootstrap_interval([3.0]) is None
    ci = toolkit.bootstrap_interval([1, 2, 3, 4, 5])
    assert ci == toolkit.bootstrap_interval([1, 2, 3, 4, 5]) and ci[0] < 3 < ci[1]  # seeded: repeats exactly

    def row(gain, seed, reached, final, error=None):
        return {"gain": gain, "seed": seed, "target_bearing_deg": 45.0, "target_distance_mm": 12.0, "reached": reached,
                "first_turn_toward": True, "final_distance_mm": final, "mean_speed_mm_s": 5.0, "net_turn_deg": 10.0,
                "error": error}
    rows = [row(1, 1, False, 9.), row(1, 2, False, 8.), row(1, 3, True, 1.), row(1, 4, False, 7.),
            row(3, 1, True, 1.), row(3, 2, True, 2.), row(3, 3, True, 1.), row(3, 4, None, None, "RuntimeError: x"),
            row(3, 5, True, 0.)]  # seed 5 has no baseline partner
    summary = toolkit.summarize(rows, ["gain"])
    first, second = summary["conditions"]
    assert (first["trials"], first["errors"], first["reached"]) == (4, 0, 1) and second["errors"] == 1
    assert second["reached"] == 4 and second["reached_ci95"] == toolkit.wilson_interval(4, 4)
    assert first["final_distance_mm"]["mean"] == pytest.approx(6.25) and first["first_turn_toward"] == 4
    paired = summary["paired_differences"][0]
    assert paired["pairs"] == 3 and paired["baseline"] == {"gain": 1} and paired["condition"] == {"gain": 3}
    assert paired["reached"]["mean_difference"] == pytest.approx(2 / 3)
    assert paired["final_distance_mm"]["mean_difference"] == pytest.approx(((1 - 9) + (2 - 8) + (1 - 1)) / 3)
    assert summary["matched_on"] == ["seed", "target_bearing_deg", "target_distance_mm"]


def run_cli(*args, check=True):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), *args], capture_output=True, text=True,
                            timeout=300, cwd=ROOT)
    if not check:
        return result
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_command_line_tool(tmp_path):
    assert "fafb783-steering" in run_cli("circuits") and "| fafb783-dna02 | committed | 3,000 |" in run_cli("circuits")
    paths = run_cli("paths", "--source", "DNa03", "--target", "DNa02", "--hops", "2", "--out", str(tmp_path / "paths"))
    assert "DNa03 → DNa02" in paths
    saved = json.loads((tmp_path / "paths.json").read_text())
    assert saved["paths"][0]["cell_types"] == ["DNa03", "DNa02"] and saved["provenance"]["circuits"][0]["name"] == "fafb783-dna02"
    assert (tmp_path / "paths.csv").read_text().startswith("path,steps,strength,net_sign\nDNa03 → DNa02,1,")
    out = tmp_path / "bias"
    text = run_cli("bias", "--levels", ".5", "--differences=-.2,0,.2", "--ms", "50", "--out", str(out))
    assert "Mirror asymmetry" in text
    report = json.loads(out.with_suffix(".json").read_text())
    assert report["parameters"]["circuit"] == "fafb783-dna02" and len(report["rows"]) == 3
    assert out.with_suffix(".csv").read_text().startswith("level,right_minus_left")
    provenance = report["provenance"]
    assert provenance["command"][1:3] == ["bias", "--levels"] and provenance["packages"]["digitalfly"]
    assert len(provenance["git_commit"] or "0" * 40) == 40 and len(provenance["circuits"][0]["sha256"]) == 64


def test_trials_honour_seed_and_intensity_settings_and_resume(tmp_path):
    refused = run_cli("trials", "--vary", "seed=7,8", "--seeds", "1", check=False)
    assert refused.returncode == 1 and "leave out --seeds" in refused.stderr
    refused = run_cli("trials", "--set", "stimulus.x=5", "--bearings", "45", check=False)
    assert refused.returncode == 1 and "--bearings" in refused.stderr
    assert "--resume needs --out" in run_cli("trials", "--resume", check=False).stderr
    out = tmp_path / "sweep"
    args = ["trials", "--vary", "seed=7,8", "--set", "stimulus.intensity=0.5", "--bearings", "45,-45", "--distances", "12",
            "--duration", ".2", "--out", str(out)]
    run_cli(*args)
    report = json.loads(out.with_suffix(".json").read_text())
    assert [(r["trial"], r["seed"], r["target_bearing_deg"]) for r in report["trials"]] == [
        (0, 7, 45), (1, 7, -45), (2, 8, 45), (3, 8, -45)]
    assert {r["target_intensity"] for r in report["trials"]} == {.5} and report["errors"] == 0
    assert report["statistics"]["conditions"][0]["trials"] == 4 and report["provenance"]["command"][1] == "trials"
    full = out.with_suffix(".csv").read_text()
    lines = out.with_suffix(".jsonl").read_text().splitlines()
    assert len(lines) == 4 and len(full.splitlines()) == 5
    out.with_suffix(".jsonl").write_text("\n".join(lines[:3]) + "\n")  # as if interrupted before the last trial
    assert "Running 1 trials" in run_cli(*args, "--resume") and out.with_suffix(".csv").read_text() == full
    assert len(out.with_suffix(".jsonl").read_text().splitlines()) == 4


def test_trial_log_appends_widens_and_resumes_only_successful_trials(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("toolkit_cli", ROOT / "scripts/toolkit.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    stem = tmp_path / "log"
    log = cli.TrialLog(stem, resume=False)
    log.add({"trial": 1, "seed": 2, "config_hash": "b", "error": "FloatingPointError: x", "config": {"seed": 2}})
    log.add({"trial": 0, "seed": 1, "config_hash": "a", "error": None, "reached": True})  # a new column
    log.add({"trial": 2, "seed": 3, "config_hash": "c", "error": None, "reached": False})
    assert stem.with_suffix(".csv").read_text().splitlines() == [
        "trial,seed,config_hash,error,reached", "1,2,b,FloatingPointError: x,", "0,1,a,,True", "2,3,c,,False"]
    assert len(stem.with_suffix(".jsonl").read_text().splitlines()) == 3
    resumed = cli.TrialLog(stem, resume=True)
    assert sorted(resumed.saved) == ["a", "c"]  # the failed trial runs again
    assert cli.TrialLog(stem, resume=False).saved == {} and not stem.with_suffix(".jsonl").exists()


def test_ablation_takes_cell_types_with_commas_and_checks_names_first(tmp_path):
    out = tmp_path / "ablation"
    text = run_cli("ablation", "--type", "AOTU018,AOTU031", "--types", "PS049", "--ms", "5", "--out", str(out))
    assert "| AOTU018,AOTU031 |" in text and "| PS049 |" in text
    assert {r["cell_type"] for r in json.loads(out.with_suffix(".json").read_text())["rows"]} == {"AOTU018,AOTU031", "PS049"}
    refused = run_cli("ablation", "--types", "AOTU018,AOTU031", "--ms", "5", check=False)
    assert refused.returncode == 1 and "Not a cell type in the fafb783-dna02 circuit: AOTU018, AOTU031" in refused.stderr


def test_jump_command_exports_a_run_for_compare(tmp_path):
    text = run_cli("jump", "--engine", "toy", "--set", "neural_model=connectome", "--set", "seed=3", "--duration", "1",
                   "--every", ".5", "--jump-seed", "5", "--export-dir", str(tmp_path / "runs"), "--out", str(tmp_path / "jump"))
    report = json.loads((tmp_path / "jump.json").read_text())
    run = Path(report["run"]["path"])
    run = run if run.is_absolute() else ROOT / run
    metadata = json.loads((run / "metadata.json").read_text())
    assert "compare --run" in text and report["run"]["samples"] == 101 and report["jump_seed"] == 5
    assert metadata["initial_config"]["seed"] == 3 and sum(e["kind"] == "stimulus" for e in metadata["events"]) == 2


def test_partial_evaluations_never_take_the_full_report_name():
    import importlib.util
    spec = importlib.util.spec_from_file_location("evaluate_models", ROOT / "scripts/evaluate_models.py")
    evaluate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluate)
    everything = list(evaluate.MODELS)
    assert evaluate.report_name("toy", False, everything, 10.) == "evaluation-toy.json"
    assert evaluate.report_name("flygym", True, everything[::-1], 6.) == "evaluation-flygym-quick.json"
    assert evaluate.report_name("toy", False, ["engineered"], 10.) == "evaluation-toy-engineered.json"
    assert evaluate.report_name("toy", True, everything, 2.5) == "evaluation-toy-quick-2.5s.json"
    assert evaluate.report_name("flygym", False, ["connectome", "steering"], 3.) == "evaluation-flygym-connectome+steering-3s.json"
