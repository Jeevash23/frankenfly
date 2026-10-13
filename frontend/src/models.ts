import type {Condition, Config, Dynamics, Intervention, NeuralModel, Protocol} from './types.ts';
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
};

// Switching models starts a fresh run without interventions the new model does not have.
export function configForModel(config: Config, model: NeuralModel): Config {
  return {...config, neural_model: model, initial_interventions: noInterventions};
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
// conditions need a circuit that contains DNa02.
export function conditionsFor(model: NeuralModel, hasDNa02 = true): Condition[] {
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
      ).filter((c) => hasDNa02 || !DNA02_CONDITIONS.includes(c));
}

// Mirrors the server's comparison rules so problems read as plain sentences.
export function conditionProblem(
  conditions: Condition[],
  model: NeuralModel,
  cellType: string,
  hasDNa02 = true,
): string | null {
  if (!conditions.length) return 'Select at least one condition.';
  if (conditions.length > 4) return 'Choose at most four conditions.';
  const allowed = conditionsFor(model, hasDNa02);
  const other = conditions.find((c) => !allowed.includes(c));
  if (other)
    return DNA02_CONDITIONS.includes(other) && model === 'connectome'
      ? `“${conditionNames[other]}” needs a circuit that contains DNa02.`
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
