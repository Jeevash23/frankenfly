import type {Job, Verification} from './types.ts';

// Background jobs (circuit builds, replay checks) and replay verdicts, for display.

// GET /api/jobs is polled at this interval, only while a job waits or runs.
export const JOB_POLL_MS = 1500;

export const jobActive = (job: Pick<Job, 'status'>) =>
  job.status === 'queued' || job.status === 'running';

// The newest replay job for a saved run (jobs are listed newest first), or null.
export function replayJob(jobs: Job[], key: string): Job | null {
  return jobs.find((job) => job.kind === 'replay' && job.target === key) ?? null;
}

// Saved runs whose replay check finished between two listings: active then, or not listed yet (a
// quick check can finish before the next poll). Their verdict is new, or the old one when the check
// could not run.
export function finishedReplays(before: Job[], after: Job[]): string[] {
  const settled = new Set(before.filter((j) => !jobActive(j)).map((j) => j.id));
  return after
    .filter((j) => j.kind === 'replay' && !jobActive(j) && !settled.has(j.id) && j.target)
    .map((j) => j.target as string);
}

export function jobStatus(job: Job): string {
  if (job.status === 'running')
    return job.progress !== null ? `running · ${Math.round(job.progress * 100)}%` : 'running';
  if (job.status === 'failed') return `failed${job.error ? `: ${job.error}` : ''}`;
  return job.status;
}

// "4.2e-11": errors are reported in scientific notation, like replay.py.
export const errorText = (value: number) =>
  Number.isFinite(value) ? value.toExponential(1) : String(value);

// The badge for a run's latest replay check, or null when it was never checked.
export function verificationBadge(verified: Verification | null | undefined): {
  ok: boolean;
  text: string;
  note: string | null;
  title: string;
} | null {
  if (!verified) return null;
  const note = verified.same_software ? null : 'software differs';
  const when = new Date(verified.checked);
  const checked = Number.isNaN(when.getTime()) ? '' : ` Checked ${when.toLocaleString()}.`;
  return verified.ok
    ? {ok: true, text: '✓ verified', note, title: `${verified.message}${checked}`}
    : {
        ok: false,
        text: `✗ mismatch · max error ${errorText(verified.max_abs_error)}`,
        note,
        title: `${verified.message}${checked}`,
      };
}
