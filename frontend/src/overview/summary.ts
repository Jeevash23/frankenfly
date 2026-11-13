import type {Job, SavedRun} from '../types.ts';
import type {Scorecard, ScorecardStatus} from '../scorecard.ts';

// What the Overview shows, as plain functions.

// The caveat every result carries.
export const MODEL_CAVEAT = 'Results are properties of these models, not fly biology.';

// Running and waiting jobs first, then the newest finished ones; jobs arrive newest first.
export function recentJobs(jobs: Job[], limit: number): Job[] {
  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
  const done = jobs.filter((j) => !active.includes(j));
  return [...active, ...done].slice(0, limit);
}

// "Left sensor off · seed 43" for a comparison trial, else the run's tags or "Workbench run".
export function runTitle(run: Pick<SavedRun, 'condition' | 'trial' | 'tags'>): string {
  if (run.trial) return `${run.condition ?? run.trial.condition} · seed ${run.trial.seed}`;
  if (run.tags.length) return run.tags.join(', ');
  return 'Workbench run';
}

// Pass, partial and fail counts of a scorecard, always in that order.
export function scoreChips(
  card: Pick<Scorecard, 'summary'>,
): {status: ScorecardStatus; count: number}[] {
  return (['pass', 'partial', 'fail'] as const).map((status) => ({
    status,
    count: card.summary[status] ?? 0,
  }));
}

// Tests that were not passed, partial or failed: inconclusive, not testable, blocked or not run.
export function otherScores(card: Pick<Scorecard, 'summary'>): number {
  const {inconclusive = 0, not_testable = 0, blocked = 0, error = 0} = card.summary;
  return inconclusive + not_testable + blocked + error;
}

// "just now", "5 min ago", "3 h ago", "2 days ago", or the date for older times.
export function timeAgo(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const s = Math.max(0, (now - then) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 14) {
    const days = Math.floor(s / 86400);
    return `${days} day${days === 1 ? '' : 's'} ago`;
  }
  return new Date(then).toLocaleDateString();
}
