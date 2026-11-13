"""Validation scorecard: score a model against published perturbation → behavior results.

Each test names its source and the published finding, the manipulation (done with the ordinary intervention
machinery: `Interventions.cell_types` on matched-seed closed-loop trials), what is measured and a pass / partial /
fail rule. The rules were written down before any model was scored and are part of the code (`TESTS`); changing one
changes SCORECARD_VERSION. A test whose cell types are missing from the circuit, or that the model has no cell types
for, is "not_testable"; a test that needs a sense or a motor program this fly lacks is "blocked". Either way it stays
listed, so the scorecard shows what is still out of reach.

    from digitalfly import scorecard
    card = scorecard.run(scorecard.Target("connectome", circuit="fafb783-steering"), engine="toy", seeds=[1, 2, 3])
    card["summary"], [(t["id"], t["status"], t["measured"]) for t in card["tests"]]

A pass is not biological validation. The body's motor interface (two descending drives, clipped at zero, into
FlyGym's walking controller) and every manipulation are engineered, and several tests can only pass or fail because
of how the readout is wired; those carry `by_construction` with the reason. Results describe these models.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import numpy as np
from digitalfly import toolkit
from typing import Literal
from digitalfly.api.models import (CellTypeIntervention, CircuitName, ConnectomeParameters, Interventions, RunConfig,
                                  Stimulus, StrictModel)

SCORECARD_VERSION = 1
ROOT = toolkit.ROOT
SCORECARD_DIR = ROOT / "runs/scorecards"
STATUSES = ("pass", "partial", "fail", "inconclusive", "not_testable", "blocked", "error")
WINDOW_S = .2  # measurements start here, after the onset transient
EARLY_END_S = 1.  # the symmetry test reads the first response, before reaching or circling a target dominates
# Rotational speed is read from heading changes over 0.25 s bins, three strides of FlyGym's 12 Hz walking rhythm, so the
# body's yaw wobble within each stride is not counted as turning. (Changed after the first FlyGym scores: see the
# research guide, "Validation scorecard".)
ROTATION_BIN_S = .25
ACTIVATION = {"rate": 1., "spiking": 150.}  # clamped rate; Poisson Hz (Shiu et al. 2024's input rate)
LATERAL = (45., -45., 90., -90.)  # target bearings, degrees, positive = left
DISTANCE_MM = 12.
DEFAULT_SEEDS = {"toy": [1, 2, 3], "flygym": [1, 2]}
DEFAULT_DURATION = {"toy": 3., "flygym": 2.}
# What the body can do: the motor interface is two descending drives (left and right legs) clipped to [0, 1.4]
# into FlyGym's hybrid turning controller. It walks forward and turns; it has no backward channel, no takeoff,
# no grooming program and no proboscis, and the only sense is vision (the target, or rendered eyes).
BODY_CAN = {"walk", "turn", "vision"}
CAPABILITY_TEXT = {
    "takeoff": "the body has no jump or takeoff motor program (FlyGym's walking controller only)",
    "grooming": "the body has no grooming motor program: the descending drive only scales the walking rhythm of "
                "each side, so the front legs cannot move on their own",
    "taste": "the fly has no taste input (gustatory receptor neurons get no stimulus)",
    "proboscis": "the body has no proboscis motor control",
}


@dataclass(frozen=True)
class Target:
    """What is scored: the engineered model, or the connectome model with a circuit, dynamics and other settings."""
    model: str = "connectome"
    circuit: str | None = None
    dynamics: str = "rate"
    settings: dict = field(default_factory=dict)  # further ConnectomeParameters fields

    def parameters(self) -> ConnectomeParameters:
        data = dict(self.settings)
        if self.circuit:
            data["circuit"] = self.circuit
        return ConnectomeParameters.model_validate({**data, "dynamics": self.dynamics})

    def key(self, engine: str) -> str:
        """The name of the latest scorecard file: one per model, circuit, dynamics, engine and settings."""
        if self.model == "engineered":
            return f"engineered-{engine}"
        p = self.parameters()
        extra = ""
        if self.settings:
            text = json.dumps(self.settings, sort_keys=True, default=str)
            extra = "-" + hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"connectome-{p.circuit}-{p.dynamics}-{engine}{extra}"



class ScorecardRequest(StrictModel):
    """POST /api/scorecards/run: score one model in a background job (default circuit for the connectome model)."""
    model: Literal["engineered", "connectome"] = "connectome"
    circuit: CircuitName | None = None
    dynamics: Literal["rate", "spiking"] = "rate"
    engine: Literal["toy", "flygym"] = "toy"

    def target(self) -> Target:
        if self.model == "engineered":
            return Target("engineered")
        return Target("connectome", circuit=self.circuit, dynamics=self.dynamics)

def _source(citation, doi, finding):
    return {"citation": citation, "doi": doi, "url": f"https://doi.org/{doi}", "finding": finding}


RAYSHUBSKIY = "Rayshubskiy A, Holtz SL, Bates A, et al., Wilson RI (2025). Neural circuit mechanisms for steering " \
              "control in walking Drosophila. eLife 13:RP102230"
UNILATERAL_RULE = ("pass: the ipsilateral shift is above 5 °/s for the left and for the right activation; partial: "
                   "their mean is above 5 °/s, or both are above 0; fail: otherwise.")
# Each test: what it needs (cell types as groups of accepted FlyWire names, each group needed; capabilities the body
# must have), how it is run and how it is scored. `kind` selects the plan and the scoring below.
TESTS = [
    {"id": "dna02_unilateral_activation", "kind": "unilateral", "cell_types": [["DNa02"]],
     "title": "DNa02 activation on one side → turning toward that side",
     "source": _source(RAYSHUBSKIY, "10.7554/eLife.102230",
                       "ReaChR expressed in DNa02 on one side: light evoked a small but significant steering bias "
                       "toward the side of the activated neuron, in flies walking on a ball (Fig. 8B, C)."),
     "manipulation": "In darkness (target intensity 0), DNa02 activated on the left, then on the right, for the whole "
                     "trial; matched-seed control trials without activation.",
     "measure": "Ipsilateral yaw-rate shift, °/s: mean yaw rate (from 0.2 s) with activation − control, signed "
                "positive toward the activated side; reported for each side and their mean.",
     "rule": UNILATERAL_RULE,
     "caveats": ["The fly effect was small; this rule tests its direction, not its size.",
                 "Activation clamps the rate (rate dynamics) or drives Poisson input (spiking), uncalibrated to ReaChR."]},
    {"id": "dna02_bilateral_silencing", "kind": "bilateral_silencing", "cell_types": [["DNa02"]],
     "title": "DNa02 silenced on both sides → rotational speed unchanged",
     "source": _source(RAYSHUBSKIY, "10.7554/eLife.102230",
                       "GtACR1 inhibition of both DNa02 neurons in freely walking flies left rotational speed "
                       "unchanged; only the fine structure of turns changed (Fig. 8D–H)."),
     "manipulation": "DNa02 silenced on both sides for the whole trial, with the target at 45° and 90° to either "
                     "side, 12 mm away; matched-seed control trials.",
     "measure": "Rotational-speed ratio: mean rotational speed silenced ÷ control, over all bearings and seeds; "
                "rotational speed is |heading change| over consecutive 0.25 s bins from 0.2 s (three strides, so the "
                "body's yaw wobble within a stride does not count as turning).",
     "rule": "pass: ratio 0.75–1.33; partial: 0.5–2; fail: otherwise. Inconclusive when the control turns slower than "
             "2 °/s.",
     "caveats": ["The flies turned spontaneously in an arena; here turning is driven by a visual target.",
                 "A circuit read out from DNa02 alone cannot turn without it, so it fails by construction."]},
    {"id": "dnp09_unilateral_activation", "kind": "unilateral", "cell_types": [["DNp09"]],
     "title": "DNp09 (P9) activation on one side → turning toward that side",
     "source": _source("Bidaye SS, Laturney M, Chang AK, et al., Scott K (2020). Two brain pathways initiate distinct "
                       "forward walking programs in Drosophila. Neuron 108:469–485", "10.1016/j.neuron.2020.07.032",
                       "Activating P9 (DNp09) drives forward walking with turning toward the activated side; "
                       "unilateral activation of a single P9 neuron initiates ipsilateral forward turns."),
     "manipulation": "As for DNa02: in darkness, DNp09 activated on the left, then on the right; matched controls.",
     "measure": "Ipsilateral yaw-rate shift, °/s, as for DNa02.",
     "rule": UNILATERAL_RULE,
     "caveats": ["P9 also starts forward walking from rest. The model walks at a tonic forward drive whatever P9 does, "
                 "so that half of the finding is not tested."]},
    {"id": "mdn_activation_backward", "kind": "backward", "cell_types": [["MDN"]],
     "title": "MDN activation → backward walking",
     "source": _source("Bidaye SS, Machacek C, Wu Y, Dickson BJ (2014). Neuronal control of Drosophila walking "
                       "direction. Science 344:97–101", "10.1126/science.1249964",
                       "Activating the moonwalker descending neurons (MDN) makes flies walk backward; silencing them "
                       "impairs backward walking."),
     "manipulation": "In darkness, MDN activated on both sides for the whole trial; matched-seed controls.",
     "measure": "Mean forward velocity along the body axis, mm/s (from 0.2 s); negative = backward.",
     "rule": "pass: below −0.5 mm/s (net backward walking); partial: at most half the control's forward velocity, "
             "not backward; fail: otherwise. Inconclusive when the control walks slower than 0.5 mm/s.",
     "caveats": ["The motor interface clips the descending drive at zero and has no backward channel, so this body "
                 "cannot walk backward: the best any brain can score here today is partial.",
                 "MDN is not a readout type, so only its connections inside the brain can change the motor command."]},
    {"id": "giant_fiber_takeoff", "kind": "listed", "cell_types": [["DNp01"]], "needs": ["takeoff"],
     "title": "Giant Fiber (DNp01) activation → escape takeoff",
     "source": _source("von Reyn CR, Breads P, Peek MY, et al., Card GM (2014). A spike-timing mechanism for action "
                       "selection. Nat Neurosci 17:962–970", "10.1038/nn.3741",
                       "Giant Fiber activity triggers the short-mode escape takeoff (wings stay folded, the middle "
                       "legs extend and the fly jumps)."),
     "manipulation": "Giant Fiber (FlyWire DNp01) activated on both sides.",
     "measure": "Takeoff posture: middle-leg extension and a jump.",
     "rule": "Not scored until the body has a takeoff motor program.",
     "caveats": []},
    {"id": "antennal_grooming", "kind": "listed", "cell_types": [["DNg62", "DNge078"]], "needs": ["grooming"],
     "title": "Antennal grooming descending neurons (aDN) → antennal grooming",
     "source": _source("Hampel S, Franconville R, Simpson JH, Seeds AM (2015). A neural command circuit for grooming "
                       "movement control. eLife 4:e08758", "10.7554/eLife.08758",
                       "Activating the antennal descending neurons aDN1 and aDN2 elicits antennal grooming by the "
                       "front legs. FlyWire names: aDN1 = DNg62 (Shiu et al. 2024), aDN2 = DNge078 (Virtual Fly "
                       "Brain)."),
     "manipulation": "aDN1 (DNg62) or aDN2 (DNge078) activated on both sides.",
     "measure": "Grooming-like front-leg movement relative to the other legs.",
     "rule": "Not scored until the body has a grooming motor program.",
     "caveats": []},
    {"id": "left_right_symmetry", "kind": "symmetry", "cell_types": [],
     "title": "Left-right symmetry: mirrored targets → mirrored turns",
     "source": _source("Buchanan SM, Kain JS, de Bivort BL (2015). Neuronal control of locomotor handedness in "
                       "Drosophila. PNAS 112:6700–6705", "10.1073/pnas.1500804112",
                       "Individual flies have idiosyncratic left or right turning biases, but the population is "
                       "unbiased on average."),
     "manipulation": "None: control trials with the target at 45° and 90° to the left and to the right, 12 mm away.",
     "measure": "Bias index from the mean yaw rate between 0.2 and 1 s: Σ(yaw(+b) + yaw(−b)) ÷ Σ(|yaw(+b)| + "
                "|yaw(−b)|) over bearings and seeds; positive = a leftward bias, 0 = mirror symmetric.",
     "rule": "pass: |index| ≤ 0.1; partial: ≤ 0.3; fail: above 0.3. Inconclusive when the model does not turn.",
     "caveats": ["A model stands for one fly, and single flies are allowed a handedness; a strong bias still means it "
                 "does not represent the average fly.",
                 "On the toy body each seed starts with a small heading offset, so a perfectly symmetric brain gives "
                 "an index slightly off 0."]},
    {"id": "sugar_grn_mn9", "kind": "listed", "cell_types": [], "needs": ["taste", "proboscis"],
     "title": "Sugar gustatory receptor neurons → MN9 (proboscis extension)",
     "source": _source("Shiu PK, Sterne GR, Spiller N, et al., Scott K (2024). A Drosophila computational brain model "
                       "reveals sensorimotor processing. Nature 634:210–219", "10.1038/s41586-024-07763-9",
                       "In the whole-brain LIF model, activating sugar GRNs activates the proboscis motor neuron MN9, "
                       "and the prediction held in flies (proboscis extension)."),
     "manipulation": "Sugar GRNs activated; MN9 activity and proboscis extension read out.",
     "measure": "MN9 firing and proboscis extension.",
     "rule": "Not scored until the fly has taste input and a proboscis (roadmap track G).",
     "caveats": []},
]
TEST_IDS = [t["id"] for t in TESTS]


def definitions() -> list[dict]:
    """The tests as published: everything but the internal plan fields."""
    return [{k: v for k, v in t.items() if k != "kind"} | {"needs": t.get("needs", [])} for t in TESTS]


# ---------------------------------------------------------------------------------------------------------------------
# Planning: which trials each test needs. A condition is (label, stimulus, interventions); identical conditions are
# shared between tests and run once per seed.

DARK = Stimulus(x=DISTANCE_MM, y=0, intensity=0)


def _lateral(bearing):
    return toolkit.target(bearing, DISTANCE_MM)


def _act(name, side, dynamics):
    return Interventions(cell_types=[CellTypeIntervention(name=name, side=side, mode="activate",
                                                          value=ACTIVATION[dynamics])])


def _resolve(test, data):
    """For each group of accepted names, the first one in the circuit; the groups with none, as text."""
    found, missing = [], []
    for group in test["cell_types"]:
        name = next((n for n in group if data is not None and n in data.type_members), None)
        (found.append(name) if name else missing.append(" or ".join(group)))
    return found, missing


def _readout(target: Target, data) -> list[str]:
    if target.model != "connectome":
        return []
    return list(target.parameters().readout_types or data.defaults["readout_types"])


def plan(test, target: Target, data) -> dict:
    """The test's verdict before any trial runs (not_testable or blocked, with the reasons), or its conditions."""
    lacking = [n for n in test.get("needs", []) if n not in BODY_CAN]
    reasons = []
    names = []
    if test["cell_types"]:
        if target.model != "connectome":
            reasons.append("the engineered model has six generic units and no identified cell types to manipulate")
        else:
            names, missing = _resolve(test, data)
            if missing:
                reasons.append(f"the {data.key} circuit has no {', '.join(missing)} neurons")
            if test["kind"] == "unilateral" and names:
                one_sided = [n for n in names if not (len(data.members(n, "left")) and len(data.members(n, "right")))]
                if one_sided:
                    reasons.append(f"{', '.join(one_sided)} lacks neurons on one side")
    if reasons:
        return {"status": "not_testable", "reasons": reasons + [CAPABILITY_TEXT[n] for n in lacking], "names": names}
    if lacking:
        return {"status": "blocked", "reasons": [CAPABILITY_TEXT[n] for n in lacking], "names": names}
    dynamics = target.dynamics if target.model == "connectome" else "rate"
    conditions = []
    if test["kind"] == "unilateral":
        name = names[0]
        conditions = [("dark", DARK, Interventions())] + [
            (f"dark, {name} {side} activated", DARK, _act(name, side, dynamics)) for side in ("left", "right")]
    elif test["kind"] == "bilateral_silencing":
        name = names[0]
        silenced = Interventions(cell_types=[CellTypeIntervention(name=name, side="both", mode="silence")])
        for bearing in LATERAL:
            conditions += [(f"target {bearing:+g}°", _lateral(bearing), Interventions()),
                           (f"target {bearing:+g}°, {name} silenced", _lateral(bearing), silenced)]
    elif test["kind"] == "backward":
        name = names[0]
        conditions = [("dark", DARK, Interventions()), (f"dark, {name} activated", DARK, _act(name, "both", dynamics))]
    elif test["kind"] == "symmetry":
        conditions = [(f"target {b:+g}°", _lateral(b), Interventions()) for b in LATERAL]
    return {"status": "planned", "conditions": conditions, "names": names}


