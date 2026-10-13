"""Hand-designed rate circuit, no biological cell identities or connectivity.

Rate vector: sensory L/R, steering L/R, descending L/R. All dimensionless.
Euler integration: r += dt/tau * (clip(W @ r + B @ s + b, 0, 1) - r).
"""
import numpy as np
from digitalfly.api.models import Interventions, Pose, SensorState, Stimulus, NeuralParameters

NAMES = ["Sensory L", "Sensory R", "Steering L", "Steering R", "Descending L", "Descending R"]
TAU = np.array([.025, .025, .05, .05, .08, .08])
W = np.array([
    [0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0],
    [1.7, -1.7, 0, 0, 0, 0],
    [-1.7, 1.7, 0, 0, 0, 0],
    [.45, .45, -.85, .85, 0, 0],
    [.45, .45, .85, -.85, 0, 0],
], dtype=float)
B = np.zeros((6, 2))
B[0, 0] = B[1, 1] = 1
BIAS = np.array([0, 0, 0, 0, .35, .35])
GROUPS = {"none": [], "sensory": [0, 1], "steering": [2, 3],
          "descending": [4, 5], "all": list(range(6))}


def encode(pose: Pose, stimulus: Stimulus, interventions: Interventions) -> SensorState:
    dx, dy = stimulus.x - pose.x, stimulus.y - pose.y
    distance = float(np.hypot(dx, dy))
    bearing = float(np.arctan2(np.sin(np.arctan2(dy, dx) - pose.yaw),
                               np.cos(np.arctan2(dy, dx) - pose.yaw)))
    intensity = stimulus.intensity / (1 + (distance / 20) ** 2)
    left = float(np.clip(intensity * (.5 + .5 * np.cos(bearing - np.pi / 4)), 0, 1))
    right = float(np.clip(intensity * (.5 + .5 * np.cos(bearing + np.pi / 4)), 0, 1))
    return SensorState(left=0 if interventions.zero_left else left,
                       right=0 if interventions.zero_right else right,
                       raw_left=left, raw_right=right, bearing_rad=bearing, distance_mm=distance)


class RateCircuit:
    kind = "engineered"
    unit_names = NAMES

    def __init__(self, parameters: NeuralParameters | None = None):
        self.rates = np.zeros(6)
        self.configure(parameters or NeuralParameters())

    def configure(self, parameters: NeuralParameters):
        self.parameters = parameters.model_copy(deep=True)
        self.W = W.copy()
        self.W[2:4] *= parameters.steering_gain
        self.B = B * parameters.sensory_gain
        self.bias = BIAS.copy()
        self.bias[4:6] = parameters.tonic_drive
        self.tau = TAU * parameters.time_scale

    def description(self):
        return {"unit_names": NAMES, "W": self.W.tolist(), "B": self.B.tolist(),
                "bias": self.bias.tolist(), "tau_s": self.tau.tolist(),
                "parameters": self.parameters.model_dump(),
                "kind": "engineered", "equation": "r += dt/tau * (clip(W @ r + B @ sensors + bias, 0, 1) - r)"}

    def reset(self, seed: int | None = None):
        self.rates.fill(0)  # deterministic: the seed only matters to stochastic models

    def apply_silencing(self, interventions: Interventions):
        self.rates[GROUPS[interventions.silence]] = 0

    def readout(self) -> list[float]:
        return self.rates.tolist()

    def advance(self, sensors: SensorState, interventions: Interventions, dt: float = .001):
        silenced = GROUPS[interventions.silence]
        self.rates[silenced] = 0
        inputs = np.array([sensors.left, sensors.right])
        target = np.clip(self.W @ self.rates + self.B @ inputs + self.bias, 0, 1)
        self.rates += dt / self.tau * (target - self.rates)
        self.rates[silenced] = 0
        if not np.isfinite(self.rates).all():
            raise FloatingPointError("Nonfinite neural state; simulation paused.")

    def motor(self, baseline: bool = False) -> np.ndarray:
        # No world coordinates here. Baseline explicitly bypasses the circuit.
        return np.ones(2) if baseline else np.clip(self.rates[4:6] * 1.4, 0, 1.4)
