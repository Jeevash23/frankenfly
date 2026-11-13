import {useEffect, useRef, useState} from 'react';
import {ClipboardCheck} from 'lucide-react';
import type {Job, State} from '../types';
import {request} from '../api';
import {
  cardLabel,
  finishedScorecards,
  keyFor,
  pickCard,
  requestFor,
  resultDetail,
  STATUS_MARK,
  STATUS_TEXT,
  type ScorecardListing,
} from '../scorecard';

// The validation scorecard: each published perturbation → behavior result, scored for the latest
// run of every model, with the source, the rule fixed in advance and the measured number.
export function ScorecardPanel({
  state,
  jobs,
  refreshJobs,
  disabled,
}: {
  state: State | null;
  jobs: Job[];
  refreshJobs: () => void;
  disabled: boolean;
}) {
  const [listing, setListing] = useState<ScorecardListing | null>(null);
  const [error, setError] = useState('');
  const [round, setRound] = useState(0);
  const [engine, setEngine] = useState<'toy' | 'flygym'>('toy');
  const [chosen, setChosen] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const current = requestFor(state?.config, engine);
  useEffect(() => {
    let cancelled = false;
    void request<ScorecardListing>('GET', '/api/scorecards').then((r) => {
      if (cancelled) return;
      if (!r.ok) return setError(r.status === 404 ? '' : `Scorecards: ${r.error}`);
      setListing(r.data);
      setError('');
    });
    return () => {
      cancelled = true;
    };
  }, [round]);
  // Reload the cards when a scorecard job finishes.
  const previous = useRef<Job[] | null>(null);
  useEffect(() => {
    if (previous.current && finishedScorecards(previous.current, jobs)) setRound((n) => n + 1);
    previous.current = jobs;
  }, [jobs]);
  if (!listing) return error ? <p className="microcopy">{error}</p> : null;
  const card = pickCard(listing.scorecards, chosen ?? keyFor(current));
  const running = jobs.some(
    (j) =>
      j.kind === 'scorecard' &&
      j.target === keyFor(current) &&
      ['queued', 'running'].includes(j.status),
  );
  const score = async () => {
    setNotice('');
    const r = await request('POST', '/api/scorecards/run', current);
    if (!r.ok) return setNotice(r.error);
    setChosen(keyFor(current));
    setNotice(
      engine === 'toy'
        ? 'Scoring on the toy body in the background; this takes under a minute for a rate model.'
        : 'Scoring on the FlyGym body in the background; this takes several minutes.',
    );
    refreshJobs();
  };
  return (
    <section className="panel scorecard-panel" aria-labelledby="scorecard-heading">
      <div className="panel-heading">
        <div>
          <h2 id="scorecard-heading">Validation scorecard</h2>
        </div>
        <span className="subtle-label">Published perturbation → behavior results</span>
      </div>
      <div className="scorecard-body">
        <p className="microcopy">
          Each test manipulates a cell type the way a published experiment did and scores the
          behavior by a rule fixed before any model was scored. A pass shows that this model
          reproduces the result, not that it is a validated fly; results marked “by construction”
          follow from the engineered readout rather than from the wiring.
        </p>
        <div className="scorecard-controls">
          {listing.scorecards.length > 0 && (
            <label>
              Model
              <select
                value={card?.key ?? ''}
                onChange={(e) => setChosen(e.target.value)}
                aria-label="Scorecard to show"
              >
                {listing.scorecards.map((c) => (
                  <option key={c.key} value={c.key}>
                    {cardLabel(c)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            Body
            <select
              value={engine}
              onChange={(e) => setEngine(e.target.value as 'toy' | 'flygym')}
              aria-label="Body to score on"
            >
              <option value="toy">Toy body (fast)</option>
              <option value="flygym">FlyGym body</option>
            </select>
          </label>
          <button
            className="secondary-button"
            disabled={disabled || !state || running}
            onClick={() => void score()}
          >
            <ClipboardCheck size={14} />
            {running ? 'Scoring…' : 'Score the Workbench model'}
          </button>
        </div>
        {notice && (
          <p className="microcopy" role="status">
            {notice}
          </p>
        )}
        {error && <p className="microcopy">{error}</p>}
        {card ? (
          <>
            <p className="scorecard-summary">
              <strong>{cardLabel(card)}:</strong> {card.summary.text}.{' '}
              <span className="microcopy">
                {card.seeds.length} seeds, {card.duration_s} s trials, scored{' '}
                {new Date(card.created).toLocaleString()}
                {card.version !== listing.version ? ' with an older version of the tests' : ''}.
              </span>
            </p>
            <div className="summary-table-wrap">
              <table className="scorecard-table">
                <thead>
                  <tr>
                    <th scope="col">Test</th>
                    <th scope="col">Result</th>
                    <th scope="col">Measured</th>
                  </tr>
                </thead>
                <tbody>
                  {card.tests.map((t) => (
                    <tr key={t.id} className={`scorecard-row ${t.status}`}>
                      <td>
                        <details>
                          <summary>{t.title}</summary>
                          <p>{t.source.finding}</p>
                          <p>
                            <a href={t.source.url} target="_blank" rel="noreferrer">
                              {t.source.citation}
                            </a>
                          </p>
                          <p>
                            <strong>Rule:</strong> {t.rule}
                          </p>
                          {t.caveats.map((c) => (
                            <p key={c} className="microcopy">
                              {c}
                            </p>
                          ))}
                        </details>
                      </td>
                      <td>
                        <span className={`scorecard-status ${t.status}`}>
                          {STATUS_MARK[t.status]} {STATUS_TEXT[t.status]}
                        </span>
                      </td>
                      <td>
                        {resultDetail(t)}
                        {t.by_construction && (
                          <small className="by-construction">
                            By construction: {t.by_construction}
                          </small>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            <p className="scorecard-summary">
              No model has been scored yet. Score the Workbench model, or run{' '}
              <code>scripts/toolkit.py scorecard --all</code>.
            </p>
            <ul className="scorecard-tests">
              {listing.tests.map((t) => (
                <li key={t.id}>
                  {t.title}{' '}
                  <a href={t.source.url} target="_blank" rel="noreferrer">
                    {t.source.citation.split(').')[0]})
                  </a>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
