from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Stimulus(StrictModel):
    x: float = Field(default=12, ge=-40, le=40)
    y: float = Field(default=8, ge=-40, le=40)
    intensity: float = Field(default=1, ge=0, le=2)


class Interventions(StrictModel):
    zero_left: bool = False
    zero_right: bool = False
    silence: Literal["none", "sensory", "steering", "descending", "all"] = "none"


class NeuralParameters(StrictModel):
    sensory_gain: float = Field(default=1, ge=0, le=3)
    steering_gain: float = Field(default=1, ge=0, le=3)
    tonic_drive: float = Field(default=.35, ge=0, le=1)
    time_scale: float = Field(default=1, ge=.25, le=4)


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
    neural_parameters: NeuralParameters = Field(default_factory=NeuralParameters)
    initial_interventions: Interventions = Field(default_factory=Interventions)
    protocol: Protocol | None = None

    @model_validator(mode="after")
    def supported_sensor(self):
        if self.engine == "toy" and self.sensor_model == "vision":
            raise ValueError("Compound-eye vision requires the FlyGym body and an OpenGL context.")
        return self


class BatchRequest(StrictModel):
    config: RunConfig
    seeds: list[int] = Field(default_factory=lambda: [42, 43], min_length=1, max_length=5)
    conditions: list[Literal["control", "left_sensor_off", "descending_off", "baseline"]] = Field(
        default_factory=lambda: ["control", "left_sensor_off"], min_length=1, max_length=4)

    @model_validator(mode="after")
    def bounded(self):
        if self.config.protocol is None:
            raise ValueError("A comparison needs a finite protocol.")
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
