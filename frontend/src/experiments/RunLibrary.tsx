import {useEffect, useRef, useState} from 'react';
import {ArrowDownToLine, BarChart3, RotateCcw, Square, Trash2} from 'lucide-react';
import type {Command, Job, RunAnnotations, SavedRun, State} from '../types';
import {fmt} from '../format';
import {request} from '../api';
import {describeError} from '../errors';
import {
  activeFilters,
  deleteBlock,
  filterProblem,
  libraryCaption,
  mergeRuns,
  noFilters,
  PAGE,
  readRunPage,
  replaceRun,
  runsQuery,
  type RunFilters,
} from '../library';
import {jobActive, replayJob, verificationBadge} from '../jobs';
import {normalizeModel} from '../models';
import {useCircuitList} from '../connectome/useCircuit';
import {ComparisonSummary} from './ComparisonSummary';
import {LibraryFilters} from './LibraryFilters';
import {RunNotes} from './RunNotes';
import {MethodsDraft, RunExports} from './RunExports';
import {runTitle, SavedComparison} from './SavedComparison';

const MAX_SELECTED = 4;
const COLUMNS = 10;
// Typed filters apply once typing pauses this long.
const FILTER_DELAY_MS = 350;

// The run library: saved runs, newest first, page by page and filtered on the server, with tags
// and notes, replay checks, deletion, comparison statistics and an overlay of up to four selected
// runs. Each row is a RunRow; columns are added there.
export function RunLibrary({
  state,
  command,
  disabled,
  batchActive,
  jobs,
  refreshJobs,
  cancelJob,
  reload,
  showBatch,
  onLoaded,
}: {
  state: State | null;
  command: Command;
  disabled: boolean;
  batchActive: boolean;
  jobs: Job[];
  refreshJobs: () => void;
  cancelJob: (id: string) => Promise<string | null>;
  // Changes when the runs on disk changed elsewhere (a replay check finished).
  reload: number;
  // A comparison whose trials to list (its statistics' "Show these trials"); `at` repeats a request.
  showBatch: {id: string; at: number} | null;
  onLoaded: () => void;
}) {
  const [runs, setRuns] = useState<SavedRun[]>([]);
  // Runs matching the filter on the server; null when it does not say (servers before v0.6).
  const [total, setTotal] = useState<number | null>(null);
  const [listing, setListing] = useState(false);
  const listRequest = useRef(0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  // Where focus goes once the confirm step closes: back to the row's delete button after Keep,
  // to Refresh after the row is gone.
  const [refocus, setRefocus] = useState<string | null>(null);
  const refreshButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (refocus === null) return;
    const row = document.querySelector<HTMLElement>(`[data-delete="${CSS.escape(refocus)}"]`);
    (row ?? refreshButton.current)?.focus();
    setRefocus(null);
  }, [refocus]);
  const [selected, setSelected] = useState<string[]>([]);
  const [details, setDetails] = useState<SavedRun[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [includeEmpty, setIncludeEmpty] = useState(false);
  // The filters as typed, and as last sent to the server.
  const [filters, setFilters] = useState<RunFilters>(noFilters);
  const [applied, setApplied] = useState<RunFilters>(noFilters);
  const problem = filterProblem(filters);
  const filtered = Object.keys(activeFilters(applied)).length > 0;
  const {circuits} = useCircuitList();
  // The run whose tags and notes are being edited, and the comparison whose statistics are open.
  const [editing, setEditing] = useState<string | null>(null);
  const [summaryBatch, setSummaryBatch] = useState<string | null>(null);
  const library = useRef<HTMLElement>(null);
  // Loads runs from `offset` after `keep`; only the newest request's answer is used.
  const list = (offset: number, limit: number, keep: SavedRun[]) => {
    const id = ++listRequest.current;
    setListing(true);
    return fetch(runsQuery(offset, includeEmpty, limit, applied))
      .then(async (r) => {
        if (!r.ok)
          throw Error(
            'The run library could not be read. Check that the local server is still running, then press Refresh.',
          );
        const page = readRunPage(await r.json(), r.headers.get('X-Total-Count'));
        if (id !== listRequest.current) return;
        setRuns(mergeRuns(keep, page.runs));
        setTotal(page.total);
      })
      .catch((e) => {
        if (id === listRequest.current) setError(e.message);
      })
      .finally(() => {
        if (id === listRequest.current) setListing(false);
      });
  };
  // Reloads as many runs as are listed now, newest first.
  const refresh = () => list(0, Math.max(PAGE, runs.length), []);
  const loadMore = () => list(runs.length, PAGE, runs);
  useEffect(() => {
    void refresh();
    // Trials are saved as they finish, and an unfinished one when a comparison ends early.
  }, [state?.batch?.results.length, state?.batch?.status, reload]);
  const appliedKey = JSON.stringify(activeFilters(applied));
  useEffect(() => {
    void list(0, PAGE, []);
  }, [includeEmpty, appliedKey]);
  // Typed filters apply once typing pauses, and only when the server would take them.
  const filtersKey = JSON.stringify(filters);
  useEffect(() => {
    if (problem) return;
    const timer = setTimeout(() => setApplied(filters), FILTER_DELAY_MS);
    return () => clearTimeout(timer);
  }, [filtersKey, problem]);
  const changeFilters = (change: Partial<RunFilters>, now = false) => {
    const next = {...filters, ...change};
    setFilters(next);
    if (now && !filterProblem(next)) setApplied(next);
  };
  useEffect(() => {
    if (!showBatch) return;
    changeFilters({...noFilters, batch: showBatch.id}, true);
    library.current?.scrollIntoView({behavior: 'smooth', block: 'start'});
  }, [showBatch?.id, showBatch?.at]);
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      selected.map((key) =>
        fetch(`/api/runs/${key}`).then((r) => {
          if (!r.ok)
            throw Error(
              'A selected run could not be read. Its files may have been moved or deleted.',
            );
          return r.json();
        }),
      ),
    )
      .then((d) => {
        if (!cancelled) setDetails(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const remove = async (key: string) => {
    setDeleting(key);
    setError('');
    setNotice('');
    try {
      const r = await fetch(`/api/runs/${encodeURIComponent(key)}`, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
        signal: AbortSignal.timeout(30000),
      });
      const data = await r.json().catch(() => ({}));
      // 404: it is already gone. 405: a server before v0.6, which cannot delete runs.
      if (r.status === 405)
        throw Error('This version of the server cannot delete runs. Delete its folder in runs/.');
      if (!r.ok && r.status !== 404) throw Error(describeError(data.detail, r.status));
      setRuns((previous) => previous.filter((run) => run.key !== key));
      setTotal((previous) => (previous === null ? null : Math.max(0, previous - 1)));
      setSelected((previous) => previous.filter((k) => k !== key));
      setNotice(`Run ${key} deleted.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The run could not be deleted.');
    } finally {
      setDeleting(null);
      setConfirming(null);
      setRefocus(key);
    }
  };
  const verify = async (key: string) => {
    setError('');
    setNotice('');
    const r = await request('POST', `/api/runs/${encodeURIComponent(key)}/replay`, {});
    if (!r.ok)
      setError(
        r.status === 405
          ? 'This version of the server cannot verify runs. Run scripts/replay.py on the folder.'
          : r.error,
      );
    else setNotice(`Replay check of ${key} started. It runs in its own process.`);
    refreshJobs();
  };
  const cancel = async (job: Job) => {
    const problem = await cancelJob(job.id);
    if (problem) setError(problem);
  };
  // Saves a run's tags and notes; answers the server's refusal as a sentence, or null.
  const annotate = async (key: string, tags: string[], notes: string) => {
    const body: RunAnnotations = {tags, notes};
    const r = await request<SavedRun>('PATCH', `/api/runs/${encodeURIComponent(key)}`, body);
    if (!r.ok)
      return r.status === 405 ? 'This version of the server cannot keep tags and notes.' : r.error;
    setRuns((previous) => replaceRun(previous, r.data));
    setNotice(`Saved the tags and notes of ${key}.`);
    return null;
  };
  const closeEditor = (key: string) => {
    setEditing(null);
    requestAnimationFrame(() =>
      document.querySelector<HTMLElement>(`[data-edit="${CSS.escape(key)}"]`)?.focus(),
    );
  };

  // Servers before v0.6 ignore include_empty, so zero-step runs are also filtered here.
  const shownRuns = runs.filter((run) => includeEmpty || run.samples > 1);
  return (
    <section className="run-library" ref={library}>
      <div className="session-heading">
        <div>
          <span className="eyebrow">LOCAL EXPERIMENT RECORDS</span>
          <h2>Run library</h2>
        </div>
        <button
          ref={refreshButton}
          className="secondary-button"
          aria-busy={listing}
          onClick={() => {
            if (!listing) void refresh();
          }}
        >
          <RotateCcw size={13} />
          Refresh
        </button>
      </div>
      {(error || notice) && (
        <div
          className={`alert ${error ? 'error-alert' : 'export-alert'}`}
          role={error ? 'alert' : 'status'}
        >
          {error || notice}
        </div>
      )}
      <div className="library-filter">
        <p className="library-hint">
          Select up to four saved runs to overlay their paths and compare measured outcomes.
          {(runs.length > 0 || filtered) &&
            ` ${libraryCaption(shownRuns.length, total, filtered)}.`}
        </p>
        <label>
          <input
            type="checkbox"
            checked={includeEmpty}
            onChange={(e) => setIncludeEmpty(e.target.checked)}
          />
          Include zero-step runs
        </label>
      </div>
      <LibraryFilters
        filters={filters}
        change={changeFilters}
        circuits={circuits}
        problem={problem}
        clear={
          Object.keys(activeFilters(filters)).length ? () => changeFilters(noFilters, true) : null
        }
      />
      {summaryBatch && (
        <ComparisonSummary
          batchId={summaryBatch}
          reload={reload}
          showTrials={() => changeFilters({...noFilters, batch: summaryBatch}, true)}
          close={() => setSummaryBatch(null)}
        />
      )}
      {!shownRuns.length && filtered ? (
        <section className="panel empty-research">
          <h3>No saved runs match these filters.</h3>
          <button className="secondary-button" onClick={() => changeFilters(noFilters, true)}>
            Clear filters
          </button>
        </section>
      ) : !shownRuns.length ? (
        <section className="panel empty-research">
          <ArrowDownToLine size={26} />
          <h3>Your first record starts here.</h3>
          <p>
            Export a workbench run or complete a comparison. Everything is saved on this computer.
          </p>
        </section>
      ) : (
        <div className="panel library-table-wrap">
          <table className="library-table">
            <thead>
              <tr>
                <th>Compare</th>
                <th>Experiment</th>
                <th>Body / sensor</th>
                <th>Seed</th>
                <th>Time</th>
                <th>Mean speed</th>
                <th>Tags & notes</th>
                <th>Replay</th>
                <th>Files</th>
                <th>
                  <span className="visually-hidden">Delete</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shownRuns.map((run) => (
                <RunRow
                  key={run.key}
                  run={run}
                  selected={selected.includes(run.key)}
                  canSelect={selected.length < MAX_SELECTED}
                  toggle={(on) =>
                    setSelected((prev) =>
                      on ? [...prev, run.key] : prev.filter((k) => k !== run.key),
                    )
                  }
                  blocked={deleteBlock(run, state?.run_id, batchActive ? state!.batch!.id : null)}
                  job={replayJob(jobs, run.key)}
                  activeTag={applied.tag.trim()}
                  filterTag={(tag) => changeFilters({tag}, true)}
                  editing={editing === run.key}
                  edit={() => setEditing(run.key)}
                  annotate={(tags, notes) => annotate(run.key, tags, notes)}
                  closeEditor={() => closeEditor(run.key)}
                  showSummary={(batch) => setSummaryBatch(batch)}
                  verify={() => void verify(run.key)}
                  cancel={(job) => void cancel(job)}
                  confirming={confirming === run.key}
                  deleting={deleting === run.key}
                  askDelete={() => setConfirming(run.key)}
                  remove={() => {
                    if (!deleting) void remove(run.key);
                  }}
                  keep={() => {
                    if (deleting) return;
                    setConfirming(null);
                    setRefocus(run.key);
                  }}
                />
              ))}
            </tbody>
          </table>
          {total !== null && runs.length < total && (
            <button
              className="text-button library-more"
              aria-busy={listing}
              onClick={() => {
                if (!listing) void loadMore();
              }}
            >
              Load {Math.min(PAGE, total - runs.length)} more
            </button>
          )}
        </div>
      )}
      <SavedComparison
        details={details}
        command={command}
        disabled={disabled || batchActive}
        onLoaded={onLoaded}
      />
    </section>
  );
}

function RunRow({
  run,
  selected,
  canSelect,
  toggle,
  blocked,
  job,
  activeTag,
  filterTag,
  editing,
  edit,
  annotate,
  closeEditor,
  showSummary,
  verify,
  cancel,
  confirming,
  deleting,
  askDelete,
  remove,
  keep,
}: {
  run: SavedRun;
  selected: boolean;
  canSelect: boolean;
  toggle: (on: boolean) => void;
  // Why the run cannot be deleted now, or null.
  blocked: string | null;
  // The newest replay check of this run, or null.
  job: Job | null;
  // The tag the library is filtered by ('' for none); a tag chip filters by its tag.
  activeTag: string;
  filterTag: (tag: string) => void;
  editing: boolean;
  edit: () => void;
  annotate: (tags: string[], notes: string) => Promise<string | null>;
  closeEditor: () => void;
  showSummary: (batchId: string) => void;
  verify: () => void;
  cancel: (job: Job) => void;
  confirming: boolean;
  deleting: boolean;
  askDelete: () => void;
  remove: () => void;
  keep: () => void;
}) {
  const [methods, setMethods] = useState(false);
  const tags = run.tags ?? [];
  return (
    <>
      <tr className={selected ? 'selected' : ''}>
        <td>
          <input
            type="checkbox"
            aria-label={`Compare run ${run.key}`}
            checked={selected}
            disabled={!selected && !canSelect}
            onChange={(e) => toggle(e.target.checked)}
          />
        </td>
        <td>
          <strong>
            {runTitle(run)}
            {run.trial?.partial && <span className="run-tag">partial</span>}
          </strong>
          <small>
            {new Date(run.created_utc).toLocaleString()} · {run.samples} samples
            {run.error ? ' · interrupted' : ''}
          </small>
          {run.batch_id && (
            <button
              className="text-button run-statistics"
              aria-label={`Statistics of comparison ${run.batch_id}`}
              onClick={() => showSummary(run.batch_id!)}
            >
              <BarChart3 size={11} />
              Comparison statistics
            </button>
          )}
        </td>
        <td>
          {run.config.engine === 'flygym' ? 'FlyGym' : 'Toy'}
          <small>
            {{vision: 'Compound eye', flyvis: 'FlyVis eyes', geometric: 'Geometric'}[
              run.config.sensor_model ?? 'geometric'
            ] ?? 'Geometric'}{' '}
            ·{' '}
            {normalizeModel(run.config.neural_model) === 'connectome'
              ? `connectome · ${run.config.connectome_parameters?.circuit ?? 'fafb783-dna02'}${run.config.connectome_parameters?.dynamics === 'spiking' ? ' · spiking' : ''}`
              : 'engineered'}
          </small>
        </td>
        <td>{run.config.seed}</td>
        <td>{fmt(run.metrics.duration_s ?? (run.samples - 1) * 0.01)} s</td>
        <td>{fmt(run.metrics.mean_speed_mm_s)} mm/s</td>
        <td className="run-annotations">
          {tags.length > 0 && (
            <span className="tag-chips">
              {tags.map((tag) => (
                <button
                  key={tag}
                  className="tag-chip"
                  aria-label={`Show runs tagged ${tag}`}
                  aria-pressed={activeTag.toLowerCase() === tag.toLowerCase()}
                  title="Show only runs with this tag"
                  onClick={() => filterTag(tag)}
                >
                  {tag}
                </button>
              ))}
            </span>
          )}
          {run.notes && (
            <small className="run-notes-preview" title={run.notes}>
              {run.notes}
            </small>
          )}
          <button
            className="text-button"
            data-edit={run.key}
            aria-expanded={editing}
            aria-label={`Edit the tags and notes of run ${run.key}`}
            onClick={editing ? closeEditor : edit}
          >
            {tags.length || run.notes ? 'Edit' : 'Add tags or notes'}
          </button>
        </td>
        <td className="run-replay">
          <ReplayCell run={run} job={job} verify={verify} cancel={cancel} />
        </td>
        <td>
          <RunExports
            runKey={run.key}
            zipUrl={run.download_url}
            methodsOpen={methods}
            toggleMethods={() => setMethods(!methods)}
          />
        </td>
        <td className="run-delete">
          {confirming ? (
            <span role="group" aria-label={`Delete run ${run.key}?`}>
              <button className="text-button" aria-busy={deleting} onClick={remove}>
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
              <button className="text-button" autoFocus onClick={keep}>
                Keep
              </button>
            </span>
          ) : (
            <button
              className="icon-button"
              aria-label={blocked ? `Delete run ${run.key}: ${blocked}` : `Delete run ${run.key}`}
              title={blocked ?? 'Delete this run and its ZIP from runs/'}
              disabled={!!blocked}
              data-delete={run.key}
              onClick={askDelete}
            >
              <Trash2 size={14} />
            </button>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="run-notes-row">
          <td colSpan={COLUMNS}>
            <RunNotes run={run} save={annotate} close={closeEditor} />
          </td>
        </tr>
      )}
      {methods && (
        <tr className="run-notes-row">
          <td colSpan={COLUMNS}>
            <MethodsDraft
              path={`/api/runs/${encodeURIComponent(run.key)}/methods`}
              close={() => setMethods(false)}
            />
          </td>
        </tr>
      )}
    </>
  );
}

// A run's latest replay verdict, or the check in progress, and the button that starts one.
function ReplayCell({
  run,
  job,
  verify,
  cancel,
}: {
  run: SavedRun;
  job: Job | null;
  verify: () => void;
  cancel: (job: Job) => void;
}) {
  if (job && jobActive(job))
    return (
      <span className="verify-status">
        {job.status === 'queued'
          ? 'Waiting to verify…'
          : `Verifying…${job.progress !== null ? ` ${Math.round(job.progress * 100)}%` : ''}`}
        <button
          className="text-button"
          aria-label={`Cancel the replay check of ${run.key}`}
          onClick={() => cancel(job)}
        >
          <Square size={10} />
          Cancel
        </button>
      </span>
    );
  const badge = verificationBadge(run.verified);
  // A check that could not run (for example, the circuit changed) keeps the earlier verdict.
  const failed =
    job?.status === 'failed' &&
    (!run.verified || (job.finished ?? '') > (run.verified.checked ?? ''));
  return (
    <span className="verify-status">
      {badge && (
        <span className={`verify-badge ${badge.ok ? 'ok' : 'mismatch'}`} title={badge.title}>
          {badge.text}
        </span>
      )}
      {badge?.note && (
        <small title={run.verified?.software_differences?.join('; ')}>{badge.note}</small>
      )}
      {failed && (
        <small className="form-error" title={job?.error ?? undefined}>
          check failed{job?.error ? `: ${job.error}` : ''}
        </small>
      )}
      <button
        className="text-button"
        aria-label={`${badge ? 'Verify again' : 'Verify replay of'} ${run.key}`}
        onClick={verify}
      >
        {badge ? 'Verify again' : 'Verify replay'}
      </button>
    </span>
  );
}
