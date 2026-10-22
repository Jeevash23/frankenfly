import type {
  CellTypeIntervention,
  Condition,
  CustomCondition,
  Intervention,
  Protocol,
  ProtocolEvent,
} from './types.ts';
import type {BuildRequest} from './connectome/build.ts';
import {conditionNames} from './models.ts';
import {stimulusChange} from './protocol.ts';
import {CUSTOM_PARAMETERS} from './comparison.ts';

// Unsent edits kept in this browser's localStorage, so switching pages or reloading keeps them.
// Each draft has a versioned key; a draft that cannot be read (another version, edited by hand,
// storage blocked) is ignored, never trusted. Successful submits clear their draft.

export const DRAFT_KEYS = {
  experiments: 'digitalfly.draft.experiments.v1',
  build: 'digitalfly.draft.build.v1',
  connectivity: 'digitalfly.draft.connectivity.v1',
} as const;

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

// localStorage, or null where the browser blocks it (the accessor itself can throw).
function browserStore(): Store | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function loadDraft<T>(
  key: string,
  parse: (value: unknown) => T | null,
  store: Store | null = browserStore(),
): T | null {
  try {
    const text = store?.getItem(key);
    return text ? parse(JSON.parse(text)) : null;
  } catch {
    return null;
  }
}

export function saveDraft(key: string, value: unknown, store: Store | null = browserStore()) {
  try {
    store?.setItem(key, JSON.stringify(value));
  } catch {
    // Full or blocked storage: the draft lives on in memory only.
  }
}

export function clearDraft(key: string, store: Store | null = browserStore()) {
  try {
    store?.removeItem(key);
  } catch {
    // Nothing to clear.
  }
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const isInteger = (value: unknown, min: number, max: number): value is number =>
  Number.isInteger(value) && (value as number) >= min && (value as number) <= max;
const strings = (value: unknown, limit: number): string[] =>
  Array.isArray(value) ? value.filter((v) => typeof v === 'string').slice(0, limit) : [];
const text = (value: unknown, limit: number): string | undefined =>
  typeof value === 'string' && value.length <= limit ? value : undefined;

function readStimulus(value: unknown): ProtocolEvent['stimulus'] {
  if (!isObject(value)) return null;
  const {x, y, intensity} = value;
  return isNumber(x) && isNumber(y) && isNumber(intensity) ? {x, y, intensity} : null;
}

export function readProtocol(value: unknown): Protocol | null {
  if (!isObject(value) || !Array.isArray(value.events) || value.events.length > 64) return null;
  const name = text(value.name, 80);
  if (!name || !isInteger(value.duration_steps, 1, 29999)) return null;
  const events: ProtocolEvent[] = [];
  for (const event of value.events) {
    const stimulus = isObject(event) ? readStimulus(event.stimulus) : null;
    if (!isObject(event) || !Number.isInteger(event.step) || !stimulus) return null;
    events.push(stimulusChange(event.step as number, stimulus));
  }
  return {name, duration_steps: value.duration_steps, events};
}

function readCellType(value: unknown): CellTypeIntervention | null {
  if (!isObject(value)) return null;
  const name = text(value.name, 120);
  const side = ['both', 'left', 'right'].includes(value.side as string) ? value.side : null;
  const mode = ['silence', 'scale', 'activate'].includes(value.mode as string) ? value.mode : null;
  if (!name || !side || !mode || !isNumber(value.value)) return null;
  return {name, side, mode, value: value.value} as CellTypeIntervention;
}

export function readInterventions(value: unknown): Intervention | null {
  if (!isObject(value)) return null;
  const silence = ['none', 'sensory', 'steering', 'descending', 'all'];
  const sides = ['none', 'left', 'right', 'both'];
  return {
    zero_left: value.zero_left === true,
    zero_right: value.zero_right === true,
    silence: (silence.includes(value.silence as string)
      ? value.silence
      : 'none') as Intervention['silence'],
    silence_dna02: (sides.includes(value.silence_dna02 as string)
      ? value.silence_dna02
      : 'none') as Intervention['silence_dna02'],
    silence_types: strings(value.silence_types, 32),
    cell_types: (Array.isArray(value.cell_types) ? value.cell_types : [])
      .map(readCellType)
      .filter((c): c is CellTypeIntervention => c !== null)
      .slice(0, 32),
  };
}

function readCustom(value: unknown): CustomCondition | null {
  if (!isObject(value)) return null;
  const label = text(value.label, 200);
  if (label === undefined) return null;
  const parameters: CustomCondition['connectome_parameters'] = {};
  if (isObject(value.connectome_parameters))
    for (const [field] of CUSTOM_PARAMETERS) {
      const v = value.connectome_parameters[field];
      if (isNumber(v)) parameters[field] = v;
    }
  return {
    label,
    interventions: value.interventions === null ? null : readInterventions(value.interventions),
    connectome_parameters: Object.keys(parameters).length ? parameters : null,
  };
}

export type ExperimentsDraft = {
  protocol: Protocol;
  seeds: string;
  conditions: Condition[];
  cellType: string;
  custom: CustomCondition[];
  maxSpeed: boolean;
};

// The fields of an Experiments draft that could be read; the rest keep their defaults.
export function readExperimentsDraft(value: unknown): Partial<ExperimentsDraft> | null {
  if (!isObject(value)) return null;
  const draft: Partial<ExperimentsDraft> = {};
  const protocol = readProtocol(value.protocol);
  if (protocol) draft.protocol = protocol;
  const seeds = text(value.seeds, 200);
  if (seeds !== undefined) draft.seeds = seeds;
  if (Array.isArray(value.conditions))
    draft.conditions = strings(value.conditions, 10).filter((c): c is Condition =>
      Object.hasOwn(conditionNames, c),
    );
  const cellType = text(value.cellType, 120);
  if (cellType !== undefined) draft.cellType = cellType;
  if (Array.isArray(value.custom))
    draft.custom = value.custom
      .slice(0, 6)
      .map(readCustom)
      .filter((c): c is CustomCondition => c !== null);
  if (typeof value.maxSpeed === 'boolean') draft.maxSpeed = value.maxSpeed;
  return draft;
}

export type BuildDraft = {request: BuildRequest; seedDraft: string};

export function readBuildDraft(value: unknown): BuildDraft | null {
  if (!isObject(value) || !isObject(value.request)) return null;
  const r = value.request;
  const name = text(r.name, 64);
  if (name === undefined || !isNumber(r.hops) || !isNumber(r.threshold) || !isNumber(r.cap))
    return null;
  return {
    request: {
      name,
      seeds: strings(r.seeds, 20),
      hops: r.hops,
      threshold: r.threshold,
      cap: r.cap,
      whole_brain: r.whole_brain === true,
      balance_sides: r.balance_sides === true,
    },
    seedDraft: text(value.seedDraft, 200) ?? '',
  };
}

export type ConnectivityDraft = {key: string; threshold: number; search: string};

export function readConnectivityDraft(value: unknown): ConnectivityDraft | null {
  if (!isObject(value)) return null;
  const key = text(value.key, 200);
  if (key === undefined || !isNumber(value.threshold)) return null;
  return {key, threshold: Math.max(1, value.threshold), search: text(value.search, 200) ?? ''};
}
