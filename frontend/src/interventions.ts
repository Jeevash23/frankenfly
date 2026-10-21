import type {
  CellTypeIntervention,
  Dynamics,
  Intervention,
  ManipulationMode,
  Side,
} from './types.ts';

// Cell-type manipulations of the connectome model (Interventions v2). The server allows one
// manipulation per side of a cell type: "both" covers left and right, a silence_types entry is the
// type silenced on both sides and silence_dna02 silences DNa02 on its side(s). Edits here replace
// what they overlap instead of adding a second entry, so a request never fails on an overlap.

// A manipulation in force, with the field it comes from.
export type Manipulation = CellTypeIntervention & {
  source: 'cell_types' | 'silence_types' | 'silence_dna02';
};

export const sideNames: Record<Side, string> = {both: 'Both sides', left: 'Left', right: 'Right'};
export const modeNames: Record<ManipulationMode, string> = {
  silence: 'Silence',
  scale: 'Scale output',
  activate: 'Activate',
};

export const overlaps = (a: Side, b: Side) => a === b || a === 'both' || b === 'both';

// What is left of `held` once `taken` is addressed by another entry; null when nothing is.
function remainder(held: Side, taken: Side): Side | null {
  if (!overlaps(held, taken)) return held;
  if (taken === 'both' || held === taken) return null;
  return taken === 'left' ? 'right' : 'left';
}

// Every cell-type manipulation, the older silencing fields included, in the order they were set.
export function manipulations(interventions: Intervention | null | undefined): Manipulation[] {
  if (!interventions) return [];
  const dna02 = interventions.silence_dna02 ?? 'none';
  return [
    ...(interventions.silence_types ?? []).map((name): Manipulation => ({
      name,
      side: 'both',
      mode: 'silence',
      value: 0,
      source: 'silence_types',
    })),
    ...(dna02 !== 'none'
      ? [{name: 'DNa02', side: dna02, mode: 'silence', value: 0, source: 'silence_dna02'} as const]
      : []),
    ...(interventions.cell_types ?? []).map((c): Manipulation => ({...c, source: 'cell_types'})),
  ];
}

// The change that sets `entry`, replacing whatever addressed the same side(s) of its cell type. The
// other side of an older two-sided entry keeps its manipulation, as an entry of its own.
export function withCellType(
  current: Intervention,
  entry: CellTypeIntervention,
): Pick<Intervention, 'cell_types' | 'silence_types' | 'silence_dna02'> {
  const {name, side} = entry;
  const cellTypes: CellTypeIntervention[] = [];
  for (const c of current.cell_types ?? []) {
    const rest = c.name === name ? remainder(c.side, side) : c.side;
    if (rest) cellTypes.push({...c, side: rest});
  }
  let silenceTypes = current.silence_types ?? [];
  if (silenceTypes.includes(name)) {
    silenceTypes = silenceTypes.filter((t) => t !== name);
    const rest = remainder('both', side);
    if (rest) cellTypes.push({name, side: rest, mode: 'silence', value: 0});
  }
  const dna02 = current.silence_dna02 ?? 'none';
  const silenceDna02 =
    name === 'DNa02' && dna02 !== 'none' ? (remainder(dna02, side) ?? 'none') : dna02;
  return {
    cell_types: [
      ...cellTypes,
      {name, side, mode: entry.mode, value: entry.mode === 'silence' ? 0 : entry.value},
    ],
    silence_types: silenceTypes,
    silence_dna02: silenceDna02,
  };
}

// The change that removes one listed manipulation.
export function withoutManipulation(
  current: Intervention,
  item: Pick<Manipulation, 'name' | 'side' | 'source'>,
): Partial<Intervention> {
  if (item.source === 'silence_types')
    return {silence_types: (current.silence_types ?? []).filter((t) => t !== item.name)};
  if (item.source === 'silence_dna02') return {silence_dna02: 'none'};
  return {
    cell_types: (current.cell_types ?? []).filter(
      (c) => !(c.name === item.name && c.side === item.side),
    ),
  };
}

// The change that restores every side of a cell type.
export function withoutCellType(current: Intervention, name: string): Partial<Intervention> {
  return {
    cell_types: (current.cell_types ?? []).filter((c) => c.name !== name),
    silence_types: (current.silence_types ?? []).filter((t) => t !== name),
    silence_dna02: name === 'DNa02' ? 'none' : (current.silence_dna02 ?? 'none'),
  };
}

