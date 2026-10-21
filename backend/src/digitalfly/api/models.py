from typing import Annotated, Any, Literal, get_args
import asyncio
from pydantic import (BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator,
                      model_validator)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Stimulus(StrictModel):
    x: float = Field(default=12, ge=-40, le=40)
    y: float = Field(default=8, ge=-40, le=40)
    intensity: float = Field(default=1, ge=0, le=2)


CellTypeName = Annotated[str, Field(min_length=1, max_length=120)]
CircuitName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
DEFAULT_CIRCUIT = "fafb783-dna02"


def reads_files_later() -> bool:
    """True while validating on an asyncio event loop, as FastAPI does with every request body. Checks that read
    circuit files are skipped there, so a large circuit never stalls the API and its telemetry; the simulation
    worker validates every configuration again, in full and in its own thread, before using it."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def silenced_types(interventions: "Interventions") -> list[str]:
    """Every cell type an intervention silences in the connectome model, DNa02 included."""
    return list(dict.fromkeys(interventions.silence_types + ["DNa02"] * (interventions.silence_dna02 != "none")))


def intervention_types(interventions: "Interventions") -> list[str]:
    """Every cell type an intervention addresses in the connectome model: silenced, scaled or activated."""
    return list(dict.fromkeys(silenced_types(interventions) + [c.name for c in interventions.cell_types]))


def check_cell_types(names: list[str], circuit=DEFAULT_CIRCUIT) -> list[str]:
    """Cell types must exist in the connectome circuit: one named on disk, or a loaded CircuitData (what a run uses)."""
    if not names:
        return names
    if len(set(names)) != len(names):
        raise ValueError("List each cell type once.")
    if isinstance(circuit, str):
        from digitalfly.neural.connectome import known_cell_types
        try:
            known = known_cell_types(circuit)
        except (OSError, ValueError) as exc:
            raise ValueError(f"The connectome circuit is unavailable: {exc}") from exc
    else:
        known, circuit = circuit.type_members, circuit.key
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"Not a cell type in the {circuit} circuit: {', '.join(unknown)}.")
    return names


def check_interventions(interventions: "Interventions", circuit=DEFAULT_CIRCUIT, dynamics: str | None = None):
    """Raise ValueError unless every cell type the interventions address is in the connectome circuit (one named on
    disk, or a loaded CircuitData) with neurons on each side they name, and, given the dynamics, every activation
    value fits it."""
    if dynamics is not None:
        interventions.for_dynamics(dynamics)
    names = intervention_types(interventions)
    if not names:
        return interventions
    if isinstance(circuit, str):
        from digitalfly.neural.connectome import load_circuit
        try:
            circuit = load_circuit(circuit)
        except (OSError, ValueError) as exc:
            raise ValueError(f"The connectome circuit is unavailable: {exc}") from exc
    check_cell_types(names, circuit)
    for item in interventions.cell_types:
        if item.side != "both" and not len(circuit.members(item.name, item.side)):
            raise ValueError(f"{item.name} has no {item.side} neurons in the {circuit.key} circuit.")
    return interventions


class CellTypeIntervention(StrictModel):
    """An engineered manipulation of one cell type's neurons on one side or both (connectome model only):
    silence: no output (value ignored); scale: output × value (0–2); activate: independent Poisson input at value Hz
    to each neuron (spiking dynamics, 0–500) or its rate clamped to value (rate dynamics, 0–1).
    Equations: docs/ARCHITECTURE.md, "Connectome interventions"."""
    name: CellTypeName
    side: Literal["both", "left", "right"] = "both"
    mode: Literal["silence", "scale", "activate"]
    value: float = Field(default=0, ge=0, le=500)

    @model_validator(mode="after")
    def value_fits_mode(self):
        if self.mode == "scale" and self.value > 2:
            raise ValueError("Scaling multiplies a cell type's output by a value from 0 to 2.")
        return self

    @property
    def target(self) -> str:
        return self.name if self.side == "both" else f"{self.name} {self.side}"

    def label(self, dynamics: str = "rate") -> str:
        if self.mode == "silence":
            return f"{self.target} silenced"
        if self.mode == "scale":
            return f"{self.target} output ×{self.value:g}"
        return f"{self.target} activated " + (f"{self.value:g} Hz" if dynamics == "spiking" else f"(rate {self.value:g})")


class Interventions(StrictModel):
    zero_left: bool = False
    zero_right: bool = False
    # Engineered six-unit model only.
    silence: Literal["none", "sensory", "steering", "descending", "all"] = "none"
    # Connectome model only. silence_types entries mean {name, side "both", mode "silence"}.
    silence_dna02: Literal["none", "left", "right", "both"] = "none"
    silence_types: list[CellTypeName] = Field(default_factory=list, max_length=32)
    cell_types: list[CellTypeIntervention] = Field(default_factory=list, max_length=32)

    @field_validator("silence_types")
    @classmethod
    def distinct_types(cls, names):
        if len(set(names)) != len(names):
            raise ValueError("List each silenced cell type once.")
        return names

    @model_validator(mode="after")
    def sides_once(self):
        """One manipulation per side of a cell type: "both" covers left and right, a silence_types entry is the
        type on both sides and DNa02 silencing its side(s). The older fields may still overlap each other."""
        older = [(name, "both") for name in self.silence_types] + [("DNa02", self.silence_dna02)] * (self.silence_dna02 != "none")
        addressed = [(c.name, c.side) for c in self.cell_types]
        for k, (name, side) in enumerate(addressed):
            if any(name == other and (side == other_side or "both" in (side, other_side))
                   for other, other_side in addressed[:k] + older):
                raise ValueError(f"Set one intervention per side of a cell type: {name} ({side}) is addressed twice "
                                 "(“both” covers left and right; silenced types count as both sides).")
        return self

    def for_model(self, neural_model: str):
        """Reject interventions that the selected neural model does not have."""
        if neural_model == "engineered" and (self.silence_dna02 != "none" or self.silence_types or self.cell_types):
            raise ValueError("DNa02 and cell-type interventions need the connectome model. Select it first.")
        if neural_model == "connectome" and self.silence != "none":
            raise ValueError("Group silencing belongs to the engineered six-unit model. "
                             "With the connectome model, silence DNa02 or a cell type instead.")
        return self

    def for_dynamics(self, dynamics: str):
        """Reject activation values the connectome dynamics cannot take: rate dynamics clamp a rate within 0–1."""
        high = [c.name for c in self.cell_types if c.mode == "activate" and c.value > 1]
        if dynamics == "rate" and high:
            raise ValueError("With rate dynamics, activation clamps a cell type's rate to a value from 0 to 1 "
                             f"(spiking dynamics take 0–500 Hz): {', '.join(high)}.")
        return self


class NeuralParameters(StrictModel):
    sensory_gain: float = Field(default=1, ge=0, le=3)
    steering_gain: float = Field(default=1, ge=0, le=3)
    tonic_drive: float = Field(default=.35, ge=0, le=1)
    time_scale: float = Field(default=1, ge=.25, le=4)


class SpikingParameters(StrictModel):
    """Shiu et al. 2024's one free parameter plus the closed-loop input and readout. Neuron constants are fixed."""
    synapse_weight_mv: float = Field(default=.275, gt=0, le=5)
    input_rate_hz: float = Field(default=150, ge=0, le=1000)  # Poisson rate at sensor value 1 (Shiu et al.'s default)
    rate_window_ms: float = Field(default=50, ge=5, le=1000)  # readout smoothing of spike trains
    rate_scale_hz: float = Field(default=100, ge=1, le=1000)  # firing rate treated as a rate-model activity of 1


