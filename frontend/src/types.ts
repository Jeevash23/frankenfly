export type Engine = 'flygym' | 'toy';
export type Stimulus = {x: number; y: number; intensity: number};
export type Intervention = {
  zero_left: boolean;
  zero_right: boolean;
  silence: 'none' | 'sensory' | 'steering' | 'descending' | 'all';
};
export type NeuralParameters = {
  sensory_gain: number;
  steering_gain: number;
  tonic_drive: number;
  time_scale: number;
};
export type ProtocolEvent = {
  step: number;
  stimulus?: Stimulus | null;
  interventions?: Intervention | null;
};
export type Protocol = {name: string; duration_steps: number; events: ProtocolEvent[]};
export type Config = {
  engine: Engine;
  seed: number;
  controller: 'neural' | 'baseline';
  speed: number;
  stimulus: Stimulus;
  sensor_model: 'geometric' | 'vision';
  neural_parameters: NeuralParameters;
  initial_interventions: Intervention;
  protocol: Protocol | null;
};
export type BodySignals = {
  leg_order?: string[];
  ground_contact_force?: number[];
  contact?: boolean[];
  cpg_phase_rad?: number[];
  joint_position_rad?: number[];
  force_unit?: string;
};
export type Sample = {
  step: number;
  t: number;
  pose: {x: number; y: number; z: number; yaw: number; velocity: number; legs: number[][][]};
  sensors: {
    left: number;
    right: number;
    raw_left: number;
    raw_right: number;
    bearing_rad: number;
    distance_mm: number;
  };
  rates: number[];
  motor: number[];
  body_signals: BodySignals;
};
export type Metrics = {
  path_length_mm?: number;
  displacement_mm?: number;
  mean_speed_mm_s?: number;
  net_turn_deg?: number;
  target_distance_mm?: number;
  duration_s?: number;
  contact_fraction?: number[];
  protocol_complete?: boolean;
};
export type Batch = {
  id: string;
  status: 'running' | 'paused' | 'completed' | 'cancelled' | 'failed';
  total: number;
  current: number;
  condition: string;
  seed: number;
  protocol: string;
  results: {run_id: string; metrics: Metrics}[];
  error?: string;
};
export type RunEvent = {
  seq: number;
  step: number;
  t: number;
  kind: string;
  message: string;
  payload: Record<string, unknown>;
};
export type State = {
  instance_id: string;
  revision: number;
  run_id: string;
  status: 'initializing' | 'paused' | 'running' | 'error' | 'stopped';
  error: string | null;
  config: Config;
  interventions: Intervention;
  sample: Sample | null;
  history: Sample[];
  trail: number[][];
  events: RunEvent[];
  wall_s: number;
  real_time_factor: number;
  compute_real_time_factor: number;
  memory_mb: number;
  frame_revision: number;
  rendering: boolean;
  render_error: string | null;
  subscribers: number;
  recording_samples: number;
  recording_limit: number;
  provenance: Record<string, string>;
  metrics: Metrics;
  vision: {ommatidia_per_eye?: number; left?: number[]; right?: number[]; sample_time_s?: number};
  batch: Batch | null;
};
export type Command = (path: string, body?: unknown) => Promise<any>;
export type SavedRun = {
  key: string;
  run_id: string;
  created_utc: string;
  config: Config;
  samples: number;
  metrics: Metrics;
  trial: {condition: string; batch_id: string; seed: number} | null;
  error?: string;
  provenance: Record<string, string>;
  download_url: string;
  trajectory?: number[][];
};
