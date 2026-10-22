// The server's shapes come from api.gen.ts, generated from the API models by scripts/gen_types.py;
// a model change that breaks the UI fails the typecheck. Some keep the names the UI has always
// used. Shapes the server does not describe (jobs, presets, the circuit list, build status) and
// UI-only types are written out below.
import type {
  BatchRequest,
  CellTypeIntervention,
  ConnectomeParameters,
  Event,
  Interventions,
  ReplayVerdict,
  RunConfig,
  RunItem,
  RunMetrics,
  Stimulus,
} from './api.gen';

export type {
  Batch,
  BatchRequest,
  CellTypeIntervention,
  ConnectomeLive,
  ConnectomeParameters,
  NeuralParameters,
  PresetRequest,
  Protocol,
  ProtocolEvent,
  Sample,
  State,
  Stimulus,
} from './api.gen';

export type Config = RunConfig;
export type Engine = Config['engine'];
export type NeuralModel = Config['neural_model'];
// An engineered manipulation of one cell type on one side or both (connectome model only).
// scale: output × value (0–2); activate: rate clamped to value (rate, 0–1) or Poisson input at
// value Hz (spiking, 0–500); silence ignores value.
export type Side = CellTypeIntervention['side'];
export type ManipulationMode = CellTypeIntervention['mode'];
// silence is the engineered six-unit model's; silence_dna02, silence_types and cell_types the
// connectome model's. At most one entry per side of a cell type ("both" covers left and right;
// silence_types and silence_dna02 count too); the server refuses overlaps.
export type Intervention = Interventions;
// A change to the live interventions: fields to set, or a function of the newest interventions
// (including a change still in flight), for toggles and list edits.
export type StimulusChange = Partial<Stimulus> | ((current: Stimulus) => Partial<Stimulus>);
export type InterventionChange =
  Partial<Intervention> | ((current: Intervention) => Partial<Intervention>);
export type Dynamics = ConnectomeParameters['dynamics'];
export type Metrics = RunMetrics;
export type Condition = NonNullable<BatchRequest['conditions']>[number];
export type RunEvent = Event;
export type Command = (path: string, body?: unknown) => Promise<any>;

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
    // The cap was applied per cell type and side (v0.6; absent from older servers).
    balance_sides?: boolean;
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
// A labelled comparison condition of your own as the editor holds it; customRequest turns it
// into BatchRequest.custom_conditions.
export type CustomCondition = {
  label: string;
  interventions: Intervention | null;
  // Live-editable connectome parameters only (not circuit, dynamics or populations).
  connectome_parameters: Partial<Record<CustomParameter, number>> | null;
};
export type CustomParameter =
  'output_gain' | 'input_gain' | 'tonic_drive' | 'motor_delay_ms' | 'motor_tau_ms';
// A saved run (GET /api/runs); GET /api/runs/{key} adds its decimated trajectory
// ([time_s, x_mm, y_mm, speed_mm_s]). Older runs may lack configuration fields added since.
export type SavedRun = Omit<RunItem, 'verified'> & {
  trajectory?: number[][];
  // The latest replay check (POST /api/runs/{key}/replay); null when never checked.
  verified: Verification | null;
};
// replay.json: the verdict fields, and what scripts/replay.py --save adds to them.
export type Verification = ReplayVerdict & {
  samples_compared?: number;
  column_errors?: Record<string, number | null>;
  software_differences?: string[];
};
// A background job: a circuit build or a replay check, in its own process (GET /api/jobs).
export type Job = {
  id: string;
  kind: 'build' | 'replay';
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  label: string;
  target: string | null;
  created: string;
  started: string | null;
  finished: string | null;
  progress: number | null;
  log_tail: string[];
  result: unknown;
  error: string | null;
};
// One entry of GET /api/configs.
export type PresetInfo = {
  name: string;
  source: 'shipped' | 'local';
  description: string;
  available: boolean;
  reason?: string;
  error?: string;
};