class ConnectomeParameters(StrictModel):
    """Settings of the connectome model. All are global: nothing addresses a single neuron or synapse."""
    circuit: CircuitName = DEFAULT_CIRCUIT
    dynamics: Literal["rate", "spiking"] = "rate"
    synapse_threshold: int = Field(default=5, ge=1, le=1000)
    global_gain: float = Field(default=.001, ge=0, le=1)
    input_gain: float = Field(default=1, ge=0, le=10)
    output_gain: float = Field(default=1, ge=0, le=20)
    tonic_drive: float = Field(default=.35, ge=0, le=1)
    tau_ms: float = Field(default=20, ge=5, le=200)
    other_transmitters: Literal["excluded", "excitatory"] = "excluded"
    # Populations by cell type. None means the circuit's default readout, or every visual projection neuron.
    readout_types: list[CellTypeName] | None = Field(default=None, min_length=1, max_length=8)
    input_types: list[CellTypeName] | None = Field(default=None, min_length=1, max_length=32)
    speed_types: list[CellTypeName] = Field(default_factory=list, max_length=8)
    speed_gain: float = Field(default=1, ge=0, le=10)
    spiking: SpikingParameters = Field(default_factory=SpikingParameters)
    # Engineered motor path. The defaults reproduce v0.5: equal weights, summed, no delay, no low-pass.
    readout_weights: dict[CellTypeName, Annotated[float, Field(ge=-5, le=5)]] | None = Field(default=None, max_length=8)
    readout_pool: Literal["sum", "mean"] = "sum"
    motor_delay_ms: float = Field(default=0, ge=0, le=500)  # descending command → walking controller
    motor_tau_ms: float = Field(default=0, ge=0, le=1000)  # first-order low-pass on that command; 0 = none

    @model_validator(mode="after")
    def distinct_populations(self):
        for group in (self.readout_types, self.input_types, self.speed_types):
            if group and len(set(group)) != len(group):
                raise ValueError("List each cell type once per population.")
        return self

    def check_against_circuit(self, data=None, flyvis: bool = False):
        """Raise ValueError unless the circuit exists and every population works in it: readout and input neurons on
        both sides (the default visual input too) and, with FlyVis eyes, input neurons that the circuit's FlyVis
        bridge reaches on both sides. `data` checks a loaded CircuitData instead of the file on disk."""
        import numpy as np
        from digitalfly.neural.connectome import INPUT_SUPER_CLASS, bridge_path, load_bridge, load_circuit
        if data is None:
            try:
                data = load_circuit(self.circuit)
            except (OSError, ValueError) as exc:
                raise ValueError(f"The {self.circuit} circuit is unavailable: {exc}") from exc
        readout = self.readout_types or data.defaults["readout_types"]
        if not readout:
            raise ValueError(f"Choose readout cell types: the {self.circuit} circuit has no default steering readout.")
        for name in readout:
            if not (len(data.members(name, "left")) and len(data.members(name, "right"))):
                raise ValueError(f"{name} needs neurons on both sides to read out turning.")
        unweighted = sorted(set(self.readout_weights or {}) - set(readout))
        if unweighted:
            raise ValueError(f"Readout weights name cell types that are not read out: {', '.join(unweighted)}.")
        for name in self.speed_types:
            data.members(name)
        if self.input_types:
            inputs = np.concatenate([data.members(name) for name in self.input_types])
            if not {"left", "right"} <= set(data.side[inputs]):
                raise ValueError("The input cell types need neurons on both sides.")
        else:
            inputs = np.flatnonzero(data.super_class == INPUT_SUPER_CLASS)
            for side in ("left", "right"):
                if not (data.side[inputs] == side).any():
                    raise ValueError(f"The {data.key} circuit has no visual projection neurons on the {side} side, so "
                                     "its default visual input cannot steer. Choose input cell types with neurons on "
                                     "both sides.")
        if flyvis:
            if not bridge_path(data).is_file():
                raise ValueError(f"The {data.key} circuit has no FlyVis bridge. Build it with "
                                 f"scripts/build_circuit.py flyvis-bridge --circuit {data.key}")
            matrix, _ = load_bridge(data)
            reached = matrix[inputs].getnnz(axis=1) > 0
            for side in ("left", "right"):
                if not reached[data.side[inputs] == side].any():
                    raise ValueError(f"FlyVis eyes would give the circuit no {side} input: its FlyVis bridge reaches "
                                     f"none of the {side} input neurons. The bridge feeds visual projection neurons; "
                                     "use the default visual input or visual projection cell types.")
        return data


