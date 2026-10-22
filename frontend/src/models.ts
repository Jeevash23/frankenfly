import type {
  Condition,
  Config,
  ConnectomeParameters,
  Dynamics,
  Intervention,
  NeuralModel,
  Protocol,
} from './types.ts';
import {preset} from './protocol.ts';

export const modelNames: Record<NeuralModel, string> = {
  engineered: 'Engineered six-unit loop',
  connectome: 'Connectome circuit',
};

// The same names inside running text.
export const modelPhrases: Record<NeuralModel, string> = {
  engineered: 'engineered six-unit loop',
  connectome: 'connectome circuit',
};

// What drives the fly, in one line each. Kept next to the selector and in the header.
export const modelDrivers: Record<NeuralModel, string> = {
  engineered: 'Six engineered rate units with hand-chosen weights',
  connectome:
    'FlyWire v783 wiring · data-derived connections, assumed signs, engineered input and readout',
};

// Runs recorded with v0.3 call the connectome model "connectome_dna02".
export function normalizeModel(model: string | undefined): NeuralModel {
  return model === 'connectome' || model === 'connectome_dna02' ? 'connectome' : 'engineered';
}

export const dynamicsNames: Record<Dynamics, string> = {
  rate: 'Rate units (engineered)',
  spiking: 'Spiking (Shiu et al. 2024 neuron model)',
};

export const dynamicsLabels: Record<Dynamics, string> = {
  rate: 'engineered',
  spiking: 'published LIF model',
};

// A fresh connectome run on another circuit or dynamics. A new circuit starts from its own
// default readout and input populations.
export function configForCircuit(config: Config, circuit: string, dynamics: Dynamics): Config {
  const same = config.connectome_parameters.circuit === circuit;
  return {
    ...config,
    neural_model: 'connectome',
    initial_interventions: noInterventions,
    connectome_parameters: {
      ...config.connectome_parameters,
      circuit,
      dynamics,
      ...(same ? {} : {readout_types: null, input_types: null, speed_types: []}),
    },
  };
}

// Which recorded rates belong to each readout cell type: the server lists L then R per type.
export function readoutPairs(
  readoutTypes: string[],
): {name: string; left: number; right: number}[] {
  return readoutTypes.map((name, k) => ({name, left: 2 * k, right: 2 * k + 1}));
}

export const noInterventions: Intervention = {
  zero_left: false,
  zero_right: false,
  silence: 'none',
  silence_dna02: 'none',
  silence_types: [],
  cell_types: [],
};

// The reset that switches models. FlyVis eyes drive only the connectome model's visual neurons, so
// leaving the connectome model with them selected also switches to rendered compound eyes (FlyVis
// already needs the FlyGym body they use), and says so.
export function modelSwitch(
  config: Pick<Config, 'sensor_model'>,
  model: NeuralModel,
): {override: Partial<Config>; note: string | null} {
  const leaveFlyVis = model !== 'connectome' && config.sensor_model === 'flyvis';
  return {
    override: {neural_model: model, ...(leaveFlyVis ? {sensor_model: 'vision' as const} : {})},
    note: leaveFlyVis
      ? 'FlyVis eyes drive only the connectome model, so the sensor switched to rendered compound eyes.'
      : null,
  };
}

// Switching models starts a fresh run without interventions the new model does not have.
export function configForModel(config: Config, model: NeuralModel): Config {
  return {
    ...config,
    ...modelSwitch(config, model).override,
    initial_interventions: noInterventions,
  };
}

// What a connectome circuit summary depends on: the circuit file and the structural parameters.
// Gains, tonic drive, time constants and dynamics change the activity, not the summary, so editing
// them keeps the cached summary. Without a hash (servers before v0.6) a rebuilt circuit keeps its
// key; the cache is then cleared when a build completes.
export function summaryKey(parameters: ConnectomeParameters, sha256?: string | null): string {
  return JSON.stringify([
    parameters.circuit,
    sha256 ?? '',
    parameters.synapse_threshold,
    parameters.other_transmitters,
    parameters.readout_types,
    parameters.input_types,
    parameters.speed_types,
  ]);
}

// The neural stage of the loop, named for the model that runs it.
export function neuralStage(
  config: Pick<Config, 'neural_model'> & {
    connectome_parameters?: Pick<ConnectomeParameters, 'dynamics'>;
  },
): string {
  if (config.neural_model !== 'connectome') return '6 rate units';
  return config.connectome_parameters?.dynamics === 'spiking'
    ? 'Connectome circuit · spiking'
    : 'Connectome circuit · rate';
}

export const conditionNames: Record<Condition, string> = {
  control: 'Neural control',
  left_sensor_off: 'Left sensor off',
  descending_off: 'Descending units off',
  baseline: 'Controller baseline',
  engineered_model: 'Engineered model',
  connectome_model: 'Connectome model',
  dna02_left_off: 'DNa02 left off',
  dna02_right_off: 'DNa02 right off',
  dna02_both_off: 'Both DNa02 off',
  cell_type_off: 'A cell type off',
};

