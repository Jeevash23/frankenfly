from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Stimulus(StrictModel):
    x: float = Field(default=12, ge=-40, le=40)
    y: float = Field(default=8, ge=-40, le=40)
    intensity: float = Field(default=1, ge=0, le=2)


CellTypeName = Annotated[str, Field(min_length=1, max_length=120)]
CircuitName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
DEFAULT_CIRCUIT = "fafb783-dna02"


def silenced_types(interventions: "Interventions") -> list[str]:
    """Every cell type an intervention silences in the connectome model, DNa02 included."""
    return list(dict.fromkeys(interventions.silence_types + ["DNa02"] * (interventions.silence_dna02 != "none")))


def check_cell_types(names: list[str], circuit: str = DEFAULT_CIRCUIT) -> list[str]:
    """Cell types must exist in the named connectome circuit."""
    if not names:
        return names
    if len(set(names)) != len(names):
        raise ValueError("List each cell type once.")
    from digitalfly.neural.connectome import known_cell_types
    try:
        known = known_cell_types(circuit)
    except (OSError, ValueError) as exc:
        raise ValueError(f"The connectome circuit is unavailable: {exc}") from exc
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"Not a cell type in the {circuit} circuit: {', '.join(unknown)}.")
    return names


class Interventions(StrictModel):
    zero_left: bool = False
    zero_right: bool = False
    # Engineered six-unit model only.
    silence: Literal["none", "sensory", "steering", "descending", "all"] = "none"
    # Connectome model only.
    silence_dna02: Literal["none", "left", "right", "both"] = "none"
    silence_types: list[CellTypeName] = Field(default_factory=list, max_length=32)

    @field_validator("silence_types")
    @classmethod
    def distinct_types(cls, names):
        if len(set(names)) != len(names):
            raise ValueError("List each silenced cell type once.")
        return names

    def for_model(self, neural_model: str):
        """Reject interventions that the selected neural model does not have."""
        if neural_model == "engineered" and (self.silence_dna02 != "none" or self.silence_types):
            raise ValueError("DNa02 and cell-type silencing need the connectome model. Select it first.")
        if neural_model == "connectome" and self.silence != "none":
            raise ValueError("Group silencing belongs to the engineered six-unit model. "
                             "With the connectome model, silence DNa02 or a cell type instead.")
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

    @model_validator(mode="after")
    def distinct_populations(self):
        for group in (self.readout_types, self.input_types, self.speed_types):
            if group and len(set(group)) != len(group):
                raise ValueError("List each cell type once per population.")
        return self

    def check_against_circuit(self):
        """Raise ValueError unless the circuit exists and every named population is in it."""
        from digitalfly.neural.connectome import load_circuit
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
        for name in self.speed_types:
            data.members(name)
        if self.input_types:
            sides = {data.side[i] for name in self.input_types for i in data.members(name)}
            if not {"left", "right"} <= sides:
                raise ValueError("The input cell types need neurons on both sides.")
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
    sensor_model: Literal["geometric", "vision"] = "geometric"
    neural_model: Literal["engineered", "connectome"] = "engineered"
    neural_parameters: NeuralParameters = Field(default_factory=NeuralParameters)
    connectome_parameters: ConnectomeParameters = Field(default_factory=ConnectomeParameters)
    initial_interventions: Interventions = Field(default_factory=Interventions)
    protocol: Protocol | None = None

    @field_validator("neural_model", mode="before")
    @classmethod
    def legacy_model_name(cls, value):
        return "connectome" if value == "connectome_dna02" else value  # the v0.3 name

    @model_validator(mode="after")
    def supported_sensor(self):
        if self.engine == "toy" and self.sensor_model == "vision":
            raise ValueError("Compound-eye vision requires the FlyGym body and an OpenGL context.")
        scheduled = [e.interventions for e in self.protocol.events if e.interventions is not None] if self.protocol else []
        for interventions in [self.initial_interventions] + scheduled:
            interventions.for_model(self.neural_model)
        if self.neural_model == "connectome":
            self.connectome_parameters.check_against_circuit()
            for interventions in [self.initial_interventions] + scheduled:
                check_cell_types(silenced_types(interventions), self.connectome_parameters.circuit)
        return self


Condition = Literal["control", "left_sensor_off", "descending_off", "baseline",
                    "engineered_model", "connectome_model",
                    "dna02_left_off", "dna02_right_off", "dna02_both_off", "cell_type_off"]
ENGINEERED_ONLY = {"descending_off"}
CONNECTOME_ONLY = {"dna02_left_off", "dna02_right_off", "dna02_both_off", "cell_type_off"}


class BatchRequest(StrictModel):
    config: RunConfig
    seeds: list[int] = Field(default_factory=lambda: [42, 43], min_length=1, max_length=5)
    conditions: list[Condition] = Field(
        default_factory=lambda: ["control", "left_sensor_off"], min_length=1, max_length=4)
    cell_type: CellTypeName | None = None

    @model_validator(mode="after")
    def bounded(self):
        if self.config.protocol is None:
            raise ValueError("A comparison needs a finite protocol.")
        model = self.config.neural_model
        if model == "engineered" and CONNECTOME_ONLY & set(self.conditions):
            raise ValueError("DNa02 and cell-type conditions need the connectome model. Select it before comparing.")
        if model == "connectome" and ENGINEERED_ONLY & set(self.conditions):
            raise ValueError("“Descending units off” belongs to the engineered model; use a DNa02 condition instead.")
        if ("cell_type_off" in self.conditions) != (self.cell_type is not None):
            raise ValueError("Choose a cell type for the “cell type off” condition, and only with that condition.")
        circuit = self.config.connectome_parameters.circuit
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
        if self.config.protocol.duration_steps * len(self.seeds) * len(self.conditions) > 30000:
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