class ProtocolEvent(StrictModel):
    step: int = Field(ge=0, le=29999)
    stimulus: Stimulus | None = None
    interventions: Interventions | None = None

    @model_validator(mode="after")
    def has_action(self):
        if self.stimulus is None and self.interventions is None:
            raise ValueError("A scheduled event needs a stimulus or intervention.")
        return self


class Protocol(StrictModel):
    name: str = Field(default="Target reversal", min_length=1, max_length=80)
    duration_steps: int = Field(default=200, ge=1, le=29999)
    events: list[ProtocolEvent] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_schedule(self):
        steps = [e.step for e in self.events]
        if steps != sorted(set(steps)) or any(s >= self.duration_steps for s in steps):
            raise ValueError("Event steps must be unique, sorted, and before the protocol end.")
        return self


class RunConfig(StrictModel):
    engine: Literal["flygym", "toy"] = "flygym"
    seed: int = Field(default=42, ge=0, le=2147483647)
    controller: Literal["neural", "baseline"] = "neural"
    speed: float = Field(default=0.25, ge=0.05, le=2)
    stimulus: Stimulus = Field(default_factory=Stimulus)
    # "flyvis": rendered eyes → FlyVis optic-lobe network → the circuit's visual neurons through FlyWire wiring.
    sensor_model: Literal["geometric", "vision", "flyvis"] = "geometric"
    neural_model: Literal["engineered", "connectome"] = "engineered"
    neural_parameters: NeuralParameters = Field(default_factory=NeuralParameters)
    connectome_parameters: ConnectomeParameters = Field(default_factory=ConnectomeParameters)
    initial_interventions: Interventions = Field(default_factory=Interventions)
    protocol: Protocol | None = None
    # "types": connectome runs also export activity_types.npz, every cell type's mean activity per control step.
    record_activity: Literal["none", "types"] = "none"

    @field_validator("neural_model", mode="before")
    @classmethod
    def legacy_model_name(cls, value):
        return "connectome" if value == "connectome_dna02" else value  # the v0.3 name

    @model_validator(mode="after")
    def supported_sensor(self):
        if self.engine == "toy" and self.sensor_model in ("vision", "flyvis"):
            raise ValueError("Compound-eye vision requires the FlyGym body and an OpenGL context.")
        if self.sensor_model == "flyvis":
            if self.neural_model != "connectome":
                raise ValueError("FlyVis eyes drive the connectome model's visual neurons. Select the connectome model.")
            from digitalfly.vision.flyvis_eyes import available
            ok, reason = available()
            if not ok:
                raise ValueError(reason)
        scheduled = [e.interventions for e in self.protocol.events if e.interventions is not None] if self.protocol else []
        for interventions in [self.initial_interventions] + scheduled:
            interventions.for_model(self.neural_model)
            if self.neural_model == "connectome":
                interventions.for_dynamics(self.connectome_parameters.dynamics)
        if self.neural_model == "connectome" and not reads_files_later():
            self.connectome_parameters.check_against_circuit(flyvis=self.sensor_model == "flyvis")
            for interventions in [self.initial_interventions] + scheduled:
                check_interventions(interventions, self.connectome_parameters.circuit)
        return self


