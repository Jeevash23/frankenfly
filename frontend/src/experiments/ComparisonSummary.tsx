import {useEffect, useId, useState} from 'react';
import {ArrowDownToLine, ChevronDown, ListFilter, X} from 'lucide-react';
import type {BatchSummary, MetricSummary} from '../types';
import {request} from '../api';
import {conditionName} from '../models';
import {intervalChart} from '../plot';
import {
  formatEstimate,
  formatInterval,
  formatTick,
  formatValue,
  leftOutNote,
  metricLabel,
  metricOrder,
  sampleNote,
  SMALL_N,
  summaryCsvUrl,
  wideInterval,
} from '../summary';

// A finished comparison's statistics from GET /api/batches/{batch_id}/summary: per condition the
// mean ± SD and 95% interval of each metric, the paired differences from the first condition, a
// chart of one metric and the same numbers as CSV. The server computes them all.
export function ComparisonSummary({
  batchId,
  reload,
  showTrials,
  close,
}: {
  batchId: string;
  // Changes when trials of this comparison were saved or deleted.
  reload?: unknown;
  // Filters the run library to this comparison's trials.
  showTrials?: () => void;
  close?: () => void;
}) {
  const id = useId();
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    void request<BatchSummary>('GET', `/api/batches/${encodeURIComponent(batchId)}/summary`).then(
      (r) => {
        if (cancelled) return;
        if (r.ok) {
          setSummary(r.data);
          setError('');
        } else {
          setSummary(null);
          setError(
            r.status === 405 || (r.status === 404 && !/comparison/.test(r.error))
              ? 'This version of the server has no comparison statistics.'
              : r.error,
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [batchId, reload]);
  const metrics = summary ? metricOrder(summary) : [];
  const baseline = summary?.conditions[0]?.condition;
  const note = summary ? sampleNote(summary) : null;
  const leftOut = summary ? leftOutNote(summary) : null;
  return (
    <section className="panel comparison-summary" aria-labelledby={`${id}-heading`}>
      <div className="panel-heading">
        <div>
          <h2 id={`${id}-heading`}>Comparison statistics</h2>
        </div>
        <div className="summary-heading-end">
          <span className="subtle-label">
            Comparison {batchId}
            {summary ? ` · ${summary.n_trials} ${summary.n_trials === 1 ? 'trial' : 'trials'}` : ''}
          </span>
          {close && (
            <button
              className="icon-button"
              aria-label="Close the comparison statistics"
              onClick={close}
            >
              <X size={15} />
            </button>
          )}
        </div>
      </div>
      <div className="summary-body">
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : !summary ? (
          <p className="microcopy" role="status">
            Loading the statistics…
          </p>
        ) : (
          <>
            {note && <p className="summary-note">{note}</p>}
            {leftOut && <p className="microcopy">{leftOut}</p>}
            <div className="summary-table-wrap">
              <table className="summary-table">
                <caption>Per condition: mean ± SD, with the 95% interval below</caption>
                <thead>
                  <tr>
                    <th scope="col">Condition</th>
                    <th scope="col">n</th>
                    {metrics.map((m) => (
                      <th scope="col" key={m}>
                        {metricLabel(m)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {summary.conditions.map((c, i) => (
                    <tr key={c.condition}>
                      <th scope="row">
                        {conditionName(c.condition)}
                        {i === 0 && summary.conditions.length > 1 && <small>baseline</small>}
                      </th>
                      <td>
                        <SampleSize n={c.n} />
                      </td>
                      {metrics.map((m) => (
                        <td key={m}>
                          <Estimate metric={m} value={c.metrics[m]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {summary.paired.length > 0 && baseline !== undefined && (
              <div className="summary-table-wrap">
                <table className="summary-table">
                  <caption>
                    Paired difference from {conditionName(baseline)}: condition − baseline over
                    trials with the same seed, with the 95% interval below
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Condition</th>
                      <th scope="col">Pairs</th>
                      {metrics.map((m) => (
                        <th scope="col" key={m}>
                          {metricLabel(m)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {summary.conditions.slice(1).map((c) => {
                      const rows = summary.paired.filter((p) => p.condition === c.condition);
                      return (
                        <tr key={c.condition}>
                          <th scope="row">{conditionName(c.condition)}</th>
                          <td>
                            <SampleSize n={rows[0]?.n_pairs ?? 0} />
                          </td>
                          {metrics.map((m) => {
                            const row = rows.find((p) => p.metric === m);
                            return (
                              <td key={m}>
                                {row ? (
                                  <Estimate
                                    metric={m}
                                    value={{mean: row.mean_diff, sd: null, ci95: row.ci95}}
                                    signed
                                  />
                                ) : (
                                  '—'
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {metrics.length > 0 && <SummaryChart summary={summary} metrics={metrics} />}
            <div className="summary-actions">
              <a className="secondary-button" href={summaryCsvUrl(batchId)} download>
                <ArrowDownToLine size={13} />
                Download CSV
              </a>
              {showTrials && (
                <button className="text-button" onClick={showTrials}>
                  <ListFilter size={12} />
                  Show these trials in the library
                </button>
              )}
            </div>
            <details className="summary-methods">
              <summary>How these numbers are computed</summary>
              <dl>
                {Object.entries(summary.methods).map(([name, text]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>{text}</dd>
                  </div>
                ))}
                <div>
                  <dt>wide</dt>
                  <dd>a 95% interval wider than the estimate itself (more than about ±50%)</dd>
                </div>
                <div>
                  <dt>small n</dt>
                  <dd>fewer than {SMALL_N} trials or pairs</dd>
                </div>
              </dl>
            </details>
          </>
        )}
      </div>
    </section>
  );
}

function SampleSize({n}: {n: number}) {
  return (
    <>
      {n}
      {n < SMALL_N && <span className="run-tag">small n</span>}
    </>
  );
}

// "1.19 ± 0.03" over "95% CI 1.17 to 1.22", marked wide where it is.
function Estimate({
  metric,
  value,
  signed = false,
}: {
  metric: string;
  value: MetricSummary | undefined;
  signed?: boolean;
}) {
  if (!value || value.mean === null) return <>—</>;
  const interval = formatInterval(metric, value.ci95, signed);
  return (
    <>
      <span className="summary-estimate">
        {signed ? formatValue(metric, value.mean, true) : formatEstimate(metric, value)}
      </span>
      <small>
        {interval ? `95% CI ${interval}` : 'no interval below 2 trials'}
        {wideInterval(value.mean, value.ci95) && <span className="run-tag wide-tag">wide</span>}
      </small>
    </>
  );
}

const CHART = {width: 560, label: 172, right: 540, row: 30, top: 14, axis: 30};

// One metric's mean and 95% interval per condition on a shared axis that includes zero. The tables
// above hold the same numbers; wide intervals are drawn dashed.
function SummaryChart({summary, metrics}: {summary: BatchSummary; metrics: string[]}) {
  const id = useId();
  const [chosen, setChosen] = useState(metrics[0]);
  const metric = metrics.includes(chosen) ? chosen : metrics[0];
  const rows = summary.conditions.map((c) => ({
    name: conditionName(c.condition),
    estimate: c.metrics[metric]?.mean ?? null,
    ci: c.metrics[metric]?.ci95 ?? null,
  }));
  const chart = intervalChart(rows, CHART.label + 12, CHART.right);
  const height = CHART.top + rows.length * CHART.row + CHART.axis;
  const axisY = CHART.top + rows.length * CHART.row;
  const describe = (row: (typeof rows)[number]) => {
    const interval = formatInterval(metric, row.ci);
    return `${row.name}: ${formatValue(metric, row.estimate)}${interval ? `, 95% CI ${interval}` : ''}`;
  };
  return (
    <figure className="summary-chart">
      <label className="field-label">
        Chart
        <div className="select-wrap">
          <select
            aria-label="Metric to chart"
            value={metric}
            onChange={(e) => setChosen(e.target.value)}
          >
            {metrics.map((m) => (
              <option key={m} value={m}>
                {metricLabel(m)}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </div>
      </label>
      <svg
        viewBox={`0 0 ${CHART.width} ${height}`}
        role="img"
        aria-labelledby={`${id}-title ${id}-desc`}
      >
        <title id={`${id}-title`}>
          {metricLabel(metric)} per condition: mean with 95% interval
        </title>
        <desc id={`${id}-desc`}>{rows.map(describe).join('; ')}</desc>
        {chart.ticks.map((tick) => (
          <g key={tick.value}>
            <path d={`M${tick.x} ${CHART.top - 6}V${axisY}`} className="summary-grid" />
            <text x={tick.x} y={axisY + 16} textAnchor="middle">
              {formatTick(metric, tick.value)}
            </text>
          </g>
        ))}
        <path d={`M${chart.zero} ${CHART.top - 6}V${axisY}`} className="summary-zero" />
        {rows.map((row, i) => {
          const y = CHART.top + i * CHART.row + CHART.row / 2;
          const at = chart.rows[i];
          return (
            <g key={row.name}>
              <title>{describe(row)}</title>
              <rect
                x="0"
                y={y - CHART.row / 2}
                width={CHART.width}
                height={CHART.row}
                fill="transparent"
              />
              <text x={CHART.label} y={y + 4} textAnchor="end">
                {row.name}
              </text>
              {at && (
                <>
                  <path
                    d={`M${at.low} ${y}H${at.high}M${at.low} ${y - 5}V${y + 5}M${at.high} ${y - 5}V${y + 5}`}
                    className="summary-whisker"
                    strokeDasharray={wideInterval(row.estimate, row.ci) ? '4 3' : undefined}
                  />
                  <circle cx={at.x} cy={y} r="4.5" className="summary-dot" />
                </>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="microcopy">
        Dots are means, lines their 95% intervals (dashed where wide); the axis includes zero.
      </figcaption>
    </figure>
  );
}