def _config(target: Target, engine: str, seed: int, stimulus: Stimulus, interventions: Interventions) -> RunConfig:
    settings = {"engine": engine, "seed": seed, "stimulus": stimulus, "initial_interventions": interventions,
                "neural_model": target.model}
    if target.model == "connectome":
        settings["connectome_parameters"] = target.parameters()
    return toolkit.configure(**settings)


# ---------------------------------------------------------------------------------------------------------------------
# Measuring: per-trial metrics from the trajectory (one sample per 10 ms control step).

def trial_metrics(trajectory, window_s: float = WINDOW_S, early_end_s: float = EARLY_END_S,
                  rotation_bin_s: float = ROTATION_BIN_S) -> dict:
    """Yaw rate (°/s, positive = left), rotational speed and forward velocity along the body axis (mm/s) from a
    trajectory of [t, x, y, yaw] rows, over t > window_s; `early_yaw_rate_deg_s` stops at early_end_s.
    Rotational speed is the mean |heading change| ÷ rotation_bin_s over consecutive bins from window_s: FlyGym's body
    yaws back and forth with every stride (12 Hz), and 10 ms yaw rates would count that wobble as turning."""
    data = np.asarray(trajectory, dtype=np.float64)
    if len(data) < 3:
        raise ValueError("The trial is too short to measure.")
    t, x, y = data[:, 0], data[:, 1], data[:, 2]
    yaw = np.unwrap(data[:, 3])
    dt = np.diff(t)
    rate = np.degrees(np.diff(yaw) / dt)
    middle = (yaw[1:] + yaw[:-1]) / 2
    forward = (np.diff(x) * np.cos(middle) + np.diff(y) * np.sin(middle)) / dt
    end = t[1:]
    late, early = end > window_s + 1e-9, (end > window_s + 1e-9) & (end <= early_end_s + 1e-9)
    if not late.any():
        raise ValueError(f"The trial ends before the measurement window starts at {window_s:g} s.")
    first = int(np.searchsorted(t, window_s - 1e-9))  # the sample at the window's start
    step = max(1, round(rotation_bin_s / float(np.median(dt))))
    marks = np.arange(first, len(t), step)
    if len(marks) < 2:
        raise ValueError(f"The trial is shorter than one {rotation_bin_s:g} s rotation bin after {window_s:g} s.")
    rotation = np.degrees(np.abs(np.diff(yaw[marks])) / np.diff(t[marks]))
    return {"yaw_rate_deg_s": float(rate[late].mean()), "rotational_speed_deg_s": float(rotation.mean()),
            "forward_velocity_mm_s": float(forward[late].mean()),
            "early_yaw_rate_deg_s": float(rate[early].mean()) if early.any() else None}