Condition = Literal["control", "left_sensor_off", "descending_off", "baseline",
                    "engineered_model", "connectome_model",
                    "dna02_left_off", "dna02_right_off", "dna02_both_off", "cell_type_off"]
ENGINEERED_ONLY = {"descending_off"}
CONNECTOME_ONLY = {"dna02_left_off", "dna02_right_off", "dna02_both_off", "cell_type_off"}
MAX_CONDITIONS = 6  # built-in and custom together
# Connectome parameters a run can change live (POST /api/connectome/parameters); the rest need a reset.
FIXED_CONNECTOME_FIELDS = ("circuit", "dynamics", "readout_types", "input_types", "speed_types")
LIVE_CONNECTOME_FIELDS = tuple(k for k in ConnectomeParameters.model_fields if k not in FIXED_CONNECTOME_FIELDS)
ConditionLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40,
                                                  pattern=r"^[^\x00-\x1f\x7f]+$")]


class CustomCondition(StrictModel):
    """A comparison condition of your own: its trials hold `interventions` (none when null) and, with the connectome
    model, the configuration's connectome parameters with these live-editable fields changed (a partial `spiking`
    keeps the other spiking settings)."""
    label: ConditionLabel
    interventions: Interventions | None = None
    connectome_parameters: dict[str, Any] | None = None

    @field_validator("connectome_parameters")
    @classmethod
    def live_editable(cls, value):
        other = [k for k in value or {} if k not in LIVE_CONNECTOME_FIELDS]
        if other:
            raise ValueError(f"A condition can change only the connectome parameters a run can change live, not "
                             f"{', '.join(other)}; circuit, dynamics and populations belong to the configuration.")
        return value

    def overrides(self, config: RunConfig) -> dict:
        """A trial's configuration fields (model_dump form) that differ from `config`, its seed aside."""
        changes = {"controller": "neural", "initial_interventions": (self.interventions or Interventions()).model_dump()}
        if self.connectome_parameters:
            base, edit = config.connectome_parameters.model_dump(), self.connectome_parameters
            spiking = {"spiking": {**base["spiking"], **edit["spiking"]}} if isinstance(edit.get("spiking"), dict) else {}
            changes["connectome_parameters"] = {**base, **edit, **spiking}
        return changes


