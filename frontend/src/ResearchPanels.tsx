import {memo, useEffect, useState} from 'react';
import {Activity, Eye, Network, ArrowRight} from 'lucide-react';
import type {Command, InterventionChange, NeuralParameters, Sample, State} from './types';
import {fmt} from './format';
import {eyeImageUrl} from './snapshot';
const names = [
  'Sensory L',
  'Sensory R',
  'Steering L',
  'Steering R',
  'Descending L',
  'Descending R',
];

// Up to 6 × 201 contact segments, drawn again only when the history moves on (not while paused).
const GaitRaster = memo(
  function GaitRaster({legs, history}: {run: string; legs: string[]; history: Sample[]}) {
    const end = history.at(-1)?.t ?? 0;
    const start = Math.max(0, end - 4);
    return (
      <svg viewBox="0 0 520 142" role="img" aria-label="Six leg contact traces from MuJoCo physics">
        {legs.map((leg, i) => (
          <g key={leg}>
            <text x="0" y={18 + i * 19}>
              {leg.toUpperCase()}
            </text>
            <line x1="35" x2="514" y1={14 + i * 19} y2={14 + i * 19} stroke="var(--chart-grid)" />
            {history
              .filter((s) => s.t >= start)
              .map((s, j) =>
                s.body_signals.contact?.[i] ? (
                  <rect
                    key={j}
                    x={35 + ((s.t - start) / Math.max(end - start, 0.02)) * 472}
                    y={8 + i * 19}
                    width={Math.max(1, (0.02 / Math.max(end - start, 0.02)) * 472)}
                    height="9"
                    rx="1"
                    fill={i < 3 ? '#52765e' : '#b18b51'}
                  />
                ) : null,
              )}
          </g>
        ))}
        <text x="35" y="137">
          {fmt(start, 1)} s
        </text>
        <text x="479" y="137">
          {fmt(end, 1)} s
        </text>
      </svg>
    );
  },
  (a, b) =>
    a.run === b.run &&
    a.legs.join() === b.legs.join() &&
    a.history.length === b.history.length &&
    a.history[0]?.t === b.history[0]?.t &&
    a.history.at(-1)?.t === b.history.at(-1)?.t,
);

