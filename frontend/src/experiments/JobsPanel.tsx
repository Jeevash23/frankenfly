import {Hammer, ShieldCheck, Square} from 'lucide-react';
import type {Job} from '../types';
import {jobActive, jobStatus} from '../jobs';

const SHOWN = 6;

// Circuit builds and replay checks running in their own processes, newest first.
export function JobsPanel({jobs, cancel}: {jobs: Job[]; cancel: (id: string) => void}) {
  if (!jobs.length) return null;
  const shown = jobs.slice(0, SHOWN);
  return (
    <section className="panel jobs-panel" aria-label="Background jobs">
      <div className="panel-heading">
        <div>
          <h2>Background jobs</h2>
        </div>
        <span className="subtle-label">Builds and replay checks, in their own processes</span>
      </div>
      <ul>
        {shown.map((job) => (
          <li key={job.id} className={`job-row ${job.status}`}>
            {job.kind === 'build' ? <Hammer size={14} /> : <ShieldCheck size={14} />}
            <span className="job-label">
              {job.label}
              <small>
                {jobStatus(job)}
                {job.status === 'done' && job.kind === 'replay' && isVerdict(job.result)
                  ? job.result.ok
                    ? ' · replay matches'
                    : ' · replay differs'
                  : ''}
              </small>
            </span>
            {job.status === 'running' && job.progress !== null && (
              <progress max={1} value={job.progress} aria-label={`${job.label} progress`} />
            )}
            {jobActive(job) && (
              <button
                className="text-button"
                aria-label={`Cancel ${job.label}`}
                onClick={() => cancel(job.id)}
              >
                <Square size={11} />
                Cancel
              </button>
            )}
          </li>
        ))}
      </ul>
      {jobs.length > SHOWN && (
        <p className="microcopy jobs-more">
          {jobs.length - SHOWN} older jobs are not shown; GET /api/jobs lists the last 50.
        </p>
      )}
    </section>
  );
}

const isVerdict = (value: unknown): value is {ok: boolean} =>
  typeof value === 'object' && value !== null && 'ok' in value;