class BatchRequest(StrictModel):
    config: RunConfig
    seeds: list[int] = Field(default_factory=lambda: [42, 43], min_length=1, max_length=5)
    conditions: list[Condition] = Field(
        default_factory=lambda: ["control", "left_sensor_off"], min_length=0, max_length=4)
    cell_type: CellTypeName | None = None
    # Labelled conditions with their own interventions and/or live-editable connectome parameters.
    custom_conditions: list[CustomCondition] = Field(default_factory=list, max_length=MAX_CONDITIONS)
    # True runs the trials unpaced, as fast as the computer allows; otherwise the display speed paces them.
    max_speed: bool = False

    @property
    def condition_names(self) -> list[str]:
        """Built-in conditions, then custom labels: the order trials run in for each seed."""
        return [*self.conditions, *(c.label for c in self.custom_conditions)]

    def custom_config(self, label: str, seed: int) -> RunConfig:
        """A custom condition's trial configuration, validated in full like any reset."""
        custom = next(c for c in self.custom_conditions if c.label == label)
        return RunConfig.model_validate({**self.config.model_dump(), **custom.overrides(self.config), "seed": seed})

    @model_validator(mode="after")
    def bounded(self):
        if self.config.protocol is None:
            raise ValueError("A comparison needs a finite protocol.")
        labels = [c.label for c in self.custom_conditions]
        if not self.condition_names:
            raise ValueError("Choose at least one condition.")
        if len(self.condition_names) > MAX_CONDITIONS:
            raise ValueError(f"A comparison has at most {MAX_CONDITIONS} conditions, built-in and custom together.")
        if len(set(labels)) != len(labels) or set(labels) & set(get_args(Condition)):
            raise ValueError("Give each custom condition its own label, different from the built-in condition names.")
        for custom in self.custom_conditions:
            if custom.connectome_parameters and self.config.neural_model != "connectome":
                raise ValueError(f"Custom condition “{custom.label}” changes connectome parameters; select the "
                                 "connectome model first.")
            try:
                self.custom_config(custom.label, self.config.seed)
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'configuration'}: "
                                     f"{e['msg'].removeprefix('Value error, ')}" for e in exc.errors()[:3])
                raise ValueError(f"Custom condition “{custom.label}”: {problems}") from None
        model = self.config.neural_model
        if model == "engineered" and CONNECTOME_ONLY & set(self.conditions):
            raise ValueError("DNa02 and cell-type conditions need the connectome model. Select it before comparing.")
        if model == "connectome" and ENGINEERED_ONLY & set(self.conditions):
            raise ValueError("“Descending units off” belongs to the engineered model; use a DNa02 condition instead.")
        if self.config.sensor_model == "flyvis" and "engineered_model" in self.conditions:
            raise ValueError("FlyVis eyes drive only the connectome model, so “engineered model” cannot be compared "
                             "with them. Choose compound-eye or geometric sensing for that comparison.")
        if ("cell_type_off" in self.conditions) != (self.cell_type is not None):
            raise ValueError("Choose a cell type for the “cell type off” condition, and only with that condition.")
        circuit = self.config.connectome_parameters.circuit
        if not reads_files_later():
            if "connectome_model" in self.conditions:
                self.config.connectome_parameters.check_against_circuit()
            if self.cell_type is not None:
                check_cell_types([self.cell_type], circuit)
            if (CONNECTOME_ONLY - {"cell_type_off"}) & set(self.conditions):
                check_cell_types(["DNa02"], circuit)
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 or s > 2147483647 for s in self.seeds):
            raise ValueError("Seeds must be distinct integers between 0 and 2147483647.")
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("Conditions must be distinct.")
        if self.config.protocol.duration_steps * len(self.seeds) * len(self.condition_names) > 30000:
            raise ValueError("A comparison is limited to 30,000 total control intervals.")
        if any(e.interventions is not None for e in self.config.protocol.events):
            raise ValueError("Comparison protocols schedule stimuli only; the selected condition holds its intervention throughout each trial.")
        return self