# ---------------------------------------------------------------------------------------------------------------------
# Scoring, with the rules in TESTS.

def _by_seed(trials, label):
    return {r["seed"]: r for r in trials if r["condition"] == label}


def _unilateral(test, names, trials):
    name = names[0]
    control = _by_seed(trials, "dark")
    shifts = {}
    for side, sign in (("left", 1), ("right", -1)):
        manipulated = _by_seed(trials, f"dark, {name} {side} activated")
        pairs = [sign * (manipulated[s]["yaw_rate_deg_s"] - control[s]["yaw_rate_deg_s"]) for s in manipulated if s in control]
        shifts[side] = float(np.mean(pairs))
    mean = (shifts["left"] + shifts["right"]) / 2
    if shifts["left"] > 5 and shifts["right"] > 5:
        status = "pass"
    elif mean > 5 or (shifts["left"] > 0 and shifts["right"] > 0):
        status = "partial"
    else:
        status = "fail"
    return status, {"value": mean, "unit": "°/s toward the activated side",
                    "text": f"{mean:+.1f} °/s ipsilateral (left activation {shifts['left']:+.1f}, right {shifts['right']:+.1f})",
                    "left_deg_s": shifts["left"], "right_deg_s": shifts["right"],
                    "control_yaw_rate_deg_s": float(np.mean([r["yaw_rate_deg_s"] for r in control.values()]))}


