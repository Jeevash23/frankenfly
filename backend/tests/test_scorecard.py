"""Validation scorecard: the tests' definitions, the measurements and rules, the plans for models and circuits that
lack what a test needs, a fast toy-body scorecard of the engineered model and the committed DNa02 circuit (the CI
subset), storage, the command line and the API."""
import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from fastapi.testclient import TestClient
from digitalfly import scorecard as sc
from digitalfly.api.models import RunConfig
from digitalfly.data import jobs as background
from digitalfly.main import create_app
from digitalfly.neural.connectome import load_circuit

ROOT = Path(__file__).resolve().parents[2]
FAST = {"engine": "toy", "seeds": [1], "duration_s": 1.5}


def test_every_test_cites_its_source_and_states_its_rule():
    assert len(set(sc.TEST_IDS)) == len(sc.TESTS) >= 8
    for test in sc.definitions():
        assert test["source"]["citation"] and test["source"]["finding"]
        assert test["source"]["url"] == f"https://doi.org/{test['source']['doi']}"
        assert test["rule"] and test["manipulation"] and test["measure"]
        assert set(test["needs"]) <= set(sc.CAPABILITY_TEXT)
    kinds = {t["kind"] for t in sc.TESTS}
    assert kinds - {"listed"} == set(sc.SCORERS)


def trajectory(seconds=1., yaw_rate=0., speed=0., dt=.01):
    """[t, x, y, yaw] rows of a body turning at yaw_rate (rad/s) and moving at speed (mm/s) along its axis."""
    rows, x, y, yaw = [], 0., 0., 0.
    for k in range(1, round(seconds / dt) + 1):
        yaw += yaw_rate * dt
        x, y = x + speed * dt * math.cos(yaw), y + speed * dt * math.sin(yaw)
        rows.append([k * dt, x, y, yaw])
    return rows


def test_trial_metrics_read_turning_and_forward_or_backward_walking():
    left = sc.trial_metrics(trajectory(yaw_rate=1., speed=5.))
    assert left["yaw_rate_deg_s"] == pytest.approx(math.degrees(1.)) and left["rotational_speed_deg_s"] > 0
    assert left["forward_velocity_mm_s"] == pytest.approx(5., rel=1e-3)
    right = sc.trial_metrics(trajectory(yaw_rate=-1., speed=5.))
    assert right["yaw_rate_deg_s"] == pytest.approx(-math.degrees(1.))
    assert sc.trial_metrics(trajectory(speed=-3.))["forward_velocity_mm_s"] == pytest.approx(-3., rel=1e-3)
    assert left["rotational_speed_deg_s"] == pytest.approx(math.degrees(1.))


def test_stride_wobble_is_not_counted_as_turning():
    """FlyGym's body yaws back and forth at the 12 Hz stride; over 0.25 s bins that is no rotation."""
    rows = [[k / 100, 0., 0., .1 * math.sin(2 * math.pi * 12 * k / 100)] for k in range(1, 201)]
    metrics = sc.trial_metrics(rows)
    assert metrics["rotational_speed_deg_s"] < 1 and abs(metrics["yaw_rate_deg_s"]) < 5
    raw = np.degrees(np.abs(np.diff([r[3] for r in rows])) / .01).mean()
    assert raw > 100  # what 10 ms yaw rates would have called turning
    with pytest.raises(ValueError, match="before the measurement window"):
        sc.trial_metrics(trajectory(seconds=.15))


def rows(condition, values, key="yaw_rate_deg_s", **extra):
    return [{"condition": condition, "seed": seed, key: value, **extra} for seed, value in enumerate(values)]


@pytest.mark.parametrize("left, right, status", [(20, 10, "pass"), (20, -1, "partial"), (2, 1, "partial"),
                                                 (-20, 40, "partial"), (-20, 5, "fail"), (0, 0, "fail")])