const DNA02_CONDITIONS: Condition[] = ['dna02_left_off', 'dna02_right_off', 'dna02_both_off'];

// The conditions a comparison can hold for each selected model, in display order. DNa02
// conditions need a circuit that contains DNa02; the engineered model cannot use FlyVis eyes.
export function conditionsFor(
  model: NeuralModel,
  hasDNa02 = true,
  sensor: Config['sensor_model'] = 'geometric',
): Condition[] {
  return model === 'engineered'
    ? ['control', 'left_sensor_off', 'descending_off', 'baseline', 'connectome_model']
    : (
        [
          'control',
          'left_sensor_off',
          ...DNA02_CONDITIONS,
          'cell_type_off',
          'baseline',
          'engineered_model',
        ] as Condition[]
      ).filter(
        (c) =>
          (hasDNa02 || !DNA02_CONDITIONS.includes(c)) &&
          (sensor !== 'flyvis' || c !== 'engineered_model'),
      );
}

// Built-in conditions per comparison, and conditions in all, built-in and custom together.
export const MAX_BUILT_IN = 4;
export const MAX_CONDITIONS = 6;

// A trial's condition for display: a built-in condition's name, or a custom condition's label.
export function conditionName(condition: string): string {
  return conditionNames[condition as Condition] ?? condition;
}

// Mirrors the server's comparison rules so problems read as plain sentences. `custom` is the
// number of custom conditions, which count towards the limit and may stand alone.
export function conditionProblem(
  conditions: Condition[],
  model: NeuralModel,
  cellType: string,
  hasDNa02 = true,
  sensor: Config['sensor_model'] = 'geometric',
  custom = 0,
): string | null {
  if (!conditions.length && !custom) return 'Select at least one condition.';
  if (conditions.length > MAX_BUILT_IN) return 'Choose at most four built-in conditions.';
  if (conditions.length + custom > MAX_CONDITIONS)
    return `A comparison has at most ${MAX_CONDITIONS} conditions, built-in and custom together.`;
  const allowed = conditionsFor(model, hasDNa02, sensor);
  const other = conditions.find((c) => !allowed.includes(c));
  if (other)
    return DNA02_CONDITIONS.includes(other) && model === 'connectome'
      ? `“${conditionNames[other]}” needs a circuit that contains DNa02.`
      : other === 'engineered_model' && sensor === 'flyvis'
        ? `“${conditionNames[other]}” cannot use FlyVis eyes. Choose another sensor on the Workbench first.`
        : `“${conditionNames[other]}” is not available with the ${modelPhrases[model]}.`;
  if (conditions.includes('cell_type_off') && !cellType.trim())
    return 'Choose the cell type to silence.';
  return null;
}

// The walkthrough in docs/RESEARCH.md: a target reversal, two seeds, the intact loop
// against the loop without its steering output.
export function firstExperiment(
  model: NeuralModel,
  hasDNa02 = true,
): {
  protocol: Protocol;
  seeds: string;
  conditions: Condition[];
} {
  return {
    protocol: preset('Target reversal', 2),
    seeds: '42, 43',
    conditions: [
      'control',
      model === 'engineered' ? 'descending_off' : hasDNa02 ? 'dna02_both_off' : 'left_sensor_off',
    ],
  };
}

// Plain words for a real-time factor below 1×, or null when there is nothing to say.
export function slowdownNote(factor: number, requested: number, running: boolean): string | null {
  if (!running || !(factor > 0) || factor >= 0.995) return null;
  const seconds = 1 / factor;
  const pace = `Slower than real time: 1 simulated second takes ${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s.`;
  return factor < requested * 0.9
    ? `${pace} The requested ${requested}× is more than this computer can keep up with.`
    : `${pace} That is the requested ${requested}× speed.`;
}

// Trace groups of the signals panel; 'readout:K' is the K-th readout type's left/right pair.
export type TraceGroup =
  'descending' | 'sensory' | 'steering' | `readout:${number}` | 'input' | 'types';

// Where each trace group starts in a sample's rates, given the number of readout types.
export function groupIndex(group: TraceGroup, readouts: number): number {
  if (group.startsWith('readout:')) return 2 * Number(group.slice(8));
  if (group === 'input') return 2 * readouts;
  return {sensory: 0, steering: 2, descending: 4, types: 0}[group as 'sensory'] ?? 0;
}

// A warning when the connectome model's motor command is clipped most of the time, or null.
export const CLIPPING_WARNING = 0.5;
export function clippingNote(fraction: number | null | undefined): string | null {
  if (fraction === undefined || fraction === null || !(fraction > CLIPPING_WARNING)) return null;
  return `The motor command was clipped to its range in ${Math.round(fraction * 100)}% of control intervals, so turning is saturated: the legs follow the sign of the turn, not its size.`;
}