class Speed(StrictModel):
    speed: float = Field(ge=0.05, le=2)


class Pose(StrictModel):
    x: float
    y: float
    z: float
    yaw: float
    velocity: float
    legs: list[list[list[float]]] = Field(default_factory=list)


class SensorState(StrictModel):
    left: float = 0
    right: float = 0
    raw_left: float = 0
    raw_right: float = 0
    bearing_rad: float = 0
    distance_mm: float = 0


class Sample(StrictModel):
    step: int
    t: float
    pose: Pose
    sensors: SensorState
    rates: list[float]
    motor: list[float]
    body_signals: dict = Field(default_factory=dict)


class Event(StrictModel):
    seq: int
    step: int
    t: float
    kind: str
    message: str
    payload: dict = Field(default_factory=dict)


class State(StrictModel):
    instance_id: str
    revision: int
    run_id: str
    status: Literal["initializing", "paused", "running", "error", "stopped"]
    error: str | None = None
    config: RunConfig
    interventions: Interventions
    sample: Sample | None = None
    history: list[Sample] = Field(default_factory=list)
    trail: list[list[float]] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    wall_s: float = 0
    real_time_factor: float = 0
    compute_real_time_factor: float = 0
    memory_mb: float = 0
    frame_revision: int = 0
    rendering: bool = False
    render_error: str | None = None
    subscribers: int = 0
    recording_samples: int = 0
    recording_limit: int = 30000
    provenance: dict[str, str] = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    vision: dict = Field(default_factory=dict)
    batch: dict | None = None
    connectome: dict | None = None
