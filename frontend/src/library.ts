import type {NeuralModel, SavedRun} from './types.ts';

// Runs fetched per request; the server allows up to 500.
export const PAGE = 100;

// Filters of GET /api/runs, combined with AND on the server; an empty one is left out.
export type RunFilters = {
  model: NeuralModel | '';
  circuit: string;
  // A comparison's batch_id.
  batch: string;
  tag: string;
  // Text in the run identifier, notes or condition, ignoring case.
  q: string;
};
export const noFilters: RunFilters = {model: '', circuit: '', batch: '', tag: '', q: ''};
const FILTERS = ['model', 'circuit', 'batch', 'tag', 'q'] as const;

// The server's rules for annotations (RunAnnotations) and for the filters.
export const TAG = /^[A-Za-z0-9 _-]{1,24}$/;
export const TAG_LIMIT = 10;
export const NOTES_LIMIT = 2000;
const BATCH = /^[A-Za-z0-9_-]{1,64}$/;
const SEARCH_LIMIT = 200;

// The filters as sent: trimmed, empty ones dropped.
export function activeFilters(filters: RunFilters): Partial<RunFilters> {
  const active: Partial<RunFilters> = {};
  for (const key of FILTERS) {
    const value = filters[key].trim();
    if (value) Object.assign(active, {[key]: value});
  }
  return active;
}

// A filter the server would refuse, as a sentence, or null.
export function filterProblem(filters: RunFilters): string | null {
  const {tag, batch, q} = activeFilters(filters);
  if (tag !== undefined && !TAG.test(tag))
    return 'A tag has up to 24 letters, digits, spaces, _ or -.';
  if (batch !== undefined && !BATCH.test(batch))
    return 'A comparison ID has up to 64 letters, digits, _ or -.';
  if (q !== undefined && q.length > SEARCH_LIMIT)
    return `Search for at most ${SEARCH_LIMIT} characters.`;
  return null;
}

// One page of the run library, newest first. include_empty=false drops runs with at most one sample
// on the server, before paging; the filters apply before paging too.
export function runsQuery(
  offset: number,
  includeEmpty: boolean,
  limit = PAGE,
  filters: RunFilters = noFilters,
): string {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(Math.min(500, Math.max(1, limit))),
    include_empty: String(includeEmpty),
    ...activeFilters(filters),
  });
  return `/api/runs?${query}`;
}

// The tags typed as "pilot, LC10 sweep": trimmed, empty entries dropped.
export function parseTags(text: string): string[] {
  return text
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

// Mirrors the server's rules for tags and notes, as one plain sentence, or null.
export function annotationProblem(tags: string[], notes: string): string | null {
  const bad = tags.find((tag) => !TAG.test(tag));
  if (bad !== undefined)
    return `“${bad}” is not a tag: use up to 24 letters, digits, spaces, _ or -, and commas between tags.`;
  if (tags.length > TAG_LIMIT) return `Use at most ${TAG_LIMIT} tags.`;
  const lower = tags.map((tag) => tag.toLowerCase());
  const twice = tags.find((_, i) => lower.indexOf(lower[i]) !== i);
  if (twice !== undefined) return `List each tag once: “${twice}” is there twice.`;
  if (notes.length > NOTES_LIMIT)
    return `Keep notes to ${NOTES_LIMIT.toLocaleString('en')} characters (now ${notes.length.toLocaleString('en')}).`;
  return null;
}

// A page from the server: {runs: [...]}, with the total in the X-Total-Count header; the total is
// null when the server does not send it (before v0.6).
export function readRunPage(
  body: unknown,
  totalHeader: string | null,
): {runs: SavedRun[]; total: number | null} {
  const runs = (body as {runs?: unknown} | null)?.runs;
  const total = totalHeader && /^\s*\d+\s*$/.test(totalHeader) ? Number(totalHeader) : null;
  return {runs: Array.isArray(runs) ? runs : [], total};
}

// Why a saved run cannot be deleted now, or null. The server refuses runs saved from the live run
// (their keys start with its run ID) and trials of the comparison still running.
export function deleteBlock(
  run: Pick<SavedRun, 'key' | 'trial'>,
  liveRunId: string | undefined,
  activeBatchId: string | null,
): string | null {
  if (liveRunId && run.key.startsWith(liveRunId))
    return 'Saved from the current run. Start a new run (Reset) to delete it.';
  if (activeBatchId && run.trial?.batch_id === activeBatchId)
    return 'A trial of the comparison that is still running.';
  return null;
}

// Appends a page, skipping runs already listed: runs saved meanwhile shift the offsets.
export function mergeRuns(shown: SavedRun[], page: SavedRun[]): SavedRun[] {
  const keys = new Set(shown.map((run) => run.key));
  return [...shown, ...page.filter((run) => !keys.has(run.key))];
}

// The line above the table. Without a total the server returned only its newest runs.
export function libraryCaption(shown: number, total: number | null, filtered = false): string {
  if (total === null) return `Showing newest ${shown} ${shown === 1 ? 'run' : 'runs'}`;
  return `Showing ${shown} of ${total} ${filtered ? 'matching ' : ''}${total === 1 ? 'run' : 'runs'}`;
}

// Replaces a run with its updated entry (an annotation was saved), keeping its place.
export function replaceRun(shown: SavedRun[], updated: SavedRun): SavedRun[] {
  return shown.map((run) => (run.key === updated.key ? {...run, ...updated} : run));
}