def _bilateral_silencing(test, names, trials):
    name = names[0]
    control = [r["rotational_speed_deg_s"] for r in trials if "silenced" not in r["condition"]]
    silenced = [r["rotational_speed_deg_s"] for r in trials if r["condition"].endswith(f"{name} silenced")]
    base, after = float(np.mean(control)), float(np.mean(silenced))
    measured = {"unit": "silenced ÷ control rotational speed", "control_deg_s": base, "silenced_deg_s": after}
    if base < 2:
        return "inconclusive", {**measured, "value": None,
                                "text": f"control turns at only {base:.1f} °/s, so there is no turning to preserve"}
    ratio = after / base
    status = "pass" if .75 <= ratio <= 1.33 else "partial" if .5 <= ratio <= 2 else "fail"
    return status, {**measured, "value": ratio,
                    "text": f"ratio {ratio:.2f} ({after:.1f} °/s silenced vs {base:.1f} °/s control)"}


def _backward(test, names, trials):
    name = names[0]
    control = float(np.mean([r["forward_velocity_mm_s"] for r in trials if r["condition"] == "dark"]))
    active = float(np.mean([r["forward_velocity_mm_s"] for r in trials if r["condition"] == f"dark, {name} activated"]))
    measured = {"value": active, "unit": "mm/s forward (negative = backward)", "control_mm_s": control}
    if control < .5:
        return "inconclusive", {**measured, "text": f"the control walks at only {control:.2f} mm/s"}
    status = "pass" if active < -.5 else "partial" if active <= .5 * control else "fail"
    return status, {**measured, "text": f"{active:+.2f} mm/s with MDN activated vs {control:+.2f} mm/s control"}