export function BodyMeasurements({state}: {state: State | null}) {
  const signals = state?.sample?.body_signals;
  const history = state?.history ?? [];
  return (
    <section className="panel body-panel">
      <div className="panel-heading">
        <div>
          <Activity size={16} />
          <h2>Body measurements</h2>
        </div>
        <span className="subtle-label">MuJoCo observations</span>
      </div>
      <div className="metric-row">
        {(
          [
            ['Path length', 'path_length_mm', 'mm'],
            ['Displacement', 'displacement_mm', 'mm'],
            ['Mean speed', 'mean_speed_mm_s', 'mm/s'],
            ['Net turn', 'net_turn_deg', '°'],
          ] as const
        ).map(([label, key, unit]) => (
          <div key={key}>
            <span>{label}</span>
            <strong>
              {fmt(state?.metrics[key])}
              <small>{unit}</small>
            </strong>
          </div>
        ))}
      </div>
      {signals?.contact ? (
        <div className="gait-grid">
          <div>
            <h3>Ground contact over time</h3>
            <GaitRaster
              run={state?.run_id ?? ''}
              legs={signals.leg_order ?? []}
              history={history}
            />
            <p className="microcopy">
              Contact threshold: 0.01 µN. Colored segments are sampled contacts.
            </p>
          </div>
          <div className="leg-readouts">
            <h3>Force & walking phase</h3>
            {signals.leg_order?.map((leg, i) => (
              <div key={leg}>
                <span>{leg.toUpperCase()}</span>
                <span className={`contact-pip ${signals.contact?.[i] ? 'on' : ''}`} />
                <b>
                  {fmt(signals.ground_contact_force?.[i], 1)} <small>µN</small>
                </b>
                <svg
                  viewBox="0 0 24 24"
                  aria-label={`${leg} CPG phase ${fmt(signals.cpg_phase_rad?.[i])} radians`}
                >
                  <circle cx="12" cy="12" r="9" fill="none" stroke="var(--chart-grid)" />
                  <path
                    d={`M12 12L${12 + 8 * Math.cos(signals.cpg_phase_rad?.[i] ?? 0)} ${12 + 8 * Math.sin(signals.cpg_phase_rad?.[i] ?? 0)}`}
                    stroke="#5a7550"
                    strokeWidth="1.5"
                  />
                </svg>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="panel-copy">
          Joint and contact measurements are available with the FlyGym body.
        </p>
      )}
      <div className="panel-footnote">
        Physics contact forces · engineered oscillator phases · exported with each run
      </div>
    </section>
  );
}

export function EyePanel({state}: {state: State | null}) {
  if (state?.config.sensor_model !== 'vision' && state?.config.sensor_model !== 'flyvis')
    return null;
  const flyvis = state.config.sensor_model === 'flyvis';
  return (
    <section className="panel eye-panel">
      <div className="panel-heading">
        <div>
          <Eye size={16} />
          <h2>Through the eyes</h2>
        </div>
        <span className="mini-badge">721 OMMATIDIA / EYE</span>
      </div>
      {state.vision.ommatidia_per_eye ? (
        <>
          <div className="eye-labels">
            <span>Left eye</span>
            <span>Right eye</span>
          </div>
          <img
            src={eyeImageUrl(state)}
            alt="Actual FlyGym left and right compound-eye camera images"
          />
          <div className="retina-signal">
            {(['left', 'right'] as const).map((side) => (
              <svg
                key={side}
                viewBox="0 0 360 35"
                preserveAspectRatio="none"
                role="img"
                aria-label={`${side} ommatidial ${flyvis ? 'luminance' : 'contrast features'}`}
              >
                <path
                  d={(state.vision[side] ?? [])
                    .map((v, i) => `${i ? 'L' : 'M'}${(i / 720) * 360},${34 - Math.min(1, v) * 32}`)
                    .join(' ')}
                  stroke={side === 'left' ? '#4c765c' : '#b58f51'}
                  strokeDasharray={side === 'right' ? '4 2' : undefined}
                  strokeWidth=".8"
                  fill="none"
                />
                <text x="3" y="10" className="retina-side">
                  {side === 'left' ? 'L' : 'R'}
                </text>
              </svg>
            ))}
          </div>
        </>
      ) : (
        <p className="panel-copy">Preparing eye images…</p>
      )}
      <p className="panel-copy">
        {flyvis
          ? 'Eye images are rendered every 50 ms. Each ommatidium’s luminance feeds FlyVis (Lappalainen et al. 2024), a connectome-constrained network of 64 optic-lobe cell types stepped every 10 ms. Each type’s strongest response in each eye drives the circuit’s visual projection neurons in proportion to their FlyWire synapses from that type. The traces show the luminance FlyVis receives.'
          : 'A green landmark is rendered in the world. An engineered contrast detector pools the eye pixels into left/right inputs every 50 ms of simulation time.'}
      </p>
    </section>
  );
}

type Circuit = {
  unit_names: string[];
  W: number[][];
  B: number[][];
  bias: number[];
  tau_s: number[];
  equation: string;
};
export function CircuitPanel({
  state,
  command,
  intervene,
  disabled,
}: {
  state: State | null;
  command: Command;
  // Builds on the newest interventions, including one still in flight.
  intervene: (change: InterventionChange) => void;
  disabled: boolean;
}) {
  const [circuit, setCircuit] = useState<Circuit | null>(null);
  const [selected, setSelected] = useState(4);
  const [params, setParams] = useState<NeuralParameters>({
    sensory_gain: 1,
    steering_gain: 1,
    tonic_drive: 0.35,
    time_scale: 1,
  });
  const [loadError, setLoadError] = useState('');
  const configParams = state?.config.neural_parameters;
  useEffect(() => {
    if (configParams) setParams(configParams);
  }, [
    configParams?.sensory_gain,
    configParams?.steering_gain,
    configParams?.tonic_drive,
    configParams?.time_scale,
  ]);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/circuit')
      .then((r) => {
        if (!r.ok)
          throw Error(
            'The six-unit circuit could not be loaded. Check that the local server is still running, then reopen this tab.',
          );
        return r.json();
      })
      .then((d) => {
        if (!cancelled) {
          setCircuit(d);
          setLoadError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [
    configParams?.sensory_gain,
    configParams?.steering_gain,
    configParams?.tonic_drive,
    configParams?.time_scale,
  ]);
  const positions = [
    [100, 90],
    [100, 260],
    [340, 90],
    [340, 260],
    [580, 90],
    [580, 260],
  ];
  const activeBatch = state?.batch && ['running', 'paused'].includes(state.batch.status);
  return (
    <div className="circuit-layout">
      <section className="panel circuit-panel">
        <div className="panel-heading">
          <div>
            <Network size={17} />
            <h2>The active circuit</h2>
          </div>
          <span className="mini-badge">LIVE / ENGINEERED</span>
        </div>
        {loadError && (
          <p role="alert" className="panel-copy">
            {loadError}
          </p>
        )}
        <svg
          viewBox="0 0 680 365"
          className="circuit-svg"
          role="group"
          aria-label="Actual six-unit engineered connectivity with live computed rates"
        >
          <defs>
            <marker
              id="positive-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M0 0L10 5L0 10Z" fill="#6f8c6c" />
            </marker>
            <marker
              id="negative-arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M8 0V10" stroke="#b89158" strokeWidth="2" />
            </marker>
          </defs>
          {[
            ['Input encoding', 100],
            ['Opponent steering', 340],
            ['Descending output', 580],
          ].map(([label, x]) => (
            <text key={label} x={x} y="27" textAnchor="middle" className="circuit-stage">
              {label}
            </text>
          ))}
          {circuit?.W.flatMap((row, post) =>
            row.map((weight, pre) =>
              weight ? (
                <path
                  key={`${pre}-${post}`}
                  d={`M${positions[pre][0] + 34} ${positions[pre][1]} C${positions[pre][0] + 110} ${positions[pre][1]},${positions[post][0] - 110} ${positions[post][1]},${positions[post][0] - 38} ${positions[post][1]}`}
                  fill="none"
                  stroke={weight > 0 ? '#73936e' : '#b48e59'}
                  strokeWidth={Math.min(3, 1 + Math.abs(weight))}
                  opacity={selected === post || selected === pre ? 0.85 : 0.2}
                  strokeDasharray={weight < 0 ? '5 5' : undefined}
                  markerEnd={`url(#${weight > 0 ? 'positive' : 'negative'}-arrow)`}
                >
                  <title>
                    {names[pre]} → {names[post]}: {weight.toFixed(2)}
                  </title>
                </path>
              ) : null,
            ),
          )}
          {names.map((name, i) => (
            <g
              key={name}
              transform={`translate(${positions[i][0]},${positions[i][1]})`}
              className="neuron-node"
              role="button"
              tabIndex={0}
              aria-label={`Inspect ${name}`}
              onClick={() => setSelected(i)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setSelected(i);
              }}
            >
              <circle
                r="40"
                fill="none"
                stroke={selected === i ? '#8ba27a' : 'transparent'}
                strokeWidth="1"
              />
              <circle
                r="32"
                fill={i % 2 ? 'var(--node-fill-alt)' : 'var(--node-fill)'}
                stroke={i % 2 ? '#ba955d' : '#7d9a73'}
              />
              <circle
                r={26 * Math.sqrt(state?.sample?.rates[i] ?? 0)}
                fill={i % 2 ? '#d9bd80' : '#a4bf91'}
                opacity=".45"
              />
              <text textAnchor="middle" y="5" className="node-rate">
                {fmt(state?.sample?.rates[i])}
              </text>
              <text y="58" textAnchor="middle" className="node-name">
                {name}
              </text>
            </g>
          ))}
          <text x="30" y="350" className="circuit-stage">
            Solid arrow: positive weight
          </text>
          <text x="340" y="350" className="circuit-stage">
            Dashed, capped line: negative weight
          </text>
        </svg>
        <div className="panel-footnote">
          Activity is computed in Python. Node positions show circuit stages, not anatomical
          coordinates.
        </div>
      </section>
      <aside className="panel circuit-inspector">
        <span className="eyebrow">SELECTED UNIT</span>
        <h2>{names[selected]}</h2>
        <div className="selected-rate">
          {fmt(state?.sample?.rates[selected], 3)}
          <small>continuous rate</small>
        </div>
        <dl>
          <div>
            <dt>Time constant</dt>
            <dd>{fmt((circuit?.tau_s[selected] ?? 0) * 1000, 0)} ms</dd>
          </div>
          <div>
            <dt>Tonic bias</dt>
            <dd>{fmt(circuit?.bias[selected])}</dd>
          </div>
        </dl>
        <h3>Incoming weights</h3>
        {circuit?.W[selected].map((w, i) =>
          w !== 0 ? (
            <div className="weight-row" key={i}>
              <span>{names[i]}</span>
              <ArrowRight size={12} />
              <b>
                {w > 0 ? '+' : ''}
                {fmt(w)}
              </b>
            </div>
          ) : null,
        )}
        {selected < 2 && (
          <p className="microcopy">
            Receives the {selected === 0 ? 'left' : 'right'} sensor input, gain{' '}
            {fmt(configParams?.sensory_gain)}.
          </p>
        )}
        <button
          className="secondary-button"
          disabled={disabled || !!activeBatch}
          onClick={() =>
            intervene({
              silence: (
                ['sensory', 'sensory', 'steering', 'steering', 'descending', 'descending'] as const
              )[selected],
            })
          }
        >
          Silence this group
        </button>
        <button
          className="text-button"
          disabled={disabled || !!activeBatch}
          onClick={() => intervene({zero_left: false, zero_right: false, silence: 'none'})}
        >
          Restore all inputs & units
        </button>
      </aside>
      <section className="panel parameter-panel">
        <div className="panel-heading">
          <div>
            <h2>Model parameters</h2>
          </div>
          <span className="subtle-label">Changes are recorded for replay</span>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void command('parameters', params);
          }}
        >
          <div className="parameter-fields">
            {(
              [
                ['sensory_gain', 'Sensory gain', 0, 3, 0.1],
                ['steering_gain', 'Steering gain', 0, 3, 0.1],
                ['tonic_drive', 'Tonic drive', 0, 1, 0.05],
                ['time_scale', 'Time-constant multiplier', 0.25, 4, 0.25],
              ] as const
            ).map(([key, label, min, max, step]) => (
              <label key={key}>
                {label}
                <input
                  aria-label={label}
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  required
                  value={params[key]}
                  disabled={disabled || !!activeBatch}
                  onChange={(e) => setParams({...params, [key]: Number(e.target.value)})}
                />
              </label>
            ))}
          </div>
          <button className="primary-button" disabled={disabled || !!activeBatch}>
            Apply parameters
          </button>
        </form>
        <p className="panel-copy">
          The six units use explicit leaky-rate dynamics. Anatomical datasets in the explorer are
          independent of this controller; loading a graph does not replace its weights.
        </p>
        <code className="equation">r += dt / τ × [clip(Wr + Bs + bias, 0, 1) − r]</code>
      </section>
    </div>
  );
}
