import {useState} from 'react';
import {ChevronDown} from 'lucide-react';
import type {State} from '../types';
import {trace} from '../plot';
import {fmt} from '../format';

const engineeredNames = [
  'Sensory L',
  'Sensory R',
  'Steering L',
  'Steering R',
  'Descending L',
  'Descending R',
];
const connectomeNames = ['DNa02 L', 'DNa02 R', 'Visual input L', 'Visual input R', 'Circuit mean'];
const typeColors = ['#416a55', '#bc9452', '#7f7fae', '#a26e67', '#5f8f8a'];
const typeDashes = [undefined, '6 4', '2 3', '8 3 2 3', '1 4'];

type Group = 'descending' | 'sensory' | 'steering' | 'dna02' | 'input' | 'types';

// Left is a solid line, right a dashed one, so the two never differ by colour alone.
function LineKey({color, dash}: {color: string; dash?: string}) {
  return (
    <svg width="22" height="8" aria-hidden="true">
      <path d="M1 4H21" stroke={color} strokeWidth="2" strokeDasharray={dash} />
    </svg>
  );
}

export function Signals({state}: {state: State | null}) {
  const connectome = state?.config.neural_model === 'connectome_dna02';
  const [chosen, setGroup] = useState<Group>('descending');
  const group: Group = connectome
    ? ['dna02', 'input', 'types'].includes(chosen)
      ? chosen
      : 'dna02'
    : ['descending', 'sensory', 'steering'].includes(chosen)
      ? chosen
      : 'descending';
  const index = {sensory: 0, steering: 2, descending: 4, dna02: 0, input: 2, types: 0}[group];
  const history = state?.history ?? [];
  const end = Math.max(2, state?.sample?.t ?? 0);
  const start = Math.max(0, end - 4);
  const names = connectome ? connectomeNames : engineeredNames;
  const top = state?.connectome?.top_types ?? [];
  const times = state?.connectome?.trace_t ?? [];
  const typeTraces = top.map((type) =>
    trace(
      times.map((t, i) => ({t, rate: type.trace[i] ?? 0})),
      (point) => point.rate,
    ),
  );
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
            onChange={(e) => setGroup(e.target.value as Group)}
          >
            {connectome ? (
              <>
                <option value="dna02">DNa02 left & right</option>
                <option value="input">Visual input left & right</option>
                <option value="types">Most active cell types</option>
              </>
            ) : (
              <>
                <option value="descending">Descending units</option>
                <option value="sensory">Sensory units</option>
                <option value="steering">Steering units</option>
              </>
            )}
          </select>
          <ChevronDown size={13} />
        </div>
      </div>
      <div className="signal-body">
        <div className="trace-area">
          <div className="trace-legend">
            {group === 'types' ? (
              top.map((t, i) => (
                <span key={t.name}>
                  <LineKey color={typeColors[i]} dash={typeDashes[i]} />
                  {t.name}
                </span>
              ))
            ) : (
              <>
                <span>
                  <LineKey color="#416a55" />
                  Left
                </span>
                <span>
                  <LineKey color="#bc9452" dash="6 4" />
                  Right
                </span>
              </>
            )}
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
              {group === 'types' ? (
                typeTraces.map((d, i) => (
                  <path
                    key={top[i].name}
                    d={d}
                    fill="none"
                    stroke={typeColors[i]}
                    strokeWidth="2"
                    strokeDasharray={typeDashes[i]}
                    vectorEffect="non-scaling-stroke"
                  />
                ))
              ) : (
                <>
                  <path
                    d={trace(history, (s) => s.rates[index] ?? 0)}
                    fill="none"
                    stroke="#416a55"
                    strokeWidth="2"
                    vectorEffect="non-scaling-stroke"
                  />
                  <path
                    d={trace(history, (s) => s.rates[index + 1] ?? 0)}
                    fill="none"
                    stroke="#bc9452"
                    strokeWidth="2"
                    strokeDasharray="6 4"
                    vectorEffect="non-scaling-stroke"
                  />
                </>
              )}
            </svg>
          </div>
          <div className="x-labels">
            <span>{fmt(start, 1)}</span>
            <span>{fmt((start + end) / 2, 1)}</span>
            <span>{fmt(end, 1)} s</span>
          </div>
        </div>
        <div className="unit-grid">
          {names.map((label, i) => (
            <div className="rate-cell" key={label}>
              <div>
                <span>{label}</span>
                <b>{fmt(state?.sample?.rates[i])}</b>
              </div>
              <div className="rate-track">
                <span
                  style={{
                    width: `${Math.min(1, state?.sample?.rates[i] ?? 0) * 100}%`,
                    background: label.endsWith('R') ? '#bc9452' : '#416a55',
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="panel-footnote">
        <span className="tiny-dot" />
        {connectome
          ? `${(state?.connectome?.type_rates.length ?? 0).toLocaleString()} cell types from FlyWire v783 · data-derived wiring, assumed signs, engineered dynamics`
          : '6 engineered rate units · hand-chosen weights'}
        <span>Simulation time, not wall time</span>
      </div>
    </section>
  );
}