def _symmetry(test, names, trials):
    rows = {(r["seed"], round(r["target_bearing_deg"])): r["early_yaw_rate_deg_s"] for r in trials}
    total = size = 0.
    for (seed, bearing), value in rows.items():
        if bearing > 0 and (seed, -bearing) in rows:
            total += value + rows[(seed, -bearing)]
            size += abs(value) + abs(rows[(seed, -bearing)])
    if size < 1e-9:
        return "inconclusive", {"value": None, "unit": "bias index", "text": "the model does not turn"}
    index = total / size
    status = "pass" if abs(index) <= .1 else "partial" if abs(index) <= .3 else "fail"
    side = "leftward" if index > 0 else "rightward"
    return status, {"value": index, "unit": "bias index (positive = leftward)",
                    "text": f"bias index {index:+.2f} ({side})" if abs(index) > .005 else f"bias index {index:+.3f}"}


SCORERS = {"unilateral": _unilateral, "bilateral_silencing": _bilateral_silencing, "backward": _backward,
           "symmetry": _symmetry}


def by_construction(test, target: Target, names, readout) -> str | None:
    """Why a result follows from the engineered readout or weights rather than from the wiring, or None."""
    if target.model == "engineered" and test["kind"] == "symmetry":
        return "The engineered model's weights are mirror symmetric by design."
    if target.model != "connectome" or not names:
        return None
    if test["kind"] == "unilateral" and names[0] in readout:
        return (f"{names[0]} is a readout type: the engineered motor mapping turns the fly toward the side whose "
                "readout is more active, so activating it on one side turns the fly that way whatever the wiring.")
    if test["kind"] == "bilateral_silencing" and set(readout) <= {names[0]}:
        return (f"Turning is read only from {names[0]}, so silencing it removes every turn command whatever the "
                "wiring.")
    return None


