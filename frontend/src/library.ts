import type {SavedRun} from './types.ts';

// Runs fetched per request; the server allows up to 500.
export const PAGE = 100;

// One page of the run library, newest first. include_empty=false drops runs with at most one sample
// on the server, before paging.
export function runsQuery(offset: number, includeEmpty: boolean, limit = PAGE): string {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(Math.min(500, Math.max(1, limit))),
    include_empty: String(includeEmpty),
  });
  return `/api/runs?${query}`;
}

// A page from the server: a list of runs, or {runs: [...]} from servers before v0.6. The total
// comes from the X-Total-Count header; null when the server does not send it.
export function readRunPage(
  body: unknown,
  totalHeader: string | null,
): {runs: SavedRun[]; total: number | null} {
  const runs = Array.isArray(body)
    ? body
    : Array.isArray((body as {runs?: unknown} | null)?.runs)
      ? (body as {runs: SavedRun[]}).runs
      : [];
  const total = totalHeader && /^\s*\d+\s*$/.test(totalHeader) ? Number(totalHeader) : null;
  return {runs, total};
}

// Appends a page, skipping runs already listed: runs saved meanwhile shift the offsets.
export function mergeRuns(shown: SavedRun[], page: SavedRun[]): SavedRun[] {
  const keys = new Set(shown.map((run) => run.key));
  return [...shown, ...page.filter((run) => !keys.has(run.key))];
}

// The line above the table. Without a total the server returned only its newest runs.
export function libraryCaption(shown: number, total: number | null): string {
  if (total === null) return `Showing newest ${shown} ${shown === 1 ? 'run' : 'runs'}`;
  return `Showing ${shown} of ${total} ${total === 1 ? 'run' : 'runs'}`;
}
