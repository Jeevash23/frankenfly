import {useEffect, useState, type ReactNode} from 'react';
import {
  ArrowRight,
  ClipboardCheck,
  FlaskConical,
  Hammer,
  Network,
  Pause,
  Play,
  Puzzle,
} from 'lucide-react';
import type {Job, SavedRun, State} from '../types';
import {request} from '../api';
import {fmt} from '../format';
import {jobActive, jobStatus} from '../jobs';
import {modelPhrases} from '../models';
import {contributionSummary, type PluginListing} from '../plugins';
import {routeHash, type RouteId} from '../route';
import {cardLabel, STATUS_MARK, STATUS_TEXT, type ScorecardListing} from '../scorecard';
import {ROUTE_ICONS} from '../shell/icons';
import {MODEL_CAVEAT, otherScores, recentJobs, runTitle, scoreChips, timeAgo} from './summary';

export type QuickAction = 'first-experiment' | 'build' | 'explore-dna02' | 'score';

const SENSORS: Record<string, string> = {
  vision: 'compound-eye input',
  flyvis: 'FlyVis eyes',
  geometric: 'geometric input',
};

// Loads a read-only listing once; null until it arrives, with an error sentence if it failed.
function useListing<T>(path: string): {data: T | null; error: string} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    void request<T>('GET', path).then((r) => {
      if (cancelled) return;
      if (r.ok) setData(r.data);
      else setError(r.status === 404 ? 'Not available on this server.' : r.error);
    });
    return () => {
      cancelled = true;
    };
  }, [path]);
  return {data, error};
}

function Card({
  title,
  route,
  link,
  className = '',
  children,
}: {
  title: string;
  route: RouteId;
  link: string;
  className?: string;
  children: ReactNode;
}) {
  const Icon = ROUTE_ICONS[route];
  const id = `overview-${route}`;
  return (
    <section className={`panel overview-card ${className}`} aria-labelledby={id}>
      <div className="overview-card-head">
        <h2 id={id}>
          <Icon size={15} aria-hidden />
          {title}
        </h2>
        <a href={routeHash(route)} className="card-link">
          {link}
          <ArrowRight size={13} aria-hidden />
        </a>
      </div>
      <div className="overview-card-body">{children}</div>
    </section>
  );
}

