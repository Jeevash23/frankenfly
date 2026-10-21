"""Connectome-constrained models on FlyWire circuits, with rate or spiking dynamics.

What each part is:
  data-derived  neurons, cell types, sides, predicted transmitters and synapse counts from
                FlyWire FAFB v783 (data/circuits/, built by scripts/build_circuit.py)
  assumed       signs: acetylcholine excitatory; GABA and glutamate inhibitory (as in Shiu et al. 2024);
                dopamine, serotonin, octopamine and unknown transmitters excluded unless switched on
  engineered    the dynamics' global gains; which populations receive the sensors, read out turning
                and (optionally) set walking speed; forward drive as a tonic term; the motor path

Rate dynamics, an Euler update every 1 ms for every neuron i:
  r_i += dt/tau × (clip(sum_j W_ij r_j + input_i, 0, 1) − r_i),  W_ij = sign(j) × synapses(j → i) × global_gain
Spiking dynamics: the leaky integrate-and-fire model and parameters of Shiu et al. 2024, stepped at 0.1 ms.
Interventions (engineered manipulations, docs/ARCHITECTURE.md): silenced neurons are clamped to rest and send nothing;
a scaled neuron sends s × its activity, to its targets and to the readout; an activated neuron's rate is clamped to the
value (rate) or it gets independent Poisson input at the value in Hz, with no refractory period (spiking).
Turning: turn = output gain × Σ_types w_type × (mean right − mean left) over the readout types (w = 1 unless
set; "mean" pooling divides by the number of types). A more active right DNa02 turns the fly right
(Rayshubskiy et al. 2025); FlyGym's HybridTurningController turns right when the left legs' amplitude exceeds
the right's. Motor: the command [forward + turn, forward − turn] passes an optional delay line and first-order
low-pass, updated every neural step (both off by default), then motor = 1.4 × clip(command, 0, 1).
"""
import hashlib
import io
import json
import math
import re
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
import numpy as np
from scipy import sparse
from digitalfly.api.models import ConnectomeParameters, Interventions, SensorState

ROOT = Path(__file__).resolve().parents[4]
CIRCUIT_DIR = ROOT / "data/circuits"
LOCAL_DIR = CIRCUIT_DIR / "local"
DEFAULT_CIRCUIT = "fafb783-dna02"
CIRCUIT_PATH = CIRCUIT_DIR / f"{DEFAULT_CIRCUIT}.json"
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
INPUT_SUPER_CLASS = "visual_projection"
CLASSIC_SIGNS = {"acetylcholine": 1, "gaba": -1, "glutamate": -1}
OTHER_TRANSMITTERS = ("dopamine", "serotonin", "octopamine", "unknown")
MOTOR_SCALE = 1.4  # Same descending-to-amplitude scale as the engineered model.
TRACE_TYPES = 5
DISPLAY_TYPES = 1500  # larger circuits show the types nearest the readout in the circuit view
# Shiu et al. 2024 (Methods and model.py): leaky integrate-and-fire neurons with alpha synapses.
LIF = {"v_rest_mv": -52.0, "v_reset_mv": -52.0, "v_threshold_mv": -45.0, "tau_membrane_ms": 20.0,
       "tau_synapse_ms": 5.0, "refractory_ms": 2.2, "delay_ms": 1.8, "poisson_scale": 250, "dt_ms": 0.1}


def circuit_path(name: str) -> Path:
    """Committed circuits first, then local ones; only plain files inside the two folders."""
    if not NAME_PATTERN.fullmatch(name) or name == "local" or name.endswith(".flyvis"):
        raise ValueError(f"{name!r} is not a valid circuit name.")
    for folder in (CIRCUIT_DIR, LOCAL_DIR):
        for suffix in (".json", ".npz"):
            path = folder / f"{name}{suffix}"
            if path.is_file() and not path.is_symlink():
                return path
    raise FileNotFoundError(f"There is no circuit named {name}. Build it with scripts/build_circuit.py.")


def _read(path: Path):
    raw = path.read_bytes()
    if path.suffix == ".npz":
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
        header = json.loads(str(arrays.pop("header")))
        neurons = {key.removeprefix("neuron_"): value for key, value in arrays.items() if key.startswith("neuron_")}
        neurons["id"] = arrays["neuron_id"]
        edges = {"pre": arrays["edge_pre"], "post": arrays["edge_post"], "synapses": arrays["edge_synapses"]}
        return raw, header, neurons, edges
    data = json.loads(raw)
    return raw, data, data["neurons"], data["edges"]