def test_unilateral_rule(left, right, status):
    trials = (rows("dark", [3, 3]) + rows("dark, X left activated", [3 + left] * 2)
              + rows("dark, X right activated", [3 - right] * 2))  # a rightward turn is a negative yaw rate
    got, measured = sc._unilateral(None, ["X"], trials)
    assert got == status
    assert measured["left_deg_s"] == pytest.approx(left) and measured["right_deg_s"] == pytest.approx(right)


@pytest.mark.parametrize("silenced, status", [(50, "pass"), (30, "partial"), (90, "partial"), (10, "fail"),
                                              (0, "fail"), (150, "fail")])
def test_bilateral_silencing_rule(silenced, status):
    trials = (rows("target +45°", [40, 60], "rotational_speed_deg_s")
              + rows("target +45°, X silenced", [silenced] * 2, "rotational_speed_deg_s"))
    assert sc._bilateral_silencing(None, ["X"], trials)[0] == status
    still = rows("target +45°", [1, 1], "rotational_speed_deg_s") + rows("target +45°, X silenced", [1, 1],
                                                                          "rotational_speed_deg_s")
    assert sc._bilateral_silencing(None, ["X"], still)[0] == "inconclusive"


@pytest.mark.parametrize("active, status", [(-1, "pass"), (2, "partial"), (0, "partial"), (4, "fail"), (6, "fail")])
def test_backward_rule(active, status):
    trials = rows("dark", [5, 5], "forward_velocity_mm_s") + rows("dark, MDN activated", [active] * 2,
                                                                   "forward_velocity_mm_s")
    assert sc._backward(None, ["MDN"], trials)[0] == status
    slow = rows("dark", [.2], "forward_velocity_mm_s") + rows("dark, MDN activated", [-2], "forward_velocity_mm_s")
    assert sc._backward(None, ["MDN"], slow)[0] == "inconclusive"


def symmetry_rows(pairs):
    out = []
    for seed, (plus, minus) in enumerate(pairs):
        out += [{"seed": seed, "target_bearing_deg": 45., "early_yaw_rate_deg_s": plus},
                {"seed": seed, "target_bearing_deg": -45., "early_yaw_rate_deg_s": minus}]
    return out


def test_symmetry_index_and_rule():
    assert sc._symmetry(None, [], symmetry_rows([(10, -10)]))[0] == "pass"
    status, measured = sc._symmetry(None, [], symmetry_rows([(30, -10)]))
    assert status == "fail" and measured["value"] == pytest.approx(.5)  # (30 − 10) / 40, a leftward bias
    status, measured = sc._symmetry(None, [], symmetry_rows([(10, -15)]))
    assert status == "partial" and measured["value"] == pytest.approx(-.2) and "rightward" in measured["text"]
    assert sc._symmetry(None, [], symmetry_rows([(0, 0)]))[0] == "inconclusive"


def test_plans_say_what_a_model_or_circuit_lacks(toy_brain):
    tests = {t["id"]: t for t in sc.TESTS}
    engineered = sc.Target("engineered")
    unilateral = sc.plan(tests["dna02_unilateral_activation"], engineered, None)
    assert unilateral["status"] == "not_testable" and "no identified cell types" in unilateral["reasons"][0]
    assert sc.plan(tests["left_right_symmetry"], engineered, None)["status"] == "planned"
    assert sc.plan(tests["sugar_grn_mn9"], engineered, None)["status"] == "blocked"
    toy = load_circuit("toy-brain")
    target = sc.Target("connectome", circuit="toy-brain")
    mdn = sc.plan(tests["mdn_activation_backward"], target, toy)
    assert mdn["status"] == "not_testable" and mdn["reasons"] == ["the toy-brain circuit has no MDN neurons"]
    grooming = sc.plan(tests["antennal_grooming"], target, toy)
    assert grooming["status"] == "not_testable" and "DNg62 or DNge078" in grooming["reasons"][0]
    assert any("grooming motor program" in r for r in grooming["reasons"])
    dna02 = load_circuit("fafb783-steering")
    present = sc.plan(tests["antennal_grooming"], sc.Target("connectome", circuit="fafb783-steering"), dna02)
    assert present["status"] == "blocked" and present["names"] == ["DNg62"]  # the cell types are there, the body is not


