export type Engine = 'flygym' | 'toy';
export type NeuralModel = 'engineered' | 'connectome';
export type Stimulus = {x: number; y: number; intensity: number};
export type Intervention = {
  zero_left: boolean;
  zero_right: boolean;
  // Engineered six-unit model only.
  silence: 'none' | 'sensory' | 'steering' | 'descending' | 'all';
  // Connectome model only.
  silence_dna02?: 'none' | 'left' | 'right' | 'both';
  silence_types?: string[];
};
// A change to the live interventions: fields to set, or a function of the newest interventions
// (including a change still in flight), for toggles and list edits.
export type InterventionChange =
  Partial<Intervention> | ((current: Intervention) => Partial<Intervention>);
export type NeuralParameters = {
  sensory_gain: number;
  steering_gain: number;
  tonic_drive: number;
  time_scale: number;
};
export type Dynamics = 'rate' | 'spiking';
// Spiking constants follow Shiu et al. 2024; these are the closed-loop input and readout settings.
export type SpikingParameters = {
  synapse_weight_mv: number;
  input_rate_hz: number;
  rate_window_ms: number;
  rate_scale_hz: number;
};
// Global settings of the connectome model; nothing addresses a single neuron or synapse.
export type ConnectomeParameters = {
  circuit: string;
  dynamics: Dynamics;
  synapse_threshold: number;
  global_gain: number;
  input_gain: number;
  output_gain: number;
  tonic_drive: number;
  tau_ms: number;
  other_transmitters: 'excluded' | 'excitatory';
  // Populations by cell type; null means the circuit's default readout or every visual projection neuron.
  readout_types: string[] | null;
  input_types: string[] | null;
  speed_types: string[];
  speed_gain: number;
  spiking: SpikingParameters;
};
// One entry of /api/connectome/circuits.
export type CircuitInfo = {
  name: string;
  title?: string;
  committed?: boolean;
  format?: string;
  neurons?: number;
  connections?: number;
  cell_types?: number;
  seeds?: string[];
  readout_types?: string[];
  build?: {
    synapse_threshold?: number;
    hops?: number | null;
    neuron_cap?: number | null;
    whole_brain?: boolean | null;
  };
  coverage?: string;
  license?: string;
  bytes?: number;
  sha256?: string;
  error?: string;
};
export type BuildStatus = {
  status: 'idle' | 'running' | 'done' | 'failed';
  name?: string;
  exit_code?: number;
  result?: {name: string; neurons: number; connections: number; cell_types: number} | null;
  log: string[];
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
  sensor_model: 'geometric' | 'vision' | 'flyvis';
  neural_model: NeuralModel;
  neural_parameters: NeuralParameters;
  connectome_parameters: ConnectomeParameters;
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
export type Condition =
  | 'control'
  | 'left_sensor_off'
  | 'descending_off'
  | 'baseline'
  | 'engineered_model'
  | 'connectome_model'
  | 'dna02_left_off'
  | 'dna02_right_off'
  | 'dna02_both_off'
  | 'cell_type_off';
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
  cell_type?: string | null;
};
// Live, display-only activity of the connectome model (not recorded).
export type ConnectomeLive = {
  circuit: string;
  // SHA-256 of the circuit file loaded in the running model; absent from servers before v0.6.
  circuit_sha256?: string;
  dynamics: Dynamics;
  unit_names: string[];
  readout_types: string[];
  type_rates: number[];
  turn: number;
  silenced_neurons: number;
  trace_t: number[];
  top_types: {index: number; name: string; trace: number[]}[];
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
  connectome: ConnectomeLive | null;
};
export type Command = (path: string, body?: unknown) => Promise<any>;
export type SavedRun = {
  key: string;
  run_id: string;
  created_utc: string;
  config: Config;
  samples: number;
  metrics: Metrics;
  trial: {
    condition: string;
    batch_id: string;
    seed: number;
    neural_model?: NeuralModel;
    cell_type?: string | null;
  } | null;
  error?: string;
  provenance: Record<string, string>;
  download_url: string;
  trajectory?: number[][];
};