# ---------------------------------------------------------------------------------------------------------------------

def run(target: Target, engine: str = "toy", seeds=None, duration_s: float | None = None, workers: int = 1,
        tests=None, on_progress=None) -> dict:
    """Score `target` on `engine`: plan every test, run the trials they need once each (matched seeds), score them.
    `tests` limits the run to some test ids; `on_progress(done, total)` follows the trials."""
    if target.model not in ("engineered", "connectome"):
        raise ValueError("Choose the engineered or the connectome model.")
    if engine not in DEFAULT_SEEDS:
        raise ValueError("Choose the toy or the flygym engine.")
    seeds = list(seeds or DEFAULT_SEEDS[engine])
    duration_s = float(duration_s or DEFAULT_DURATION[engine])
    if duration_s <= EARLY_END_S:
        raise ValueError(f"Trials must last longer than {EARLY_END_S:g} s, the end of the symmetry window.")
    unknown = sorted(set(tests or []) - set(TEST_IDS))
    if unknown:
        raise ValueError(f"No scorecard test {', '.join(unknown)}; the tests are {', '.join(TEST_IDS)}.")
    chosen = [t for t in TESTS if not tests or t["id"] in tests]
    data = None
    if target.model == "connectome":
        from digitalfly.neural.connectome import load_circuit
        data = target.parameters().check_against_circuit(load_circuit(target.parameters().circuit))
    readout = _readout(target, data)
    plans = {t["id"]: plan(t, target, data) for t in chosen}
    conditions = {}  # label → (stimulus, interventions); tests that share a condition share its trials
    for p in plans.values():
        for label, stimulus, interventions in p.get("conditions", []):
            conditions.setdefault(label, (stimulus, interventions))
    tasks = [(label, seed) for label in conditions for seed in seeds]
    configs = [_config(target, engine, seed, *conditions[label]) for label, seed in tasks]
    done = [0]

    def finished(index, row):
        done[0] += 1
        if on_progress:
            on_progress(done[0], len(configs))
    rows = toolkit.run_trials(configs, workers=workers, on_result=finished, duration_s=duration_s, trajectory_every=1)
    trials = []
    for (label, seed), row in zip(tasks, rows):
        item = {"condition": label, "seed": seed, "target_bearing_deg": row.get("target_bearing_deg"),
                "error": row.get("error"), "config_hash": row.get("config_hash")}
        if not row.get("error"):
            try:
                item.update(trial_metrics(row["trajectory"]))
                item["mean_speed_mm_s"] = row.get("mean_speed_mm_s")
                if "motor_clipped_fraction" in row:
                    item["motor_clipped_fraction"] = row["motor_clipped_fraction"]
            except (KeyError, ValueError) as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
        trials.append(item)
    results = []
    for test in chosen:
        p = plans[test["id"]]
        entry = {"id": test["id"], "title": test["title"], "source": test["source"], "rule": test["rule"],
                 "cell_types": p["names"], "measured": None, "reasons": p.get("reasons", []),
                 "by_construction": by_construction(test, target, p["names"], readout), "caveats": test["caveats"]}
        if p["status"] != "planned":
            results.append({**entry, "status": p["status"], "by_construction": None})
            continue
        own = [t for t in trials if t["condition"] in {c[0] for c in p["conditions"]}]
        failed = [t for t in own if t["error"]]
        if failed:
            results.append({**entry, "status": "error", "reasons": [f"{len(failed)} of {len(own)} trials failed: "
                                                                     f"{failed[0]['error']}"]})
            continue
        status, measured = SCORERS[test["kind"]](test, p["names"], own)
        if test["kind"] == "symmetry" and target.model == "connectome":
            # Not scored: the open-loop turn command with both sensors at 0.5, as `toolkit.py bias` reports it.
            spiking = target.dynamics == "spiking"
            measured["open_loop_equal_input_turn"] = toolkit.hold(target.parameters(), .5, .5, ms=500, seed=seeds[0],
                                                                  average_ms=200 if spiking else 0)["turn"]
            measured["open_loop_note"] = ("Turn command with both sensors held at 0.5 for 500 ms (positive = rightward), "
                                          "for comparison with the research guide's bias tables; not scored.")
        results.append({**entry, "status": status, "measured": measured, "trials": len(own)})
    counts = {s: sum(r["status"] == s for r in results) for s in STATUSES}
    scored = counts["pass"] + counts["partial"] + counts["fail"]
    p = target.parameters() if target.model == "connectome" else None
    return {"format": "digitalfly-scorecard", "version": SCORECARD_VERSION, "key": target.key(engine),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": {"neural_model": target.model, "circuit": p.circuit if p else None,
                      "dynamics": p.dynamics if p else None, "readout_types": readout,
                      "settings": dict(target.settings), "label": label_for(target)},
            "engine": engine, "seeds": seeds, "duration_s": duration_s,
            "summary": {**counts, "scored": scored,
                        "text": f"{counts['pass']} pass, {counts['partial']} partial, {counts['fail']} fail of {scored} "
                                f"scored; {counts['not_testable']} not testable, {counts['blocked']} blocked"
                                + (f", {counts['inconclusive']} inconclusive" if counts["inconclusive"] else "")
                                + (f", {counts['error']} failed to run" if counts["error"] else "")},
            "tests": results, "trials": trials,
            "methods": {"window_s": WINDOW_S, "symmetry_window_s": [WINDOW_S, EARLY_END_S],
                        "rotation_bin_s": ROTATION_BIN_S,
                        "activation": ACTIVATION if target.model == "connectome" else None,
                        "target_distance_mm": DISTANCE_MM, "lateral_bearings_deg": list(LATERAL),
                        "darkness": "target intensity 0",
                        "yaw_sign": "positive = leftward (counter-clockwise)",
                        "note": "Scores describe this model and body, not fly biology. Every manipulation and the "
                                "motor interface are engineered."}}