def test_a_scorecard_shares_control_trials_between_tests(monkeypatch):
    calls = []

    def fake(configs, workers=1, on_result=None, **kwargs):
        calls.append(configs)
        return [{"error": "skipped", "target_bearing_deg": 0} for _ in configs]
    monkeypatch.setattr(sc.toolkit, "run_trials", fake)
    card = sc.run(sc.Target("connectome"), seeds=[1, 2])
    labels = {(c.stimulus.intensity, c.initial_interventions.model_dump_json()) for c in calls[0]}
    # dark control, DNa02 and DNp09 left/right, MDN; 4 lateral controls and 4 with DNa02 silenced: 14, per seed
    assert len(calls[0]) == 28 and len(labels) == 8
    assert {t["status"] for t in card["tests"] if t["id"] in ("mdn_activation_backward", "left_right_symmetry")} == {"error"}


def test_toy_body_scorecard_of_the_engineered_model_and_the_dna02_circuit():
    """The CI subset: one seed, 1.5 s trials on the toy body."""
    engineered = sc.run(sc.Target("engineered"), **FAST)
    by_id = {t["id"]: t for t in engineered["tests"]}
    assert by_id["left_right_symmetry"]["status"] == "pass" and by_id["left_right_symmetry"]["by_construction"]
    assert engineered["summary"]["scored"] == 1 and engineered["summary"]["not_testable"] == 6
    assert engineered["key"] == "engineered-toy" and not engineered["summary"]["error"]

    card = sc.run(sc.Target("connectome", circuit="fafb783-dna02"), **FAST)
    by_id = {t["id"]: t for t in card["tests"]}
    assert card["key"] == "connectome-fafb783-dna02-rate-toy" and card["model"]["readout_types"] == ["DNa02"]
    unilateral = by_id["dna02_unilateral_activation"]
    assert unilateral["status"] == "pass" and "readout type" in unilateral["by_construction"]
    silencing = by_id["dna02_bilateral_silencing"]
    assert silencing["status"] == "fail" and silencing["measured"]["value"] == pytest.approx(0, abs=1e-9)
    assert silencing["by_construction"]
    # DNp09 is not read out here, so its result comes from the wiring into DNa02.
    assert by_id["dnp09_unilateral_activation"]["by_construction"] is None
    assert by_id["dnp09_unilateral_activation"]["measured"]["value"] > 0
    assert by_id["mdn_activation_backward"]["status"] != "pass"  # this body cannot walk backward
    assert by_id["left_right_symmetry"]["measured"]["value"] > 0  # the DNa02 circuit's known left bias
    assert by_id["left_right_symmetry"]["measured"]["open_loop_equal_input_turn"] < 0
    assert by_id["giant_fiber_takeoff"]["status"] == "not_testable"
    assert by_id["sugar_grn_mn9"]["status"] == "blocked"
    assert all(t["status"] != "error" for t in card["tests"])
    assert "| MDN activation → backward walking |" in sc.markdown(card)


def test_scorecards_are_published_and_listed_newest_first(tmp_path):
    older = {"format": "digitalfly-scorecard", "key": "engineered-toy", "created": "2026-01-01T00:00:00+00:00",
             "trials": [{}, {}], "tests": []}
    newer = {**older, "key": "connectome-fafb783-dna02-rate-toy", "created": "2026-02-01T00:00:00+00:00"}
    for card in (older, newer):
        sc.publish(card, tmp_path)
    (tmp_path / "broken.json").write_text("{")
    (tmp_path / "other.json").write_text(json.dumps({"format": "something else"}))
    listed = sc.latest(tmp_path)
    assert [c["key"] for c in listed] == [newer["key"], older["key"]]
    assert listed[0]["trial_count"] == 2 and "trials" not in listed[0]
    assert not list(tmp_path.glob(".*.part"))
    with pytest.raises(ValueError, match="Not a scorecard name"):
        sc.publish({**older, "key": "../escape"}, tmp_path)
    assert sc.latest(tmp_path / "missing") == []


