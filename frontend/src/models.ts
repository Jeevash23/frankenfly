import type {Condition, Config, Intervention, NeuralModel, Protocol} from './types.ts';
import {preset} from './protocol.ts';

export const modelNames: Record<NeuralModel, string> = {
  engineered: 'Engineered six-unit loop',
  connectome_dna02: 'Connectome DNa02 circuit',
};

// The same names inside running text, keeping the cell type's capitalisation.
export const modelPhrases: Record<NeuralModel, string> = {
  engineered: 'engineered six-unit loop',
  connectome_dna02: 'connectome DNa02 circuit',
};

// What drives the fly, in one line each. Kept next to the selector and in the header.
export const modelDrivers: Record<NeuralModel, string> = {
  engineered: 'Six engineered rate units with hand-chosen weights',
  connectome_dna02:
    'FlyWire v783 wiring around DNa02 · data-derived connections, assumed signs, engineered dynamics',
};

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

// The conditions a comparison can hold for each selected model, in display order.
export function conditionsFor(model: NeuralModel): Condition[] {
  return model === 'engineered'
    ? ['control', 'left_sensor_off', 'descending_off', 'baseline', 'connectome_model']
    : [
        'control',
        'left_sensor_off',
        'dna02_left_off',
        'dna02_right_off',
        'dna02_both_off',
        'cell_type_off',
        'baseline',
        'engineered_model',
      ];
}

// Mirrors the server's comparison rules so problems read as plain sentences.
export function conditionProblem(
  conditions: Condition[],
  model: NeuralModel,
  cellType: string,
): string | null {
  if (!conditions.length) return 'Select at least one condition.';
  if (conditions.length > 4) return 'Choose at most four conditions.';
  const allowed = conditionsFor(model);
  const other = conditions.find((c) => !allowed.includes(c));
  if (other) return `“${conditionNames[other]}” is not available with the ${modelPhrases[model]}.`;
  if (conditions.includes('cell_type_off') && !cellType.trim())
    return 'Choose the cell type to silence.';
  return null;
}

// The walkthrough in docs/RESEARCH.md: a target reversal, two seeds, the intact loop
// against the loop without its steering output.
export function firstExperiment(model: NeuralModel): {
  protocol: Protocol;
  seeds: string;
  conditions: Condition[];
} {
  return {
    protocol: preset('Target reversal', 2),
    seeds: '42, 43',
    conditions: ['control', model === 'engineered' ? 'descending_off' : 'dna02_both_off'],
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
