import {useCallback, useEffect, useState} from 'react';
import type {Job} from './types';
import {request} from './api';
import {JOB_POLL_MS, jobActive} from './jobs';

// Background jobs from GET /api/jobs: read once, then polled only while one waits or runs.
// `refresh` reads them again (after starting one). Servers before v0.6 have no jobs.
export function useJobs(): {
  jobs: Job[];
  // False until the first listing arrives.
  loaded: boolean;
  error: string;
  refresh: () => void;
  cancel: (id: string) => Promise<string | null>;
} {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [round, setRound] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const r = await request<{jobs: Job[]}>('GET', '/api/jobs');
      if (cancelled) return;
      if (!r.ok) return setError(r.status === 404 ? '' : `Background jobs: ${r.error}`);
      setJobs(r.data.jobs);
      setLoaded(true);
      setError('');
      if (r.data.jobs.some(jobActive)) timer = setTimeout(() => void poll(), JOB_POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [round]);
  const refresh = useCallback(() => setRound((r) => r + 1), []);
  // The error message, or null once the job is cancelled.
  const cancel = useCallback(
    async (id: string) => {
      const r = await request('POST', `/api/jobs/${encodeURIComponent(id)}/cancel`, {});
      refresh();
      return r.ok ? null : r.error;
    },
    [refresh],
  );
  return {jobs, loaded, error, refresh, cancel};
}
