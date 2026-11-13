import type {Config, Job} from './types.ts';
import {jobActive} from './jobs.ts';

// Validation scorecards (GET /api/scorecards): published perturbation → behavior results, scored
// per model by scripts/toolkit.py scorecard or a background job (POST /api/scorecards/run).

export type ScorecardStatus =
  'pass' | 'partial' | 'fail' | 'inconclusive' | 'not_testable' | 'blocked' | 'error';
export type ScorecardSource = {citation: string; doi: string; url: string; finding: string};
export type ScorecardTest = {
  id: string;
  title: string;
  source: ScorecardSource;
  manipulation: string;
  measure: string;
  rule: string;
  caveats: string[];
  cell_types: string[][];
  needs: string[];
};
export type ScorecardResult = {
  id: string;
  title: string;
  status: ScorecardStatus;
  source: ScorecardSource;
  rule: string;
  cell_types: string[];
  measured: ({text: string; value: number | null; unit: string} & Record<string, unknown>) | null;
  reasons: string[];
  by_construction: string | null;
  caveats: string[];
  trials?: number;
};
export type Scorecard = {
  key: string;
  version: number;
  created: string;
  engine: 'toy' | 'flygym';
  seeds: number[];
  duration_s: number;
  model: {
    neural_model: 'engineered' | 'connectome';
    circuit: string | null;
    dynamics: 'rate' | 'spiking' | null;
    readout_types: string[];
    label: string;
  };
  summary: Record<ScorecardStatus, number> & {scored: number; text: string};
  tests: ScorecardResult[];
  trial_count: number;
};
export type ScorecardListing = {version: number; tests: ScorecardTest[]; scorecards: Scorecard[]};
export type ScorecardRequest = {
  model: 'engineered' | 'connectome';
  circuit: string | null;
  dynamics: 'rate' | 'spiking';
  engine: 'toy' | 'flygym';
};

export const STATUS_TEXT: Record<ScorecardStatus, string> = {
  pass: 'Pass',
  partial: 'Partial',
  fail: 'Fail',
  inconclusive: 'Inconclusive',
  not_testable: 'Not testable',
  blocked: 'Blocked',
  error: 'Did not run',
};
// A symbol beside each word, so a status never reads by color alone.
export const STATUS_MARK: Record<ScorecardStatus, string> = {
  pass: '✓',
  partial: '◐',
  fail: '✗',
  inconclusive: '?',
  not_testable: '–',
  blocked: '⊘',
  error: '!',
};

// The request that scores the model the Workbench has loaded.
export function requestFor(config: Config | undefined, engine: 'toy' | 'flygym'): ScorecardRequest {
  const connectome = config?.neural_model === 'connectome';
  return {
    model: connectome ? 'connectome' : 'engineered',
    circuit: connectome ? config!.connectome_parameters.circuit : null,
    dynamics: connectome ? config!.connectome_parameters.dynamics : 'rate',
    engine,
  };
}

// The scorecard file name the server gives that request's model (scorecard.Target.key, without
// custom settings).
export function keyFor(r: ScorecardRequest): string {
  return r.model === 'engineered'
    ? `engineered-${r.engine}`
    : `connectome-${r.circuit}-${r.dynamics}-${r.engine}`;
}

// The card to show first: the requested key if it was scored, else the newest.
export function pickCard(cards: Scorecard[], key: string | null): Scorecard | null {
  return cards.find((c) => c.key === key) ?? cards[0] ?? null;
}

// Scorecard jobs that finished between two listings, so the panel reloads its cards.
export function finishedScorecards(before: Job[], after: Job[]): number {
  const settled = new Set(before.filter((j) => !jobActive(j)).map((j) => j.id));
  return after.filter((j) => j.kind === 'scorecard' && !jobActive(j) && !settled.has(j.id)).length;
}

// "fafb783-dna02 · rate · toy body".
export function cardLabel(card: Scorecard): string {
  return `${card.model.label} · ${card.engine === 'toy' ? 'toy body' : 'FlyGym body'}`;
}

// What the result cell says: the measured number, or why there is none.
export function resultDetail(result: ScorecardResult): string {
  if (result.measured) return result.measured.text;
  return result.reasons.join('; ') || 'No measurement.';
}
