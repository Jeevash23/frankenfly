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
export function libraryCaption(shown: number, total: number | null): string {
  if (total === null) return `Showing newest ${shown} ${shown === 1 ? 'run' : 'runs'}`;
  return `Showing ${shown} of ${total} ${total === 1 ? 'run' : 'runs'}`;
}
