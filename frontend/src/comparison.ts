import type {
  Condition,
  CustomCondition,
  CustomParameter,
  Intervention,
  NeuralModel,
} from './types.ts';
import {conditionNames, noInterventions} from './models.ts';
import {manipulations, overlapProblem} from './interventions.ts';

// Custom comparison conditions (BatchRequest.custom_conditions): a label with its own interventions
// and/or a few live-editable connectome parameters. The server validates every trial in full.

export const LABEL_LIMIT = 40;

// The connectome parameters a custom condition can change here: [field, label, min, max, step].
export const CUSTOM_PARAMETERS: readonly (readonly [
  CustomParameter,
  string,
  number,
  number,
  number,
])[] = [
  ['output_gain', 'Output gain', 0, 20, 0.1],
  ['input_gain', 'Input gain', 0, 10, 0.1],
  ['tonic_drive', 'Tonic drive', 0, 1, 0.05],
  ['motor_delay_ms', 'Motor delay (ms)', 0, 500, 5],
  ['motor_tau_ms', 'Motor low-pass τ (ms)', 0, 1000, 5],
];

export function newCustomCondition(existing: CustomCondition[]): CustomCondition {
  const labels = new Set(existing.map((c) => c.label));
  let n = existing.length + 1;
  while (labels.has(`Condition ${n}`)) n += 1;
  return {label: `Condition ${n}`, interventions: null, connectome_parameters: null};
}

const isDefault = (interventions: Intervention) =>
  !interventions.zero_left &&
  !interventions.zero_right &&
  interventions.silence === 'none' &&
  !manipulations(interventions).length;

// The condition as the server takes it: no interventions → null, no parameter changes → null.
export function customRequest(condition: CustomCondition): CustomCondition {
  const interventions =
    condition.interventions && !isDefault(condition.interventions)
      ? {...noInterventions, ...condition.interventions}
      : null;
  const parameters = Object.keys(condition.connectome_parameters ?? {}).length
    ? condition.connectome_parameters
    : null;
  return {label: condition.label.trim(), interventions, connectome_parameters: parameters};
}

// Mirrors the server's rules for custom conditions, as one plain sentence, or null.
export function customProblem(customs: CustomCondition[], model: NeuralModel): string | null {
  const labels = customs.map((c) => c.label.trim());
  for (const [i, custom] of customs.entries()) {
    const label = labels[i];
    const name = label ? `Custom condition “${label}”` : `Custom condition ${i + 1}`;
    if (!label) return `Give custom condition ${i + 1} a label.`;
    if (label.length > LABEL_LIMIT) return `${name}: use at most ${LABEL_LIMIT} characters.`;
    if (/[\x00-\x1f\x7f]/.test(label)) return `${name}: use letters, digits and punctuation only.`;
    if (Object.hasOwn(conditionNames, label))
      return `“${label}” is the name of a built-in condition (${conditionNames[label as Condition]}). Choose another label.`;
    if (labels.indexOf(label) !== i)
      return `Give each custom condition its own label: “${label}” is used twice.`;
    const interventions = custom.interventions;
    if (interventions) {
      if (model === 'engineered' && manipulations(interventions).length)
        return `${name} manipulates cell types, which needs the connectome model. Select it on the Workbench first.`;
      if (model === 'connectome' && interventions.silence !== 'none')
        return `${name} silences a group of the engineered model; with the connectome model, manipulate cell types instead.`;
      const overlap = overlapProblem(interventions);
      if (overlap) return `${name}: ${overlap}`;
    }
    if (Object.keys(custom.connectome_parameters ?? {}).length && model !== 'connectome')
      return `${name} changes connectome parameters; select the connectome model first.`;
    for (const [field, value] of Object.entries(custom.connectome_parameters ?? {})) {
      const spec = CUSTOM_PARAMETERS.find(([key]) => key === field);
      if (spec && !(value >= spec[2] && value <= spec[3]))
        return `${name}: ${spec[1].toLowerCase()} takes ${spec[2]} to ${spec[3]}.`;
    }
  }
  return null;
}

// The seeds typed as "42, 43", or the problem with them.
export function parseSeeds(text: string): {seeds: number[]} | {problem: string} {
  const parts = text.split(',').map((x) => x.trim());
  const seeds = parts.map(Number);
  if (
    parts.some((x) => !/^\d+$/.test(x)) ||
    seeds.length > 5 ||
    seeds.some((x) => !Number.isSafeInteger(x) || x > 2147483647)
  )
    return {problem: 'Enter one to five whole-number seeds, separated by commas.'};
  if (new Set(seeds).size !== seeds.length) return {problem: 'Use each seed only once.'};
  return {seeds};
}

// A comparison runs at most 30,000 control intervals (300 simulated seconds) in all.
export const INTERVAL_LIMIT = 30000;
export function sizeProblem(
  durationSteps: number,
  seeds: number,
  conditions: number,
): string | null {
  const total = durationSteps * seeds * conditions;
  return total > INTERVAL_LIMIT
    ? `${seeds} ${seeds === 1 ? 'seed' : 'seeds'} × ${conditions} conditions × ${durationSteps / 100} s is ${total / 100} simulated seconds; a comparison is limited to ${INTERVAL_LIMIT / 100}. Use fewer seeds or conditions, or a shorter protocol.`
    : null;
}

// One line describing what a custom condition changes.
export function customSummary(condition: CustomCondition): string {
  const parts: string[] = [];
  const i = condition.interventions;
  if (i?.zero_left) parts.push('left sensor off');
  if (i?.zero_right) parts.push('right sensor off');
  if (i && i.silence !== 'none') parts.push(`${i.silence} units silenced`);
  for (const m of manipulations(i))
    parts.push(`${m.name}${m.side === 'both' ? '' : ` ${m.side}`} ${m.mode}`);
  for (const [field, value] of Object.entries(condition.connectome_parameters ?? {})) {
    const spec = CUSTOM_PARAMETERS.find(([key]) => key === field);
    parts.push(`${spec ? spec[1].toLowerCase() : field} ${value}`);
  }
  return parts.length ? parts.join(' · ') : 'the configuration unchanged';
}
