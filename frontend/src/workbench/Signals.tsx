import {useState} from 'react';
import {ChevronDown} from 'lucide-react';
import type {State} from '../types';
import {trace} from '../plot';
import {fmt} from '../format';

const rateNames = [
  'Sensory L',
  'Sensory R',
  'Steering L',
  'Steering R',
  'Descending L',
  'Descending R',
];

export function Signals({state}: {state: State | null}) {
  const [group, setGroup] = useState<'descending' | 'sensory' | 'steering'>('descending');
  const index = {sensory: 0, steering: 2, descending: 4}[group];
  const history = state?.history ?? [];
  const end = Math.max(2, state?.sample?.t ?? 0);
  const start = Math.max(0, end - 4);
  return (
    <section className="signals panel" aria-label="Computed neural activity">
      <div className="panel-heading">
        <div>
          <span className="section-no">02</span>
          <h2>Inside the loop</h2>
          <span className="subtle-label">Computed activity</span>
        </div>
        <div className="select-wrap small-select">
          <select
            aria-label="Neural trace group"
            value={group}
            onChange={(e) => setGroup(e.target.value as typeof group)}
          >
            <option value="descending">Descending units</option>
            <option value="sensory">Sensory units</option>
            <option value="steering">Steering units</option>
          </select>
          <ChevronDown size={13} />
        </div>
      </div>
      <div className="signal-body">
        <div className="trace-area">
          <div className="trace-legend">
            <span>
              <i className="legend-dot left" />
              Left
            </span>
            <span>
              <i className="legend-dot right" />
              Right
            </span>
            <span className="unit">Rate · a.u.</span>
          </div>
          <div className="chart">
            <div className="y-labels">
              <span>1.4</span>
              <span>0.7</span>
              <span>0.0</span>
            </div>
            <svg
              viewBox="0 0 600 110"
              preserveAspectRatio="none"
              role="img"
              aria-label={`${group} neural rates over simulated time`}
            >
              <path
                d="M0 1H600M0 55H600M0 109H600"
                stroke="#e3e5de"
                strokeWidth="1"
                strokeDasharray="3 4"
              />
              <path
                d={trace(history, (s) => s.rates[index])}
                fill="none"
                stroke="#416a55"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
              <path
                d={trace(history, (s) => s.rates[index + 1])}
                fill="none"
                stroke="#bc9452"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>
          <div className="x-labels">
            <span>{fmt(start, 1)}</span>
            <span>{fmt((start + end) / 2, 1)}</span>
            <span>{fmt(end, 1)} s</span>
          </div>
        </div>
        <div className="unit-grid">
          {rateNames.map((label, i) => (
            <div className="rate-cell" key={label}>
              <div>
                <span>{label}</span>
                <b>{fmt(state?.sample?.rates[i])}</b>
              </div>
              <div className="rate-track">
                <span
                  style={{
                    width: `${(state?.sample?.rates[i] ?? 0) * 100}%`,
                    background: i % 2 ? '#bc9452' : '#416a55',
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="panel-footnote">
        <span className="tiny-dot" />6 engineered rate units · hand-chosen weights
        <span>Simulation time, not wall time</span>
      </div>
    </section>
  );
}