def test_the_command_line_scores_and_publishes(tmp_path):
    done = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "scorecard", "--model", "engineered",
                           "--seeds", "1", "--duration", "1.2", "--out", str(tmp_path / "card"), "--publish-dir",
                           str(tmp_path / "latest"), "--progress"], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    assert lines[0].startswith("@progress") and json.loads(lines[-1])["scorecards"][0]["key"] == "engineered-toy"
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["provenance"]["command"] and (tmp_path / "card.csv").is_file()
    assert sc.latest(tmp_path / "latest")[0]["key"] == "engineered-toy"
    listing = subprocess.run([sys.executable, str(ROOT / "scripts/toolkit.py"), "scorecard", "--list"],
                             capture_output=True, text=True, timeout=120)
    assert listing.returncode == 0 and "doi:10.1126/science.1249964" in listing.stdout


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in ["simulation.experiment", "main", "data.research"]:
        monkeypatch.setattr(f"digitalfly.{module}.ROOT", tmp_path)
    monkeypatch.setattr(sc, "SCORECARD_DIR", tmp_path / "scorecards")
    app = create_app(RunConfig(engine="toy"), render=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert app.state.worker.ready.wait(10)
        yield client


def test_the_api_lists_tests_and_cards_and_starts_a_scorecard_job(client, monkeypatch):
    listing = client.get("/api/scorecards").json()
    assert listing["version"] == sc.SCORECARD_VERSION and listing["scorecards"] == []
    assert [t["id"] for t in listing["tests"]] == sc.TEST_IDS
    sc.publish({"format": "digitalfly-scorecard", "key": "engineered-toy", "created": "2026-01-01", "tests": []})
    assert [c["key"] for c in client.get("/api/scorecards").json()["scorecards"]] == ["engineered-toy"]

    submitted = []

    def fake_submit(jobs, model, engine, circuit=None, dynamics="rate", key=None, label=None):
        submitted.append((model, engine, circuit, dynamics, key, label))
        return jobs.submit("scorecard", label, [sys.executable, "-c", "print('{}')"], target=key,
                           duplicate="This model's scorecard is already waiting or running.")
    monkeypatch.setattr(background, "submit_scorecard", fake_submit)
    response = client.post("/api/scorecards/run", json={"model": "connectome", "circuit": "fafb783-steering",
                                                        "dynamics": "spiking"})
    assert response.status_code == 202, response.text
    assert response.json()["job"]["kind"] == "scorecard"
    assert submitted[0][:5] == ("connectome", "toy", "fafb783-steering", "spiking",
                                "connectome-fafb783-steering-spiking-toy")
    assert client.post("/api/scorecards/run", json={"model": "connectome", "circuit": "no-such-circuit"}).status_code == 422
    assert client.post("/api/scorecards/run", json={"model": "fly"}).status_code == 422
    engineered = client.post("/api/scorecards/run", json={"model": "engineered"})
    assert engineered.status_code == 202 and submitted[-1][4] == "engineered-toy"


def test_the_real_job_command_names_the_model(monkeypatch):
    commands = []

    class Manager:
        def submit(self, kind, label, command, **kwargs):
            commands.append((kind, command, kwargs["target"]))
    background.submit_scorecard(Manager(), "connectome", "flygym", "fafb783-dna02", "spiking", key="k", label="L")
    kind, command, target = commands[0]
    assert kind == "scorecard" and target == "k"
    assert command[1:] == [str(ROOT / "scripts/toolkit.py"), "scorecard", "--model", "connectome", "--engine", "flygym",
                           "--progress", "--circuit", "fafb783-dna02", "--set", "dynamics=spiking"]