// The manipulation acting on one side of a cell type, or null.
export function manipulationOn(
  interventions: Intervention | null | undefined,
  name: string,
  side: 'left' | 'right',
): Manipulation | null {
  return (
    manipulations(interventions).find((m) => m.name === name && overlaps(m.side, side)) ?? null
  );
}

// The manipulations a new entry would replace.
export function replaced(
  interventions: Intervention | null | undefined,
  name: string,
  side: Side,
): Manipulation[] {
  return manipulations(interventions).filter((m) => m.name === name && overlaps(m.side, side));
}

// Problems a set of interventions would be refused for, as a sentence, or null.
export function overlapProblem(interventions: Intervention): string | null {
  const seen: Manipulation[] = [];
  for (const m of manipulations(interventions)) {
    if (
      m.source === 'cell_types' &&
      seen.some((o) => o.name === m.name && overlaps(o.side, m.side))
    )
      return `${m.name} (${m.side}) is manipulated twice. Set one manipulation per side of a cell type.`;
    seen.push(m);
  }
  return null;
}

// The value a mode takes under the active dynamics, with its unit, as the server checks it.
export function valueRange(
  mode: ManipulationMode,
  dynamics: Dynamics,
): {min: number; max: number; step: number; initial: number; unit: string} | null {
  if (mode === 'scale') return {min: 0, max: 2, step: 0.05, initial: 0.5, unit: '×'};
  if (mode === 'activate')
    return dynamics === 'spiking'
      ? {min: 0, max: 500, step: 5, initial: 80, unit: 'Hz'}
      : {min: 0, max: 1, step: 0.05, initial: 0.6, unit: 'rate'};
  return null;
}

// Plain-language problem with a value for a mode, or null.
export function valueProblem(
  mode: ManipulationMode,
  value: number,
  dynamics: Dynamics,
): string | null {
  const range = valueRange(mode, dynamics);
  if (!range) return null;
  if (!Number.isFinite(value) || value < range.min || value > range.max)
    return mode === 'scale'
      ? 'Scaling multiplies the output by 0 to 2.'
      : dynamics === 'spiking'
        ? 'Activation with spiking dynamics takes 0 to 500 Hz.'
        : 'Activation with rate dynamics clamps the rate to 0 to 1.';
  return null;
}

// Plain-language problem with a manipulation about to be set, or null. `type` is the cell type's
// neuron counts when the circuit summary lists it; `complete` says whether the summary lists every
// type (large circuits list only the types nearest the readout, and the server checks the rest).
export function entryProblem(
  entry: CellTypeIntervention,
  dynamics: Dynamics,
  type: {left: number; right: number} | undefined,
  complete: boolean,
): string | null {
  if (!entry.name.trim()) return 'Choose a cell type.';
  if (!type && complete) return 'Not a cell type in this circuit. Pick one from the suggestions.';
  if (type && entry.side !== 'both' && !type[entry.side])
    return `${entry.name} has no ${entry.side} neurons in this circuit.`;
  return valueProblem(entry.mode, entry.value, dynamics);
}

// "DNa02 left silenced", "DNa03 output ×0.5", "DNp09 activated 80 Hz", as the server labels them.
export function manipulationLabel(m: CellTypeIntervention, dynamics: Dynamics): string {
  const target = m.side === 'both' ? m.name : `${m.name} ${m.side}`;
  if (m.mode === 'silence') return `${target} silenced`;
  if (m.mode === 'scale') return `${target} output ×${m.value}`;
  return `${target} activated ${dynamics === 'spiking' ? `${m.value} Hz` : `(rate ${m.value})`}`;
}

// How many interventions are in force, for the panel heading.
export function activeInterventions(interventions: Intervention | null | undefined): number {
  if (!interventions) return 0;
  return (
    (interventions.zero_left ? 1 : 0) +
    (interventions.zero_right ? 1 : 0) +
    (interventions.silence !== 'none' ? 1 : 0) +
    manipulations(interventions).length
  );
}

// "12 silenced · 4 scaled" from the snapshot's neuron counts, or null when none are manipulated.
export function neuronCounts(
  counts: {silence: number; scale: number; activate: number} | undefined,
): string | null {
  if (!counts) return null;
  const parts = [
    counts.silence ? `${counts.silence} silenced` : '',
    counts.scale ? `${counts.scale} scaled` : '',
    counts.activate ? `${counts.activate} activated` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}