// The landing page: the live simulation, recent runs, the latest scorecards, jobs, plugins and
// shortcuts to the common first steps. It only reads; every change happens on the pages it links.
export function Overview({
  state,
  connected,
  jobs,
  quick,
  toggleRun,
  canToggleRun,
}: {
  state: State | null;
  connected: boolean;
  jobs: Job[];
  quick: (action: QuickAction) => void;
  toggleRun: () => void;
  canToggleRun: boolean;
}) {
  const runs = useListing<{runs: SavedRun[]}>('/api/runs?limit=6&include_empty=false');
  const scorecards = useListing<ScorecardListing>('/api/scorecards');
  const plugins = useListing<PluginListing>('/api/plugins');
  const config = state?.config;
  const status = !connected ? 'connecting' : (state?.status ?? 'initializing');
  const running = status === 'running';
  const shownJobs = recentJobs(jobs, 5);
  const circuit =
    config?.neural_model === 'connectome'
      ? `${config.connectome_parameters.circuit} · ${config.connectome_parameters.dynamics}`
      : null;
  return (
    <div className="overview">
      <p className="caveat-line">
        <span className="caveat-mark" aria-hidden>
          ⁂
        </span>
        {MODEL_CAVEAT}
      </p>
      <div className="overview-grid">
        <div className="overview-col">
          <Card title="Simulation" route="workbench" link="Open the Workbench" className="o-sim">
            <div className="sim-status">
              <span className={`status-pill ${status}`}>
                <i aria-hidden />
                {status.toUpperCase()}
              </span>
              <button
                type="button"
                className="secondary-button"
                disabled={!canToggleRun}
                onClick={toggleRun}
              >
                {running ? <Pause size={13} /> : <Play size={13} />}
                {running ? 'Pause' : 'Run'}
              </button>
            </div>
            <dl className="stat-grid">
              <div>
                <dt>Simulated time</dt>
                <dd>
                  {fmt(state?.sample?.t, 2)}
                  <small> s</small>
                </dd>
              </div>
              <div>
                <dt>Step</dt>
                <dd>{state?.sample?.step ?? '—'}</dd>
              </div>
              <div>
                <dt>Speed</dt>
                <dd>
                  {fmt(state?.real_time_factor, 2)}
                  <small>× real time</small>
                </dd>
              </div>
              <div>
                <dt>Target distance</dt>
                <dd>
                  {fmt(state?.sample?.sensors.distance_mm, 1)}
                  <small> mm</small>
                </dd>
              </div>
            </dl>
            <p className="sim-config">
              <span className="chip">
                {config?.engine === 'flygym' ? 'FlyGym body' : 'Toy body'}
              </span>
              <span className="chip">{modelPhrases[config?.neural_model ?? 'engineered']}</span>
              {circuit && <span className="chip">{circuit}</span>}
              <span className="chip">{SENSORS[config?.sensor_model ?? 'geometric']}</span>
              {state?.run_id && state.run_id !== 'initializing' && (
                <span className="chip mono">run {state.run_id.slice(-8)}</span>
              )}
            </p>
          </Card>
          <Card title="Recent runs" route="library" link="Run library" className="o-runs">
            {runs.data ? (
              runs.data.runs.length ? (
                <table className="data-table compact-table">
                  <thead>
                    <tr>
                      <th scope="col">Run</th>
                      <th scope="col">Saved</th>
                      <th scope="col">Duration</th>
                      <th scope="col">Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.data.runs.map((run) => (
                      <tr key={run.key}>
                        <td>
                          <span className="run-name">{runTitle(run)}</span>
                          <small className="mono">{run.run_id.slice(-8)}</small>
                        </td>
                        <td>{timeAgo(run.created_utc)}</td>
                        <td>{fmt(run.metrics.duration_s, 1)} s</td>
                        <td>{fmt(run.metrics.path_length_mm, 1)} mm</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="empty-line">
                  No saved runs yet. Export a run on the Workbench, or run a comparison.
                </p>
              )
            ) : (
              <p className="empty-line">{runs.error || 'Loading…'}</p>
            )}
          </Card>
          <Card title="Scorecards" route="scorecard" link="Open the scorecard" className="o-scores">
            {scorecards.data ? (
              scorecards.data.scorecards.length ? (
                <ul className="score-list">
                  {scorecards.data.scorecards.map((card) => (
                    <li key={card.key}>
                      <span className="score-model">
                        {cardLabel(card)}
                        <small>{timeAgo(card.created)}</small>
                      </span>
                      <span className="score-chips">
                        {scoreChips(card).map(({status, count}) => (
                          <span key={status} className={`score-chip ${count ? status : 'zero'}`}>
                            {STATUS_MARK[status]} {count} {STATUS_TEXT[status].toLowerCase()}
                          </span>
                        ))}
                        {otherScores(card) > 0 && (
                          <span
                            className="score-chip zero"
                            title="Inconclusive, not testable on this model, blocked or did not run"
                          >
                            {otherScores(card)} not scored
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-line">
                  No model has been scored yet. {scorecards.data.tests.length} published tests are
                  ready; use Run the scorecard.
                </p>
              )
            ) : (
              <p className="empty-line">{scorecards.error || 'Loading…'}</p>
            )}
          </Card>
        </div>
        <div className="overview-col">
          <section
            className="panel overview-card quick-actions o-quick"
            aria-labelledby="overview-quick"
          >
            <div className="overview-card-head">
              <h2 id="overview-quick">Quick actions</h2>
            </div>
            <div className="overview-card-body">
              <ul className="action-list">
                <li>
                  <button type="button" onClick={() => quick('first-experiment')}>
                    <FlaskConical size={15} aria-hidden />
                    <span>
                      Set up the first experiment
                      <small>A target-reversal comparison, ready to run</small>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => quick('build')}>
                    <Hammer size={15} aria-hidden />
                    <span>
                      Build a circuit
                      <small>Cut one out of FlyWire around seed types</small>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => quick('explore-dna02')}>
                    <Network size={15} aria-hidden />
                    <span>
                      Explore DNa02
                      <small>Its strongest inputs in the connectivity explorer</small>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => quick('score')}>
                    <ClipboardCheck size={15} aria-hidden />
                    <span>
                      Run the scorecard
                      <small>Score the Workbench model on the toy body</small>
                    </span>
                  </button>
                </li>
              </ul>
            </div>
          </section>
          <Card title="Jobs" route="jobs" link="All jobs" className="o-jobs">
            {shownJobs.length ? (
              <ul className="mini-list">
                {shownJobs.map((job) => (
                  <li key={job.id} className={`job-mini ${job.status}`}>
                    <span className={`status-dot ${jobActive(job) ? 'active' : job.status}`} />
                    <span className="mini-label">
                      {job.label}
                      <small>{jobStatus(job)}</small>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-line">
                No background jobs. Circuit builds, replay checks and scorecards appear here.
              </p>
            )}
          </Card>
          <Card title="Plugins" route="plugins" link="Plugins" className="o-plugins">
            {plugins.data ? (
              plugins.data.plugins.length ? (
                <ul className="mini-list">
                  {plugins.data.plugins.map((plugin) => (
                    <li key={`${plugin.name}-${plugin.entry_point}`}>
                      <Puzzle size={13} aria-hidden />
                      <span className="mini-label">
                        {plugin.title}
                        <small>
                          {plugin.status === 'ok'
                            ? contributionSummary(plugin)
                            : `not loaded: ${plugin.status}`}
                        </small>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-line">
                  {plugins.data.enabled
                    ? 'No plugins installed. See docs/PLUGINS.md to add sensors, metrics or tests.'
                    : 'Plugins are turned off (DIGITALFLY_PLUGINS=0).'}
                </p>
              )
            ) : (
              <p className="empty-line">{plugins.error || 'Loading…'}</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