def label_for(target: Target) -> str:
    if target.model == "engineered":
        return "Engineered six-unit model"
    p = target.parameters()
    return f"{p.circuit} · {p.dynamics}" + (" · custom settings" if target.settings else "")


# ---------------------------------------------------------------------------------------------------------------------
# Storage: the latest scorecard per model, in runs/scorecards/<key>.json (ignored by git), read by the app.

KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


def publish(card: dict, folder: Path | None = None) -> Path:
    """Write the card as the latest for its key (in SCORECARD_DIR unless `folder` is given), through a hidden file
    renamed into place."""
    folder = Path(folder or SCORECARD_DIR)
    if not KEY.fullmatch(card["key"]):
        raise ValueError(f"Not a scorecard name: {card['key']!r}.")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{card['key']}.json"
    partial = folder / f".{card['key']}.{uuid.uuid4().hex}.part"
    with partial.open("x") as handle:
        handle.write(json.dumps(card, indent=1, default=str))
    os.replace(partial, path)
    return path


def latest(folder: Path | None = None) -> list[dict]:
    """The latest scorecard of each model, without per-trial rows, newest first. Unreadable files are skipped."""
    folder, cards = Path(folder or SCORECARD_DIR), []
    if not folder.is_dir() or folder.is_symlink():
        return cards
    for path in folder.glob("*.json"):
        if path.is_symlink() or not KEY.fullmatch(path.stem):
            continue
        try:
            card = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(card, dict) and card.get("format") == "digitalfly-scorecard":
            cards.append({k: v for k, v in card.items() if k != "trials"} | {"trial_count": len(card.get("trials", []))})
    return sorted(cards, key=lambda c: str(c.get("created")), reverse=True)


def markdown(card: dict) -> str:
    """The scorecard as a Markdown table."""
    symbols = {"pass": "✓ pass", "partial": "◐ partial", "fail": "✗ fail", "inconclusive": "? inconclusive",
               "not_testable": "– not testable", "blocked": "⊘ blocked", "error": "! error"}
    lines = [f"Scorecard for {card['model']['label']} on the {card['engine']} body "
             f"({len(card['seeds'])} seeds, {card['duration_s']:g} s trials): {card['summary']['text']}.", "",
             "| Test | Result | Measured | Source |", "| --- | --- | --- | --- |"]
    for t in card["tests"]:
        measured = t["measured"]["text"] if t["measured"] else "; ".join(t["reasons"])
        if t.get("by_construction"):
            measured += " (by construction)"
        lines.append(f"| {t['title']} | {symbols[t['status']]} | {measured} | {t['source']['citation'].split(').')[0]}) |")
    lines.append("")
    lines.append("Results describe this model and body, not fly biology; see each test's rule and caveats in the JSON.")
    return "\n".join(lines)