def _describe(path: Path, raw: bytes, header: dict) -> dict:
    """What the circuit list shows, from the file's header alone."""
    prov = header["provenance"]
    build, counts = prov.get("build", {}), prov.get("counts", {})
    if header["version"] == 1:
        seeds, readout = ["DNa02"], ["DNa02"]
    else:
        seeds, readout = [s["seed"] for s in prov["seeds"]], header["defaults"]["readout_types"]
    return {"name": path.stem, "title": header["name"], "committed": path.parent == CIRCUIT_DIR,
            "format": path.suffix[1:], "version": header["version"], "neurons": counts.get("neurons"),
            "connections": counts.get("connections"), "cell_types": counts.get("cell_types"),
            "seeds": seeds, "readout_types": readout,
            "build": {**{k: build.get(k) for k in ["synapse_threshold", "hops", "neuron_cap", "whole_brain", "seeds"]},
                      "balance_sides": bool(build.get("balance_sides"))},  # absent before v0.6 and in unbalanced builds
            "coverage": prov.get("coverage"), "license": prov.get("license"), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


@lru_cache(maxsize=64)
def _info(path: str, mtime_ns: int) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == ".npz":
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            header = json.loads(str(archive["header"]))
    else:
        header = json.loads(raw)
    if header.get("format") != "digitalfly-circuit" or header.get("version") not in (1, 2):
        raise ValueError(f"{path.name} is not a DigitalFly circuit file.")
    return _describe(path, raw, header)


def _whole(values, field: str, size: int | None = None) -> np.ndarray:
    """A list of whole numbers, each an index below `size` when given, or a ValueError naming the field."""
    array = np.asarray(values)
    if array.ndim != 1 or (array.size and array.dtype.kind not in "iu"):
        raise ValueError(f"Circuit field {field} must be a list of whole numbers.")
    if size is not None and array.size and (array.min() < 0 or array.max() >= size):
        bad = int(array[(array < 0) | (array >= size)][0])
        raise ValueError(f"Circuit field {field} has index {bad}, outside the {size} entries it refers to.")
    return array.astype(np.int64)


class CircuitData:
    """One circuit file (format 1 or 2, JSON or NumPy), validated once and shared by every model."""

    def __init__(self, path: Path):
        try:
            self._load(path)
        except KeyError as exc:  # a hand-made or truncated file: a validation error, not a crash
            raise ValueError(f"{path.name} lacks the circuit field {exc}.") from exc

    def _load(self, path: Path):
        raw, header, neurons, edges = _read(path)
        if header.get("format") != "digitalfly-circuit" or header.get("version") not in (1, 2):
            raise ValueError(f"{path.name} is not a DigitalFly circuit file.")
        self.path = path
        self.info = _describe(path, raw, header)
        self.sha256 = self.info["sha256"]
        self.bytes = len(raw)
        self.version = header["version"]
        self.name = header["name"]
        self.key = path.stem
        self.provenance = header["provenance"]
        lookups = header["lookups"]
        self.ids = [str(i) for i in np.asarray(neurons["id"]).tolist()]
        n = len(self.ids)
        if len(set(self.ids)) != n:
            raise ValueError("Circuit neuron IDs must be unique.")
        for key in ["cell_type", "super_class", "cell_class", "transmitter", "side", "hop"]:
            if len(neurons[key]) != n:
                raise ValueError(f"Circuit field {key} has {len(neurons[key])} entries for {n} neurons.")
        # Every lookup column must index its table: an out-of-range or negative index would otherwise wrap or crash later.
        column = {key: _whole(neurons[key], key, len(lookups[key]))
                  for key in ["cell_type", "super_class", "cell_class", "transmitter", "side"]}
        self.type_names = list(lookups["cell_type"])
        self.type_index = column["cell_type"]
        self.super_class = np.asarray(lookups["super_class"], dtype=object)[column["super_class"]]
        self.cell_class = np.asarray(lookups["cell_class"], dtype=object)[column["cell_class"]]
        self.transmitter = np.asarray(lookups["transmitter"], dtype=object)[column["transmitter"]]
        self.side = np.asarray(lookups["side"], dtype=object)[column["side"]]
        self.hop = _whole(neurons["hop"], "hop")
        self.pre = _whole(edges["pre"], "edge pre", n)
        self.post = _whole(edges["post"], "edge post", n)
        self.synapses = np.asarray(edges["synapses"], dtype=np.float64)
        if self.synapses.ndim != 1 or not (len(self.pre) == len(self.post) == len(self.synapses)):
            raise ValueError("Circuit edge arrays differ in length.")
        if not np.isfinite(self.synapses).all() or (self.synapses < 1).any():
            raise ValueError("Circuit synapse counts must be positive.")
        if self.version == 1:  # v0.3 files describe one DNa02 pair
            dna02 = self.provenance["dna02"]
            self.seeds = [{"seed": "DNa02", "cell_types": ["DNa02"], "left": [dna02["left"]],
                           "right": [dna02["right"]], "other": []}]
            self.defaults = {"readout_types": ["DNa02"], "input": INPUT_SUPER_CLASS}
        else:
            self.seeds = self.provenance["seeds"]
            self.defaults = header["defaults"]
        self.type_counts = np.bincount(self.type_index, minlength=len(self.type_names))
        order = np.argsort(self.type_index, kind="stable")
        bounds = np.searchsorted(self.type_index[order], np.arange(len(self.type_names) + 1))
        self.type_members = {name: order[bounds[i]:bounds[i + 1]] for i, name in enumerate(self.type_names)}
        self.build_threshold = int(self.provenance.get("build", {}).get("synapse_threshold", 5))

    def members(self, cell_type: str, side: str | None = None) -> np.ndarray:
        if cell_type not in self.type_members:
            raise ValueError(f"{cell_type} is not a cell type in the {self.key} circuit.")
        members = self.type_members[cell_type]
        return members if side is None else members[self.side[members] == side]

    def summary(self) -> dict:
        return {**self.info, "neurons": len(self.ids), "connections": int(len(self.synapses)),
                "cell_types": len(self.type_names)}


@lru_cache(maxsize=3)
def _load(path: str, mtime_ns: int) -> CircuitData:
    return CircuitData(Path(path))


def load_circuit(circuit: str | Path = DEFAULT_CIRCUIT) -> CircuitData:
    path = circuit if isinstance(circuit, Path) else circuit_path(circuit)
    if not path.is_file():
        raise FileNotFoundError("The connectome circuit file is missing. Rebuild it with scripts/build_circuit.py.")
    return _load(str(path), path.stat().st_mtime_ns)


def list_circuits() -> list[dict]:
    """Every circuit the app can load by name: committed ones, then locally built ones."""
    result, seen = [], set()
    for folder in (CIRCUIT_DIR, LOCAL_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix in {".json", ".npz"} and NAME_PATTERN.fullmatch(path.stem) and path.name != "downloads.json" \
                    and path.stem != "local" and not path.stem.endswith(".flyvis") and path.stem not in seen \
                    and path.is_file() and not path.is_symlink():
                seen.add(path.stem)
                try:
                    result.append(_info(str(path), path.stat().st_mtime_ns))
                except (OSError, ValueError, KeyError) as exc:
                    result.append({"name": path.stem, "error": f"{type(exc).__name__}: {exc}"})
    return result


def bridge_path(data: "CircuitData") -> Path:
    """Where a circuit's FlyVis bridge lives: next to the circuit file (scripts/build_circuit.py flyvis-bridge)."""
    return data.path.with_name(f"{data.path.stem}.flyvis.json")


@lru_cache(maxsize=4)
def _bridge(path: str, mtime_ns: int, circuit_sha256: str, n: int):
    raw = json.loads(Path(path).read_text())
    if raw.get("format") != "digitalfly-flyvis-bridge" or raw.get("circuit_sha256") != circuit_sha256:
        raise ValueError(f"{Path(path).name} does not belong to this version of the circuit; rebuild it.")
    e = raw["entries"]
    columns = np.asarray(e["eye"], dtype=np.int64) * len(raw["flyvis"]["types"]) + np.asarray(e["type"], dtype=np.int64)
    matrix = sparse.csr_matrix((np.asarray(e["weight"], dtype=np.float64), (np.asarray(raw["neurons"])[e["neuron"]], columns)),
                               shape=(n, 2 * len(raw["flyvis"]["types"])))
    return matrix, raw["flyvis"]["types"]


def load_bridge(data: "CircuitData"):
    """(sparse weights from FlyVis eye × type responses to neurons, FlyVis type names) for a circuit."""
    path = bridge_path(data)
    if not path.is_file():
        raise FileNotFoundError(f"The {data.key} circuit has no FlyVis bridge. Build it with: "
                                f"backend/.venv/bin/python scripts/build_circuit.py flyvis-bridge --circuit {data.key}")
    return _bridge(str(path), path.stat().st_mtime_ns, data.sha256, len(data.ids))


def known_cell_types(circuit: str = DEFAULT_CIRCUIT) -> set[str]:
    return set(load_circuit(circuit).type_names)


def transmitter_signs(data: CircuitData, other_transmitters: str) -> np.ndarray:
    other = 1 if other_transmitters == "excitatory" else 0
    return np.array([CLASSIC_SIGNS.get(nt, other) for nt in data.transmitter], dtype=np.float64)


def input_population(data: CircuitData, input_types: list[str] | None) -> tuple[np.ndarray, np.ndarray]:
    """Left and right sensor-input neurons: the named cell types, or every visual projection neuron."""
    if input_types is None:
        visual = data.super_class == INPUT_SUPER_CLASS
        return np.flatnonzero(visual & (data.side == "left")), np.flatnonzero(visual & (data.side == "right"))
    return tuple(np.unique(np.concatenate([data.members(t, side) for t in input_types])) for side in ("left", "right"))


def check_flyvis_inputs(data: CircuitData, input_types: list[str] | None = None):
    """Raise ValueError unless the circuit's FlyVis bridge reaches input neurons on both sides. Bridges feed visual
    projection neurons only, so FlyVis eyes on other input types would leave the circuit without input."""
    fed = load_bridge(data)[0].getnnz(axis=1) > 0
    blind = [side for side, members in zip(("left", "right"), input_population(data, input_types)) if not fed[members].any()]
    if blind:
        raise ValueError(f"FlyVis eyes reach no sensor-input neuron on the {' or '.join(blind)} side of the {data.key} "
                         "circuit: its FlyVis bridge feeds visual projection neurons only. Choose visual projection "
                         "cell types as the sensor input, or another sensor model.")


class Manipulation(NamedTuple):
    """What one set of interventions does to a circuit's neurons (ConnectomeCircuit.manipulation)."""
    silenced: np.ndarray  # neuron indices held at rest, sending nothing
    scaled: np.ndarray  # neuron indices whose output is scaled
    scale: np.ndarray | None  # output factor per neuron (1 elsewhere); None when nothing is scaled
    activated: np.ndarray  # neuron indices activated
    activation: np.ndarray  # per activated neuron: the clamped rate (rate dynamics) or a Poisson rate in Hz (spiking)
    items: list  # each intervention, described for the run's provenance


class SpikingState:
    """Leaky integrate-and-fire network after Shiu et al. 2024, stepped at 0.1 ms (forward Euler).

    dv/dt = (v_rest − v + g) / tau_m and dg/dt = −g / tau_s, both frozen while refractory. A spike
    resets v and g and, 1.8 ms later, adds sign × synapses × w_syn to g of each target. Input
    neurons receive Poisson spikes that add 250 × w_syn to v and have no refractory period.
    Each substep follows Brian2's schedule, which Shiu et al.'s code runs on: state update,
    threshold, delayed synaptic and Poisson input, reset. A neuron that spiked at step s is
    frozen until step s + 22 (Brian2: timestep(t − lastspike) ≥ timestep(refractory)).
    """

    def __init__(self, data: CircuitData, active: np.ndarray, signs: np.ndarray, parameters: ConnectomeParameters,
                 inputs: tuple[np.ndarray, np.ndarray]):
        n = len(data.ids)
        self.data, self.n, self.inputs = data, n, inputs
        dt = LIF["dt_ms"]
        self.substeps = round(1 / dt)
        self.delay = round(LIF["delay_ms"] / dt)
        self.slots = self.delay + 1
        self.refractory = np.full(n, round(LIF["refractory_ms"] / dt), dtype=np.int64)
        for side in inputs:
            self.refractory[side] = 0  # as for Poisson targets in Shiu et al.'s code
        self.base_refractory = self.refractory
        self.decay_membrane, self.decay_synapse = dt / LIF["tau_membrane_ms"], dt / LIF["tau_synapse_ms"]
        # Interventions (see manipulate): none until the circuit applies some.
        self.manipulation, self.scale, self.scaled_weights = None, None, None
        self.activated, self.activation_chance = np.array([], dtype=np.int64), np.array([])
        self.configure(active, signs, parameters)
        self.reset(0)

    def configure(self, active: np.ndarray, signs: np.ndarray, parameters: ConnectomeParameters):
        """Weights and parameter-dependent constants. Keeps v, g, the delay queue, rates, the step count and the
        random generator, so a live parameter edit continues the run; spikes already queued keep their weights."""
        p, data, n = parameters.spiking, self.data, self.n
        weights = signs[data.pre[active]] * data.synapses[active] * p.synapse_weight_mv
        matrix = sparse.csc_matrix((weights, (data.post[active], data.pre[active])), shape=(n, n))
        matrix.sum_duplicates()
        self.indptr, self.indices, self.weights = matrix.indptr, matrix.indices, matrix.data
        self.parameters = parameters
        self.kick = LIF["poisson_scale"] * p.synapse_weight_mv
        self.rate_decay = math.exp(-LIF["dt_ms"] / p.rate_window_ms)
        self.rate_jump = 1000 / p.rate_window_ms  # Hz added per spike, so a steady f Hz train averages f
        self._scale_weights()

    def manipulate(self, manipulation: "Manipulation"):
        """Interventions from the next substep: each neuron's spikes deliver scale × its weights, and activated
        neurons receive independent Poisson input at their rate in Hz, each event adding the sensor input's kick
        (250 × w_syn) to v, with no refractory period (as Poisson targets in Shiu et al.'s code)."""
        if manipulation is self.manipulation:
            return
        self.manipulation, self.scale, self.activated = manipulation, manipulation.scale, manipulation.activated
        self.activation_chance = np.minimum(1., manipulation.activation * LIF["dt_ms"] / 1000)
        self.refractory = self.base_refractory
        if len(self.activated):
            self.refractory = self.base_refractory.copy()
            self.refractory[self.activated] = 0
        self._scale_weights()

    def _scale_weights(self):
        if self.scale is None:
            self.scaled_weights = None
        else:  # CSC columns are presynaptic neurons
            self.scaled_weights = self.weights * self.scale[np.repeat(np.arange(self.n), np.diff(self.indptr))]

    def reset(self, seed: int):
        self.v = np.full(self.n, LIF["v_rest_mv"])
        self.g = np.zeros(self.n)
        self.blocked = np.zeros(self.n, dtype=np.int64)
        self.queue = np.zeros((self.slots, self.n))
        self.rate_hz = np.zeros(self.n)
        self.step_index = 0
        self.rng = np.random.default_rng([int(seed), 0x5B1])

    def advance(self, left: float, right: float, silenced: np.ndarray, drive: np.ndarray | None = None,
                substeps: int | None = None):
        """One neural step of `substeps` 0.1 ms substeps (by default ten: 1 ms). Returns the number of spikes. With
        `drive` (one value per neuron, from FlyVis), each neuron's Poisson rate follows its own drive instead of its
        side's sensor."""
        p = self.parameters
        if drive is None:  # the v0.4 arithmetic, unchanged, so recorded spiking runs replay exactly
            chances = [min(1., p.input_gain * value * p.spiking.input_rate_hz * LIF["dt_ms"] / 1000) for value in (left, right)]
            inputs = self.inputs
        else:
            targets = np.flatnonzero(drive > 0)
            inputs = [targets]
            chances = [np.minimum(1., p.input_gain * drive[targets] * p.spiking.input_rate_hz * LIF["dt_ms"] / 1000)]
        v, g, blocked = self.v, self.g, self.blocked
        weights = self.weights if self.scaled_weights is None else self.scaled_weights
        activated = self.activated
        total = 0
        for _ in range(self.substeps if substeps is None else substeps):
            np.subtract(blocked, 1, out=blocked, where=blocked > 0)
            free = blocked == 0
            # Masked arithmetic instead of boolean indexing: the same values, several times faster.
            dv = LIF["v_rest_mv"] - v
            dv += g
            dv *= self.decay_membrane
            dg = g * self.decay_synapse
            dv *= free
            dg *= free
            v += dv
            g -= dg
            v[silenced], g[silenced] = LIF["v_reset_mv"], 0
            spikes = np.flatnonzero(free & (v > LIF["v_threshold_mv"]))
            slot = self.step_index % self.slots
            if len(spikes):
                starts, ends = self.indptr[spikes], self.indptr[spikes + 1]
                lengths = ends - starts
                if lengths.sum():
                    offsets = np.repeat(starts - np.cumsum(lengths) + lengths, lengths) + np.arange(lengths.sum())
                    # The target slot was emptied when it was last delivered, one substep ago.
                    np.add.at(self.queue[(slot + self.delay) % self.slots], self.indices[offsets], weights[offsets])
            g += self.queue[slot]
            self.queue[slot] = 0
            for population, chance in zip(inputs, chances):
                if np.any(chance > 0):  # a scalar per side, or one value per neuron (FlyVis)
                    v[population[self.rng.random(len(population)) < chance]] += self.kick
            if len(activated):  # activation interventions: independent Poisson input
                v[activated[self.rng.random(len(activated)) < self.activation_chance]] += self.kick
            v[spikes], g[spikes] = LIF["v_reset_mv"], 0
            blocked[spikes] = self.refractory[spikes]
            self.rate_hz *= self.rate_decay
            self.rate_hz[spikes] += self.rate_jump
            self.step_index += 1
            total += len(spikes)
        if not np.isfinite(v).all():
            raise FloatingPointError("Nonfinite neural state; simulation paused.")
        return total


class ConnectomeCircuit:
    """A connectome circuit with rate (default) or spiking dynamics and configurable populations."""
    kind = "connectome"

    def __init__(self, parameters: ConnectomeParameters | None = None, path: Path | None = None):
        self.path = path  # an explicit file (tests); otherwise parameters.circuit names one
        self.data = None
        self.spiking = None
        self._seed = 0
        self._manipulation_key = self._manipulation = None
        self._applied = None  # the Manipulation last applied: scaled output shows in the activity
        self.visual = None  # FlyVis responses (eyes × types) when the FlyVis sensor drives the circuit
        self._history = self._lowpassed = None  # the motor path's delay line and low-passed command, when on
        self._motor_steps = self._motor_clipped = 0
        self._advanced = False
        self.configure(parameters or ConnectomeParameters())

    def configure(self, parameters: ConnectomeParameters):
        """Apply parameters. A live edit keeps the network state: the rates, or in spiking dynamics v, g, the delay
        queue, rates, step count and random generator, as long as circuit and input population are unchanged. It
        also keeps the loaded circuit, never reading the file again: the cache may have dropped it since."""
        source, data = self.path or parameters.circuit, self.data
        if data is None or (data.path != source if isinstance(source, Path) else data.key != source):
            data = load_circuit(source)
        if self.visual is not None:  # FlyVis drives the circuit: its input neurons must be reachable
            check_flyvis_inputs(data, parameters.input_types)
        self._visual_checked = self.visual is not None
        if data is not self.data:
            self.data = data
            self.rates = np.zeros(len(data.ids))
            self._manipulation_key = self._applied = None
            self._history = self._lowpassed = None
        self.parameters = parameters.model_copy(deep=True)
        p = self.parameters
        readout_types = p.readout_types if p.readout_types is not None else data.defaults["readout_types"]
        if not readout_types:
            raise ValueError(f"Choose readout cell types: the {data.key} circuit has no default steering readout.")
        unweighted = sorted(set(p.readout_weights or {}) - set(readout_types))
        if unweighted:
            raise ValueError(f"Readout weights name cell types that are not read out: {', '.join(unweighted)}.")
        self.readouts = []
        for name in readout_types:
            left, right = data.members(name, "left"), data.members(name, "right")
            if not len(left) or not len(right):
                raise ValueError(f"{name} needs neurons on both sides to read out turning.")
            self.readouts.append((name, left, right))
        self._readout_weights = [float((p.readout_weights or {}).get(name, 1.)) for name in readout_types]
        self.input_left, self.input_right = input_population(data, p.input_types)
        input_label = "Visual input" if p.input_types is None else "Input"
        if not len(self.input_left) or not len(self.input_right):
            raise ValueError("The chosen input population has no neurons on one side.")
        self.speed = np.unique(np.concatenate([data.members(t) for t in p.speed_types])) if p.speed_types else None
        self.unit_names = [f"{name} {side}" for name, _, _ in self.readouts for side in ("L", "R")] + \
            [f"{input_label} L", f"{input_label} R", "Circuit mean"] + (["Speed drive"] if self.speed is not None else [])
        signs = transmitter_signs(data, p.other_transmitters)
        active = (data.synapses >= p.synapse_threshold) & (signs[data.pre] != 0)
        n = len(data.ids)
        if p.dynamics == "spiking":
            inputs, state = (self.input_left, self.input_right), self.spiking
            if state is not None and state.data is data and all(map(np.array_equal, state.inputs, inputs)):
                state.configure(active, signs, p)
            else:
                self.spiking = SpikingState(data, active, signs, p, inputs)
                self.spiking.reset(self._seed)
            self.W = None
        else:
            self.spiking = None
            weights = signs[data.pre[active]] * data.synapses[active] * p.global_gain
            self.W = sparse.csr_matrix((weights, (data.post[active], data.pre[active])), shape=(n, n))
            self.W.sum_duplicates()
            self.W.sort_indices()
        self.tau = p.tau_ms / 1000
        self.counts = {
            "connections_total": int(len(data.synapses)),
            "connections_active": int(active.sum()),
            "excluded_below_threshold": int((data.synapses < p.synapse_threshold).sum()),
            "excluded_by_sign_assumption": int(((data.synapses >= p.synapse_threshold) & (signs[data.pre] == 0)).sum()),
            "excitatory_connections": int((active & (signs[data.pre] > 0)).sum()),
            "inhibitory_connections": int((active & (signs[data.pre] < 0)).sum()),
        }
        if not (p.motor_delay_ms or p.motor_tau_ms):
            self._history = self._lowpassed = None
        elif self._history is None:  # switched on: the delay line starts full of the current command
            self._restart_motor_path()

    def manipulation(self, interventions: Interventions) -> Manipulation:
        """What the interventions do to this circuit's neurons. Raises ValueError when they do not fit it: a cell type
        or side it lacks, or an activation its dynamics cannot take. Cached for the last interventions seen."""
        key = (self.parameters.dynamics, interventions.silence_dna02, tuple(interventions.silence_types),
               tuple((c.name, c.side, c.mode, c.value) for c in interventions.cell_types))
        if key != self._manipulation_key:
            self._manipulation, self._manipulation_key = self._compile(interventions), key
        return self._manipulation

    def _compile(self, interventions: Interventions) -> Manipulation:
        data, spiking = self.data, self.parameters.dynamics == "spiking"
        interventions.for_dynamics(self.parameters.dynamics)
        chosen, items = [], []

        def item(name, side, mode, value, neurons, field):
            effect = {"silence": "no output: held at rest" + (", no spikes" if spiking else ", rate 0"),
                      "scale": f"output × {value:g} to its targets and the readout",
                      "activate": f"independent Poisson input at {value:g} Hz to each neuron, no refractory period"
                                  if spiking else f"rate clamped to {value:g}"}[mode]
            items.append({"cell_type": name, "side": side, "mode": mode, "value": None if mode == "silence" else value,
                          "neurons": int(neurons), "effect": effect, "field": field})
        if interventions.silence_dna02 != "none":
            if "DNa02" not in data.type_members:
                raise ValueError(f"The {data.key} circuit has no DNa02 neurons to silence.")
            sides = ["left", "right"] if interventions.silence_dna02 == "both" else [interventions.silence_dna02]
            chosen += [data.members("DNa02", side) for side in sides]
            item("DNa02", interventions.silence_dna02, "silence", 0, sum(map(len, chosen)), "silence_dna02")
        for name in interventions.silence_types:
            chosen.append(data.members(name))
            item(name, "both", "silence", 0, len(chosen[-1]), "silence_types")
        scale, scaled, activated, activation = None, [], [], []
        for c in interventions.cell_types:
            members = data.members(c.name, None if c.side == "both" else c.side)
            if not len(members):
                raise ValueError(f"{c.name} has no {c.side} neurons in the {data.key} circuit.")
            if c.mode == "silence":
                chosen.append(members)
            elif c.mode == "scale":
                scale = np.ones(len(data.ids)) if scale is None else scale
                scale[members] *= c.value
                scaled.append(members)
            else:
                activated.append(members)
                activation.append(np.full(len(members), float(c.value)))
            item(c.name, c.side, c.mode, c.value, len(members), "cell_types")
        silenced = np.unique(np.concatenate(chosen)).astype(np.int64) if chosen else np.array([], dtype=np.int64)
        scaled = np.unique(np.concatenate(scaled)).astype(np.int64) if scaled else np.array([], dtype=np.int64)
        activated, activation = (np.concatenate(activated).astype(np.int64), np.concatenate(activation)) if activated \
            else (np.array([], dtype=np.int64), np.array([]))
        free = ~np.isin(activated, silenced)  # silencing wins
        return Manipulation(silenced, scaled, scale, activated[free], activation[free], items)

    def silenced(self, interventions: Interventions) -> np.ndarray:
        return self.manipulation(interventions).silenced

    @property
    def _output_scale(self) -> np.ndarray | None:
        return None if self._applied is None else self._applied.scale

    @property
    def activity(self) -> np.ndarray:
        """Rates for the rate model; for the spiking model, firing rate ÷ the rate scale. Scaled neurons show their
        output, scale × that activity, which is what their targets and the readout receive."""
        if self.spiking is not None:
            activity = self.spiking.rate_hz / self.parameters.spiking.rate_scale_hz
        else:
            activity = self.rates
        scale = self._output_scale
        return activity if scale is None else activity * scale

    def _activity_of(self, neurons: np.ndarray) -> np.ndarray:
        """activity[neurons], without computing it for every neuron."""
        if self.spiking is not None:
            activity = self.spiking.rate_hz[neurons] / self.parameters.spiking.rate_scale_hz
        else:
            activity = self.rates[neurons]
        scale = self._output_scale
        return activity if scale is None else activity * scale[neurons]

    def apply_silencing(self, interventions: Interventions):
        """Apply interventions at once, between steps: silenced neurons go to rest and, with rate dynamics, activated
        ones to their clamped rate; scaled output shows in the activity from now on."""
        m = self._applied = self.manipulation(interventions)
        silenced = m.silenced
        if self.spiking is not None:
            self.spiking.v[silenced], self.spiking.g[silenced], self.spiking.rate_hz[silenced] = LIF["v_reset_mv"], 0, 0
        else:
            self.rates[silenced] = 0
            if len(m.activated):
                self.rates[m.activated] = m.activation

    def reset(self, seed: int | None = None):
        if seed is not None:
            self._seed = int(seed)
        self.rates.fill(0)
        if self.spiking is not None:
            self.spiking.reset(self._seed)
        self._motor_steps = self._motor_clipped = 0
        self._advanced = False
        if self._history is not None:
            self._restart_motor_path()

    def set_visual(self, responses: np.ndarray | None):
        """Drive the input neurons from FlyVis (an eyes × types array, left eye first) through the circuit's
        FlyWire bridge, or return to the left/right sensor values with None. Returns the mean drive per side."""
        if responses is None:
            self.visual = self._visual_drive = None
            return None
        if not self._visual_checked:
            check_flyvis_inputs(self.data, self.parameters.input_types)
            self._visual_checked = True
        matrix, types = load_bridge(self.data)
        responses = np.asarray(responses, dtype=np.float64)
        if responses.shape != (2, len(types)):
            raise ValueError(f"FlyVis responses must be 2 × {len(types)}.")
        drive = np.zeros(len(self.data.ids))
        inputs = np.concatenate([self.input_left, self.input_right])
        drive[inputs] = (matrix @ responses.ravel())[inputs]
        self.visual, self._visual_drive = responses, drive
        return float(drive[self.input_left].mean()), float(drive[self.input_right].mean())

    def advance(self, sensors: SensorState, interventions: Interventions, dt: float = .001):
        m = self._applied = self.manipulation(interventions)
        silenced = m.silenced
        visual = self._visual_drive if self.visual is not None else None
        if self.spiking is not None:
            substeps = dt * 1000 / LIF["dt_ms"]  # the spiking network follows dt in whole 0.1 ms substeps
            if round(substeps) < 1 or not math.isclose(substeps, round(substeps)):
                raise ValueError(f"Spiking dynamics step in multiples of {LIF['dt_ms']:g} ms, not {dt * 1000:g} ms.")
            self.spiking.manipulate(m)
            self.spiking.advance(sensors.left, sensors.right, silenced, visual, round(substeps))
            self.spiking.rate_hz[silenced] = 0
        else:
            rates, clamped = self.rates, len(m.activated) > 0
            rates[silenced] = 0
            if clamped:
                rates[m.activated] = m.activation
            drive = self.W @ (rates if m.scale is None else rates * m.scale)
            gain = self.parameters.input_gain
            if visual is not None:
                drive += gain * visual
            else:
                drive[self.input_left] += gain * sensors.left
                drive[self.input_right] += gain * sensors.right
            np.clip(drive, 0, 1, out=drive)
            rates += dt / self.tau * (drive - rates)
            rates[silenced] = 0
            if clamped:
                rates[m.activated] = m.activation
            if not np.isfinite(rates).all():
                raise FloatingPointError("Nonfinite neural state; simulation paused.")
        self._advanced = True
        if self._history is not None:
            self._advance_motor_path(dt)

    def turn(self) -> float:
        """Positive when the readout's right side is more active: a rightward turn command."""
        p = self.parameters
        total = sum(w * (self._activity_of(right).mean() - self._activity_of(left).mean())
                    for w, (_, left, right) in zip(self._readout_weights, self.readouts))
        if p.readout_pool == "mean":
            total /= len(self.readouts)
        return p.output_gain * float(total)

    def forward(self) -> float:
        p = self.parameters
        return p.tonic_drive if self.speed is None else p.tonic_drive + p.speed_gain * float(self._activity_of(self.speed).mean())

    def command(self) -> np.ndarray:
        """The descending command [forward + turn, forward − turn] now, before the motor path and the clip."""
        turn, forward = self.turn(), self.forward()
        return np.array([forward + turn, forward - turn])

    def _restart_motor_path(self):
        command = self.command()
        self._history, self._lowpassed = deque([command]), command

    def _advance_motor_path(self, dt: float):
        """One neural step of the engineered motor path: a delay line of whole neural steps, then a first-order
        low-pass, on the descending command."""
        p, history = self.parameters, self._history
        slots = round(p.motor_delay_ms / (1000 * dt)) + 1
        if history.maxlen != slots:  # the delay changed: keep the newest commands, repeat the oldest to fill
            history = self._history = deque([history[0]] * (slots - len(history)) + list(history), maxlen=slots)
        history.append(self.command())
        delayed = history[0]
        if p.motor_tau_ms:
            self._lowpassed = self._lowpassed + (1 - math.exp(-1000 * dt / p.motor_tau_ms)) * (delayed - self._lowpassed)
        else:
            self._lowpassed = delayed

    def motor(self, baseline: bool = False) -> np.ndarray:
        if baseline:
            return np.ones(2)
        command = self.command() if self._lowpassed is None else self._lowpassed
        if self._advanced:  # count each command sent after the circuit advanced: one per control interval
            self._advanced = False
            self._motor_steps += 1
            self._motor_clipped += bool((command < 0).any() or (command > 1).any())
        # Larger left-leg amplitude turns FlyGym's body (and the toy body) to the right.
        return np.clip(command, 0, 1) * MOTOR_SCALE

    @property
    def motor_clipped_fraction(self) -> float:
        """Engineered diagnostic: the fraction of control intervals since the reset whose descending command left
        [0, 1] on either side, so the clip, not the circuit, set that side's amplitude."""
        return self._motor_clipped / self._motor_steps if self._motor_steps else 0.

    def readout(self) -> list[float]:
        r = self.activity
        values = [float(r[side].mean()) for _, left, right in self.readouts for side in (left, right)]
        values += [float(r[self.input_left].mean()), float(r[self.input_right].mean()), float(r.mean())]
        return values + ([float(r[self.speed].mean())] if self.speed is not None else [])

    def type_means(self) -> np.ndarray:
        return np.bincount(self.data.type_index, weights=self.activity, minlength=len(self.data.type_names)) / self.data.type_counts

    def description(self):
        data, p = self.data, self.parameters
        prov = data.provenance
        spiking = p.dynamics == "spiking"
        flyvis = self.visual is not None
        if flyvis:
            bridge = bridge_path(data)
            input_mapping = ("Engineered, unsigned FlyVis bridge: each sensor-input neuron's drive = input gain × Σ over eyes and "
                             "FlyVis cell types of bridge weight (its FlyWire v783 synapse fraction from that type and eye) × "
                             "pooled FlyVis response; every optic-lobe input counts as excitatory, unlike the circuit's sign rule"
                             + ("; Poisson spikes at input rate × input gain × that drive" if spiking else ""))
        else:
            input_mapping = ((f"Engineered: the left/right sensor value × input gain drives every neuron of {', '.join(p.input_types)} on that side"
                              if p.input_types else "Engineered: the left/right sensor value × input gain drives every visual projection neuron on that side")
                             + (" as Poisson spikes (input rate × sensor)" if spiking else ""))
        readout = ", ".join(name if p.readout_weights is None else f"{w:g} × {name}"
                            for w, (name, _, _) in zip(self._readout_weights, self.readouts))
        path = ([f"delayed by {p.motor_delay_ms:g} ms (in whole neural steps)"] if p.motor_delay_ms else []) + \
            ([f"low-passed with tau {p.motor_tau_ms:g} ms (each neural step: c += (1 − exp(−dt/tau)) × (input − c))"]
             if p.motor_tau_ms else [])
        motor = ("command = [forward + turn, forward − turn], " + ", then ".join(path) + "; motor = 1.4 × clip(command, 0, 1)"
                 if path else "motor = 1.4 × clip([forward + turn, forward − turn], 0, 1)")
        return {
            "kind": self.kind, "unit_names": self.unit_names, "parameters": p.model_dump(),
            "circuit": data.key, "circuit_file": str(data.path.relative_to(ROOT)) if data.path.is_relative_to(ROOT) else data.path.name,
            "circuit_sha256": data.sha256, "circuit_name": data.name,
            "dataset": f"{prov['dataset']} {prov['release']} · {prov['specimen']}",
            "license": prov["license"], "coverage": prov["coverage"],
            "neurons": len(data.ids), "cell_types": len(data.type_names), **self.counts,
            "readout": [{"cell_type": name, "left": [data.ids[i] for i in left], "right": [data.ids[i] for i in right]}
                        for name, left, right in self.readouts],
            "input_population": {"cell_types": p.input_types or f"super class {INPUT_SUPER_CLASS}",
                                 "left": int(len(self.input_left)), "right": int(len(self.input_right))},
            "speed_population": p.speed_types or None,
            "dynamics": p.dynamics,
            "readout_units": "firing rate (spikes/s) ÷ rate scale" if spiking else "dimensionless rate",
            "equation": ("Shiu et al. 2024 LIF: dv/dt = (v_rest − v + g)/tau_m, dg/dt = −g/tau_s; spike → g_post += sign × synapses × w_syn after 1.8 ms"
                         if spiking else "r += dt/tau * (clip(W @ r + input, 0, 1) - r); W_ij = sign(j) * synapses(j->i) * global_gain"),
            "spiking_constants": LIF if spiking else None,
            "signs": {"acetylcholine": "+1 (assumed)", "gaba": "-1 (assumed)", "glutamate": "-1 (assumed)",
                      "dopamine, serotonin, octopamine, unknown": "excluded (assumed)" if p.other_transmitters == "excluded"
                      else "+1 (assumed, Shiu et al. 2024 convention)"},
            "input_mapping": input_mapping,
            "flyvis_bridge": {"file": str(bridge.relative_to(ROOT)) if bridge.is_relative_to(ROOT) else bridge.name,
                              "signs": "unsigned: every FlyVis cell type's input counts as excitatory"} if flyvis else None,
            "output_mapping": (f"Engineered readout: turn = output gain × {'mean' if p.readout_pool == 'mean' else 'Σ'} (right − left) over "
                               f"{readout}; forward = tonic"
                               + (f" + speed gain × mean({', '.join(p.speed_types)})" if p.speed_types else "")
                               + f"; {motor}. "
                               "Direction: higher right DNa02 → rightward turn (Rayshubskiy et al. 2025); larger left amplitude turns right (FlyGym HybridTurningController)."),
            "motor_clipped_fraction": self.motor_clipped_fraction,
            # The interventions in force when described (for an export: at its end; events hold the schedule).
            "interventions": self._applied.items if self._applied is not None else [],
            "labels": {"structure": "data-derived", "signs": "assumed", "dynamics": "engineered" if not spiking else "published model (Shiu et al. 2024 parameters)",
                       "input_mapping": "engineered, unsigned FlyVis bridge" if flyvis else "engineered",
                       "output_mapping": "engineered, direction from literature",
                       "motor_path": "engineered (readout weights and pooling, delay, low-pass)",
                       "motor_clipped_fraction": "engineered diagnostic",
                       "interventions": "engineered manipulations; activation as Poisson drive (spiking) or a clamped "
                                        "rate (rate) approximates optogenetic activation and is not calibrated"},
        }


def _display_types(data: CircuitData, keep: set[int], limit: int) -> np.ndarray:
    n_types = len(data.type_names)
    if n_types <= limit:
        return np.arange(n_types)
    layer = np.full(n_types, 99, dtype=np.int64)
    hops = np.where(data.hop < 0, 98, data.hop)
    np.minimum.at(layer, data.type_index, hops)
    order = np.lexsort((np.arange(n_types), -data.type_counts, layer))
    chosen = list(keep) + [int(t) for t in order if int(t) not in keep]
    return np.array(sorted(chosen[:max(limit, len(keep))]))


def circuit_summary(parameters: ConnectomeParameters | None = None, limit: int = DISPLAY_TYPES) -> dict:
    """Cell-type view of a circuit for display: counts, layers and sign-aggregated connections."""
    parameters = parameters or ConnectomeParameters()
    model = ConnectomeCircuit(parameters.model_copy(update={"dynamics": "rate"}))
    data = model.data
    signs = transmitter_signs(data, parameters.other_transmitters)
    active = (data.synapses >= parameters.synapse_threshold) & (signs[data.pre] != 0)
    special = {data.type_names.index(name) for name, _, _ in model.readouts}
    special |= {int(data.type_index[i]) for i in np.concatenate([model.input_left, model.input_right])} if parameters.input_types else set()
    if model.speed is not None:
        special |= {int(t) for t in np.unique(data.type_index[model.speed])}
    shown = _display_types(data, special, limit)
    visible = np.zeros(len(data.type_names), dtype=bool)
    visible[shown] = True
    t_pre, t_post = data.type_index[data.pre[active]], data.type_index[data.post[active]]
    keep = visible[t_pre] & visible[t_post]
    n_types = len(data.type_names)
    key = ((t_pre[keep] * n_types + t_post[keep]) * 2 + (signs[data.pre[active]][keep] > 0)).astype(np.int64)
    unique, inverse = np.unique(key, return_inverse=True)
    synapses = np.bincount(inverse, weights=data.synapses[active][keep])
    connections = np.bincount(inverse)
    inputs = np.zeros(len(data.ids), dtype=bool)
    inputs[model.input_left] = inputs[model.input_right] = True
    types = []
    for t in shown.tolist():
        name = data.type_names[t]
        members = data.type_members[name]
        transmitters = {}
        for nt in data.transmitter[members]:
            transmitters[nt] = transmitters.get(nt, 0) + 1
        hops = data.hop[members]
        types.append({
            "index": t, "name": name, "count": int(len(members)),
            "layer": int(hops[hops >= 0].min()) if (hops >= 0).any() else -1,
            "super_class": max(set(data.super_class[members]), key=list(data.super_class[members]).count),
            "transmitters": transmitters, "transmitter": max(transmitters.items(), key=lambda item: (item[1], item[0]))[0],
            "sign": int(np.sign(signs[members].sum())),
            "left": int((data.side[members] == "left").sum()), "right": int((data.side[members] == "right").sum()),
            "input": bool(inputs[members].any()),
        })

    def into(neurons):
        # Inputs to one side of a readout type, by presynaptic cell type and sign.
        mask = active & np.isin(data.post, neurons)
        pre_type = data.type_index[data.pre[mask]]
        pre_sign = signs[data.pre[mask]].astype(np.int64)
        keys, back = np.unique(pre_type * 2 + (pre_sign > 0), return_inverse=True)
        return {"pre": (keys // 2).tolist(), "sign": np.where(keys % 2 == 1, 1, -1).tolist(),
                "synapses": np.bincount(back, weights=data.synapses[mask]).astype(np.int64).tolist()}

    return {
        "name": data.key, "title": data.name, "sha256": data.sha256, "parameters": parameters.model_dump(),
        "neurons": len(data.ids), "connections_active": int(active.sum()),
        "types_total": n_types, "types_shown": int(len(shown)),
        "readouts": [{"cell_type": name, "type_index": data.type_names.index(name),
                      "left": [data.ids[i] for i in left], "right": [data.ids[i] for i in right],
                      "inputs": {"left": into(left), "right": into(right)}} for name, left, right in model.readouts],
        "provenance": {k: data.provenance[k] for k in ["dataset", "release", "specimen", "license", "coverage"]},
        "citations": data.provenance.get("citations", []),
        "types": types,
        "edges": {"pre": (unique // 2 // n_types).tolist(), "post": (unique // 2 % n_types).tolist(),
                  "sign": np.where(unique % 2 == 1, 1, -1).tolist(), "synapses": synapses.astype(np.int64).tolist(),
                  "connections": connections.tolist()},
        "labels": {"structure": "data-derived (FlyWire v783)", "signs": "assumed from predicted transmitters",
                   "layout": "layers are hop distance to the seeds, not anatomy"},
    }


def trace_paths(parameters: ConnectomeParameters, source: str, target: str, max_hops: int = 4,
                limit: int = 10, beam: int = 400) -> dict:
    """Strongest cell-type paths from `source` to `target` within the circuit.

    A step's strength is the input fraction it carries: synapses from the source type onto the target
    type ÷ every synapse onto the target type in the circuit. A path multiplies its steps; its net sign
    multiplies each step's assumed sign. Beam search keeps the strongest `beam` partial paths per depth.
    """
    data = load_circuit(parameters.circuit)
    for name in (source, target):
        data.members(name)
    signs = transmitter_signs(data, parameters.other_transmitters)
    active = (data.synapses >= parameters.synapse_threshold) & (signs[data.pre] != 0)
    n_types = len(data.type_names)
    t_pre, t_post = data.type_index[data.pre[active]], data.type_index[data.post[active]]
    key = t_pre * n_types + t_post
    unique, inverse = np.unique(key, return_inverse=True)
    signed = np.bincount(inverse, weights=signs[data.pre[active]] * data.synapses[active])
    total = np.bincount(inverse, weights=data.synapses[active])
    incoming = np.bincount(data.type_index[data.post], weights=data.synapses, minlength=n_types)
    edge_pre, edge_post = unique // n_types, unique % n_types
    fraction = total / incoming[edge_post]
    outgoing = {}
    for a, b, f, s in zip(edge_pre.tolist(), edge_post.tolist(), fraction.tolist(), np.sign(signed).tolist()):
        if a != b:
            outgoing.setdefault(a, []).append((b, f, int(s)))
    start, goal = data.type_names.index(source), data.type_names.index(target)
    frontier, found = [((start,), 1.0, 1)], []
    for _ in range(max_hops):
        extended = []
        for path, strength, sign in frontier:
            for nxt, f, s in outgoing.get(path[-1], []):
                if nxt in path:
                    continue
                candidate = (path + (nxt,), strength * f, sign * s)
                (found if nxt == goal else extended).append(candidate)
        frontier = sorted(extended, key=lambda c: -c[1])[:beam]
    found.sort(key=lambda c: -c[1])
    return {"source": source, "target": target, "max_hops": max_hops, "circuit": data.key,
            "paths": [{"cell_types": [data.type_names[t] for t in path], "strength": strength,
                       "net_sign": sign} for path, strength, sign in found[:limit]],
            "rule": "Step strength = synapses onto the next type ÷ all its input synapses in the circuit; "
                    "net sign multiplies the assumed signs. Strongest paths by beam search."}
