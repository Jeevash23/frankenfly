"""Connectome-constrained rate model around the two DNa02 steering neurons.

What each part is:
  data-derived  neurons, cell types, sides, predicted transmitters and synapse counts from
                FlyWire FAFB v783 (data/circuits/fafb783-dna02.json, built by scripts/build_circuit.py)
  assumed       signs: acetylcholine excitatory; GABA and glutamate inhibitory (as in Shiu et al. 2024);
                dopamine, serotonin, octopamine and unknown transmitters excluded unless switched on
  engineered    leaky-rate dynamics and their global gains; the sensor → visual projection neuron
                input mapping; forward drive as a tonic term; the turning readout gain

Euler update every 1 ms for every neuron i:
  r_i += dt/tau × (clip(sum_j W_ij r_j + input_i, 0, 1) − r_i)
  W_ij = sign(j) × synapses(j → i) × global_gain
Turning: right DNa02 more active than left turns the fly right (Rayshubskiy et al. 2025), and
FlyGym's HybridTurningController turns right when the left legs' amplitude exceeds the right's.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy import sparse
from digitalfly.api.models import ConnectomeParameters, Interventions, SensorState

ROOT = Path(__file__).resolve().parents[4]
CIRCUIT_PATH = ROOT / "data/circuits/fafb783-dna02.json"
READOUT_NAMES = ["DNa02 L", "DNa02 R", "Visual input L", "Visual input R", "Circuit mean"]
INPUT_SUPER_CLASS = "visual_projection"
CLASSIC_SIGNS = {"acetylcholine": 1, "gaba": -1, "glutamate": -1}
OTHER_TRANSMITTERS = ("dopamine", "serotonin", "octopamine", "unknown")
MOTOR_SCALE = 1.4  # Same descending-to-amplitude scale as the engineered model.
TRACE_TYPES = 5


class CircuitData:
    """The committed circuit file, validated once and shared by every model instance."""

    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.path = path
        self.sha256 = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
        if data.get("format") != "digitalfly-circuit" or data.get("version") != 1:
            raise ValueError(f"{path.name} is not a version-1 DigitalFly circuit file.")
        self.provenance = data["provenance"]
        self.name = data["name"]
        lookups, neurons, edges = data["lookups"], data["neurons"], data["edges"]
        self.ids = list(neurons["id"])
        n = len(self.ids)
        for key in ["cell_type", "super_class", "cell_class", "transmitter", "side", "hop"]:
            if len(neurons[key]) != n:
                raise ValueError(f"Circuit field {key} has {len(neurons[key])} entries for {n} neurons.")
        self.type_names = list(lookups["cell_type"])
        self.type_index = np.asarray(neurons["cell_type"], dtype=np.int64)
        self.super_class = np.asarray(lookups["super_class"], dtype=object)[neurons["super_class"]]
        self.cell_class = np.asarray(lookups["cell_class"], dtype=object)[neurons["cell_class"]]
        self.transmitter = np.asarray(lookups["transmitter"], dtype=object)[neurons["transmitter"]]
        self.side = np.asarray(lookups["side"], dtype=object)[neurons["side"]]
        self.hop = np.asarray(neurons["hop"], dtype=np.int64)
        self.pre = np.asarray(edges["pre"], dtype=np.int64)
        self.post = np.asarray(edges["post"], dtype=np.int64)
        self.synapses = np.asarray(edges["synapses"], dtype=np.float64)
        if not (len(self.pre) == len(self.post) == len(self.synapses)):
            raise ValueError("Circuit edge arrays differ in length.")
        if len(self.pre) and (min(self.pre.min(), self.post.min()) < 0 or max(self.pre.max(), self.post.max()) >= n):
            raise ValueError("Circuit edge refers to a missing neuron.")
        if (self.synapses < 1).any():
            raise ValueError("Circuit synapse counts must be positive.")
        dna02 = self.provenance["dna02"]
        self.left, self.right = self.ids.index(dna02["left"]), self.ids.index(dna02["right"])
        if self.type_names[self.type_index[self.left]] != "DNa02" or self.type_names[self.type_index[self.right]] != "DNa02":
            raise ValueError("The circuit's DNa02 entries are not typed DNa02.")
        inputs = self.super_class == INPUT_SUPER_CLASS
        self.input_left = np.flatnonzero(inputs & (self.side == "left"))
        self.input_right = np.flatnonzero(inputs & (self.side == "right"))
        if not len(self.input_left) or not len(self.input_right):
            raise ValueError("The circuit has no visual projection neurons on one side.")
        self.type_counts = np.bincount(self.type_index, minlength=len(self.type_names))
        self.type_members = {name: np.flatnonzero(self.type_index == i) for i, name in enumerate(self.type_names)}


@lru_cache(maxsize=2)
def _load(path: str, mtime_ns: int) -> CircuitData:
    return CircuitData(Path(path))


def load_circuit(path: Path = CIRCUIT_PATH) -> CircuitData:
    if not path.is_file():
        raise FileNotFoundError("The connectome circuit file is missing. Rebuild it with scripts/build_circuit.py.")
    return _load(str(path), path.stat().st_mtime_ns)


def known_cell_types() -> set[str]:
    return set(load_circuit().type_names)


def transmitter_signs(data: CircuitData, other_transmitters: str) -> np.ndarray:
    other = 1 if other_transmitters == "excitatory" else 0
    return np.array([CLASSIC_SIGNS.get(nt, other) for nt in data.transmitter], dtype=np.float64)


class ConnectomeCircuit:
    kind = "connectome_dna02"
    unit_names = READOUT_NAMES

    def __init__(self, parameters: ConnectomeParameters | None = None, path: Path = CIRCUIT_PATH):
        self.data = load_circuit(path)
        self.rates = np.zeros(len(self.data.ids))
        self._silence_key = None
        self._silenced = np.array([], dtype=np.int64)
        self.configure(parameters or ConnectomeParameters())

    def configure(self, parameters: ConnectomeParameters):
        data = self.data
        self.parameters = parameters.model_copy(deep=True)
        signs = transmitter_signs(data, parameters.other_transmitters)
        active = (data.synapses >= parameters.synapse_threshold) & (signs[data.pre] != 0)
        weights = signs[data.pre[active]] * data.synapses[active] * parameters.global_gain
        n = len(data.ids)
        self.W = sparse.csr_matrix((weights, (data.post[active], data.pre[active])), shape=(n, n))
        self.W.sum_duplicates()
        self.W.sort_indices()
        self.tau = parameters.tau_ms / 1000
        self.counts = {
            "connections_total": int(len(data.synapses)),
            "connections_active": int(active.sum()),
            "excluded_below_threshold": int((data.synapses < parameters.synapse_threshold).sum()),
            "excluded_by_sign_assumption": int(((data.synapses >= parameters.synapse_threshold) & (signs[data.pre] == 0)).sum()),
            "excitatory_connections": int((active & (signs[data.pre] > 0)).sum()),
            "inhibitory_connections": int((active & (signs[data.pre] < 0)).sum()),
        }

    def silenced(self, interventions: Interventions) -> np.ndarray:
        key = (interventions.silence_dna02, tuple(interventions.silence_types))
        if key != self._silence_key:
            data = self.data
            chosen = []
            if interventions.silence_dna02 in {"left", "both"}:
                chosen.append([data.left])
            if interventions.silence_dna02 in {"right", "both"}:
                chosen.append([data.right])
            for name in interventions.silence_types:
                if name not in data.type_members:
                    raise ValueError(f"{name} is not a cell type in the connectome circuit.")
                chosen.append(data.type_members[name])
            self._silenced = np.unique(np.concatenate(chosen)).astype(np.int64) if chosen else np.array([], dtype=np.int64)
            self._silence_key = key
        return self._silenced

    def apply_silencing(self, interventions: Interventions):
        self.rates[self.silenced(interventions)] = 0

    def reset(self):
        self.rates.fill(0)

    def advance(self, sensors: SensorState, interventions: Interventions, dt: float = .001):
        silenced = self.silenced(interventions)
        rates = self.rates
        rates[silenced] = 0
        drive = self.W @ rates
        gain = self.parameters.input_gain
        drive[self.data.input_left] += gain * sensors.left
        drive[self.data.input_right] += gain * sensors.right
        np.clip(drive, 0, 1, out=drive)
        rates += dt / self.tau * (drive - rates)
        rates[silenced] = 0
        if not np.isfinite(rates).all():
            raise FloatingPointError("Nonfinite neural state; simulation paused.")

    def turn(self) -> float:
        """Positive when the right DNa02 is more active: a rightward turn command."""
        return self.parameters.output_gain * float(self.rates[self.data.right] - self.rates[self.data.left])

    def motor(self, baseline: bool = False) -> np.ndarray:
        if baseline:
            return np.ones(2)
        turn, tonic = self.turn(), self.parameters.tonic_drive
        # Larger left-leg amplitude turns FlyGym's body (and the toy body) to the right.
        return np.clip(np.array([tonic + turn, tonic - turn]), 0, 1) * MOTOR_SCALE

    def readout(self) -> list[float]:
        r, data = self.rates, self.data
        return [float(r[data.left]), float(r[data.right]), float(r[data.input_left].mean()),
                float(r[data.input_right].mean()), float(r.mean())]

    def type_means(self) -> np.ndarray:
        return np.bincount(self.data.type_index, weights=self.rates, minlength=len(self.data.type_names)) / self.data.type_counts

    def description(self):
        data, p = self.data, self.parameters
        prov = data.provenance
        return {
            "kind": self.kind, "unit_names": READOUT_NAMES, "parameters": p.model_dump(),
            "circuit_file": str(data.path.relative_to(ROOT)) if data.path.is_relative_to(ROOT) else data.path.name,
            "circuit_sha256": data.sha256, "circuit_name": data.name,
            "dataset": f"{prov['dataset']} {prov['release']} · {prov['specimen']}",
            "license": prov["license"], "coverage": prov["coverage"],
            "neurons": len(data.ids), "cell_types": len(data.type_names), **self.counts,
            "dna02": {"left": data.ids[data.left], "right": data.ids[data.right]},
            "input_population": {"super_class": INPUT_SUPER_CLASS, "left": int(len(data.input_left)),
                                 "right": int(len(data.input_right))},
            "equation": "r += dt/tau * (clip(W @ r + input, 0, 1) - r); W_ij = sign(j) * synapses(j->i) * global_gain",
            "signs": {"acetylcholine": "+1 (assumed)", "gaba": "-1 (assumed)", "glutamate": "-1 (assumed)",
                      "dopamine, serotonin, octopamine, unknown": "excluded (assumed)" if p.other_transmitters == "excluded"
                      else "+1 (assumed, Shiu et al. 2024 convention)"},
            "input_mapping": "Engineered: the left/right sensor value × input gain drives every visual projection neuron on that side",
            "output_mapping": ("Engineered readout: turn = output gain × (DNa02 R − DNa02 L); motor = 1.4 × clip([tonic + turn, tonic − turn], 0, 1). "
                               "Direction: higher right DNa02 → rightward turn (Rayshubskiy et al. 2025); larger left amplitude turns right (FlyGym HybridTurningController)."),
            "labels": {"structure": "data-derived", "signs": "assumed", "dynamics": "engineered",
                       "input_mapping": "engineered", "output_mapping": "engineered, direction from literature"},
        }


def circuit_summary(parameters: ConnectomeParameters | None = None) -> dict:
    """Cell-type view of the circuit for display: counts, layers and sign-aggregated connections."""
    parameters = parameters or ConnectomeParameters()
    data = load_circuit()
    signs = transmitter_signs(data, parameters.other_transmitters)
    active = (data.synapses >= parameters.synapse_threshold) & (signs[data.pre] != 0)
    t_pre, t_post = data.type_index[data.pre[active]], data.type_index[data.post[active]]
    sign = signs[data.pre[active]].astype(np.int64)
    n_types = len(data.type_names)
    key = (t_pre * n_types + t_post) * 2 + (sign > 0)
    unique, inverse = np.unique(key, return_inverse=True)
    synapses = np.bincount(inverse, weights=data.synapses[active])
    connections = np.bincount(inverse)
    inputs = np.zeros(len(data.ids), dtype=bool)
    inputs[data.input_left] = inputs[data.input_right] = True
    types = []
    for t, name in enumerate(data.type_names):
        members = data.type_members[name]
        transmitters = {}
        for nt in data.transmitter[members]:
            transmitters[nt] = transmitters.get(nt, 0) + 1
        dominant = max(transmitters.items(), key=lambda item: (item[1], item[0]))[0]
        types.append({
            "name": name, "count": int(len(members)), "layer": int(data.hop[members].min()),
            "super_class": max(set(data.super_class[members]), key=list(data.super_class[members]).count),
            "transmitters": transmitters, "transmitter": dominant,
            "sign": int(np.sign(signs[members].sum())),
            "left": int((data.side[members] == "left").sum()), "right": int((data.side[members] == "right").sum()),
            "input": bool(inputs[members].any()),
        })
    def into(neuron):
        # Inputs to one DNa02, aggregated by presynaptic cell type and sign, to show left/right differences.
        mask = active & (data.post == neuron)
        pre_type = data.type_index[data.pre[mask]]
        pre_sign = signs[data.pre[mask]].astype(np.int64)
        keys, back = np.unique(pre_type * 2 + (pre_sign > 0), return_inverse=True)
        return {"pre": (keys // 2).tolist(), "sign": np.where(keys % 2 == 1, 1, -1).tolist(),
                "synapses": np.bincount(back, weights=data.synapses[mask]).astype(np.int64).tolist()}

    return {
        "name": data.name, "sha256": data.sha256, "parameters": parameters.model_dump(),
        "neurons": len(data.ids), "connections_active": int(active.sum()),
        "dna02_inputs": {"left": into(data.left), "right": into(data.right)},
        "dna02": {"left": data.ids[data.left], "right": data.ids[data.right], "type_index": data.type_names.index("DNa02")},
        "provenance": {k: data.provenance[k] for k in ["dataset", "release", "specimen", "license", "coverage"]},
        "citations": data.provenance.get("citations", []),
        "types": types,
        "edges": {"pre": (unique // 2 // n_types).tolist(), "post": (unique // 2 % n_types).tolist(),
                  "sign": np.where(unique % 2 == 1, 1, -1).tolist(), "synapses": synapses.astype(np.int64).tolist(),
                  "connections": connections.tolist()},
        "labels": {"structure": "data-derived (FlyWire v783)", "signs": "assumed from predicted transmitters",
                   "layout": "layers are hop distance to DNa02, not anatomy"},
    }
