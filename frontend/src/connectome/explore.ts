// Pure helpers for the connectivity explorer (GET /api/explore/*). The server validates again.
import type {CellTypeIntervention, Dynamics, Side, State} from '../types.ts';
import {valueRange} from '../interventions.ts';
import {defaultBuild, type BuildRequest} from './build.ts';

export type Query = 'partners' | 'paths' | 'influence';
export const QUERIES: readonly Query[] = ['partners', 'paths', 'influence'];
export const queryNames: Record<Query, string> = {
  partners: 'Partners',
  paths: 'Paths',
  influence: 'Influence',
};

// How many neurons of a cell type the running circuit has on each side, as the server reports it;
// null when the type is not in the running circuit or no connectome circuit is running.
export type InCircuit = {neurons: number; left: number; right: number} | null;

export type TypeRow = {
  cell_type: string;
  super_class: string;
  in_running_circuit: InCircuit;
  [key: string]: unknown;
};
export type NeuronRow = TypeRow & {id: string; side: string; transmitter: string};

export type ExploreForm = {
  graph: string;
  threshold: number;
  query: string;
  side: Side;
  direction: 'upstream' | 'downstream';
  group: 'cell_type' | 'neuron';
  source: string;
  target: string;
  mode: 'strongest' | 'shortest';
  level: 'cell_type' | 'neuron';
  maxHops: number;
  influenceDirection: 'from' | 'onto';
  signed: boolean;
  limit: number;
};

export const defaultForm: ExploreForm = {
  graph: 'brain',
  threshold: 5,
  query: 'DNa02',
  side: 'both',
  direction: 'upstream',
  group: 'cell_type',
  source: 'LC10a',
  target: 'DNa02',
  mode: 'strongest',
  level: 'cell_type',
  maxHops: 10,
  influenceDirection: 'onto',
  signed: true,
  limit: 25,
};

// The URL of one query, from the form.
export function queryUrl(kind: Query, form: ExploreForm): string {
  const common = {graph: form.graph, threshold: String(form.threshold), limit: String(form.limit)};
  let params: Record<string, string>;
  if (kind === 'partners')
    params = {
      ...common,
      query: form.query,
      side: form.side,
      direction: form.direction,
      group: form.group,
    };
  else if (kind === 'paths')
    params = {
      ...common,
      limit: String(Math.min(form.limit, 50)),
      source: form.source,
      target: form.target,
      mode: form.mode,
      level: form.level,
      max_hops: String(form.maxHops),
    };
  else
    params = {
      ...common,
      query: form.query,
      side: form.side,
      direction: form.influenceDirection,
      group: form.group,
      signed: String(form.signed),
    };
  return `/api/explore/${kind}?${new URLSearchParams(params)}`;
}

// A plain-language problem with the form for one query, or null when it can be sent.
export function formProblem(kind: Query, form: ExploreForm): string | null {
  if (!Number.isInteger(form.threshold) || form.threshold < 1 || form.threshold > 1000)
    return 'The synapse threshold is a whole number from 1 to 1000.';
  if (!Number.isInteger(form.limit) || form.limit < 1 || form.limit > 500)
    return 'Show 1 to 500 rows.';
  if (kind === 'paths') {
    if (!form.source.trim() || !form.target.trim()) return 'Give a source and a target.';
    if (form.source.trim() === form.target.trim()) return 'The source and target are the same.';
    if (!Number.isInteger(form.maxHops) || form.maxHops < 1 || form.maxHops > 20)
      return 'Paths take 1 to 20 steps.';
    return null;
  }
  return form.query.trim() ? null : 'Give a cell type or a FlyWire root ID.';
}

// The side a row's manipulation addresses: a neuron's own side, or both sides of a cell type.
export function rowSide(row: {side?: unknown}): Side {
  return row.side === 'left' || row.side === 'right' ? row.side : 'both';
}

// Why a row's cell type cannot be manipulated in the Workbench now, or null when it can.
export function manipulationBlocker(
  state: State | null,
  cellType: string,
  side: Side,
  inCircuit: InCircuit,
): string | null {
  if (!state) return 'Not connected to the simulation.';
  if (state.config.neural_model !== 'connectome')
    return 'The Workbench runs the engineered model. Switch to a connectome circuit to manipulate cell types.';
  const circuit = state.config.connectome_parameters.circuit;
  if (!inCircuit)
    return `${cellType} is not in the running circuit (${circuit}). Build a circuit around it first.`;
  if (side !== 'both' && !inCircuit[side])
    return `The running circuit (${circuit}) has no ${side} ${cellType} neurons.`;
  return null;
}

// The manipulation a row's Silence or Activate button sets, at the Workbench's default activation.
export function rowManipulation(
  cellType: string,
  side: Side,
  mode: 'silence' | 'activate',
  dynamics: Dynamics,
): CellTypeIntervention {
  return {
    name: cellType,
    side,
    mode,
    value: mode === 'silence' ? 0 : (valueRange('activate', dynamics)?.initial ?? 0.6),
  };
}

// A local circuit name from seeds: "lc10a-dna02", lower case, at most 64 characters.
export function circuitName(seeds: string[]): string {
  const base = seeds
    .map((s) =>
      s
        .toLowerCase()
        .replace(/[^a-z0-9._-]+/g, '-')
        .replace(/^-+|-+$/g, ''),
    )
    .filter(Boolean)
    .join('-')
    .slice(0, 48)
    .replace(/-+$/, '');
  return /^[a-z0-9]/.test(base) ? `${base}-circuit` : 'explorer-circuit';
}

// The builder's form with these seeds, keeping the other settings of an unsent build draft.
export function buildDraft(
  seeds: string[],
  previous: BuildRequest | null | undefined,
): {request: BuildRequest; seedDraft: string} {
  const unique = [...new Set(seeds.map((s) => s.trim()).filter(Boolean))].slice(0, 20);
  return {
    request: {...defaultBuild, ...(previous ?? {}), name: circuitName(unique), seeds: unique},
    seedDraft: '',
  };
}

export type NeuroglancerGroup = {
  label: string;
  ids?: string[];
  cell_type?: string;
  side?: Side;
  color?: string;
};

// Neuroglancer groups for a set of result rows: neurons by ID, cell types by name (one layer each).
export function rowGroups(rows: (TypeRow | NeuronRow)[], max = 12): NeuroglancerGroup[] {
  const neurons = rows.filter((r): r is NeuronRow => typeof r.id === 'string');
  if (neurons.length) return [{label: 'neurons', ids: neurons.map((r) => r.id)}];
  return rows.slice(0, max).map((r) => ({label: r.cell_type, cell_type: r.cell_type}));
}

// Neuroglancer groups for a path: its neurons, or each cell type on it.
export function pathGroups(path: {
  cell_types: string[];
  neurons?: {id: string; cell_type: string}[];
}): NeuroglancerGroup[] {
  if (path.neurons)
    return path.neurons.map((n, k) => ({label: `${k + 1}. ${n.cell_type}`, ids: [n.id]}));
  return path.cell_types.map((t, k) => ({label: `${k + 1}. ${t}`, cell_type: t}));
}

// "+", "−" or "0" for a sign.
export const signText = (sign: unknown) => (sign === 1 ? '+' : sign === -1 ? '−' : '0');

// A number for a table cell: fractions as percentages, large counts with separators.
export function percent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(value < 0.001 ? 3 : 1)}%`
    : '—';
}

export function compact(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const size = Math.abs(value);
  if (size === 0) return '0';
  if (size >= 1000 || size < 0.01) return value.toExponential(2);
  return value.toPrecision(3);
}
