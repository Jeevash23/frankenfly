import {useEffect, useMemo, useState} from 'react';
import {ArrowRight, Network, Search} from 'lucide-react';
import type {Command, ConnectomeParameters, State} from '../types';
import {fmt} from '../format';
import {useCircuit} from './useCircuit';
import {
  activityColor,
  DNA02_X,
  edgesToDraw,
  layoutTypes,
  topPartners,
  VIEW,
  type CircuitSummary,
  type Node,
} from './layout';
import './connectome.css';

const DNA02_Y = {left: 196, right: 376};
const SIGN_TEXT: Record<number, string> = {1: 'excitatory', [-1]: 'inhibitory', 0: 'excluded'};
const DRAWN_EDGES = 140;
const DRAWN_DNA02_INPUTS = 12;

function curve(a: {x: number; y: number}, b: {x: number; y: number}) {
  if (Math.abs(a.x - b.x) < 1) {
    const bend = a.x - 40;
    return `M${a.x} ${a.y} C${bend} ${a.y},${bend} ${b.y},${b.x} ${b.y}`;
  }
  const dx = (b.x - a.x) * 0.45;
  return `M${a.x} ${a.y} C${a.x + dx} ${a.y},${b.x - dx} ${b.y},${b.x} ${b.y}`;
}

function Edge({
  from,
  to,
  sign,
  synapses,
  faded,
  title,
}: {
  from: {x: number; y: number};
  to: {x: number; y: number};
  sign: number;
  synapses: number;
  faded: boolean;
  title: string;
}) {
  return (
    <path
      d={curve(from, to)}
      fill="none"
      stroke={sign > 0 ? '#73936e' : '#b48e59'}
      strokeWidth={Math.min(3.2, 0.5 + Math.log10(synapses))}
      strokeDasharray={sign > 0 ? undefined : '5 4'}
      opacity={faded ? 0.08 : 0.5}
      markerEnd={`url(#connectome-${sign > 0 ? 'positive' : 'negative'})`}
    >
      <title>{title}</title>
    </path>
  );
}

function ParameterForm({
  state,
  command,
  disabled,
}: {
  state: State | null;
  command: Command;
  disabled: boolean;
}) {
  const current = state?.config.connectome_parameters;
  const [params, setParams] = useState<ConnectomeParameters | null>(current ?? null);
  const key = JSON.stringify(current);
  useEffect(() => {
    if (current) setParams(current);
  }, [key]);
  if (!params) return null;
  const fields = [
    ['synapse_threshold', 'Synapse threshold', 5, 100, 1],
    ['global_gain', 'Global gain', 0, 1, 0.0001],
    ['input_gain', 'Input gain', 0, 10, 0.1],
    ['output_gain', 'Output gain', 0, 20, 0.1],
    ['tonic_drive', 'Tonic drive', 0, 1, 0.05],
    ['tau_ms', 'Time constant (ms)', 5, 200, 1],
  ] as const;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void command('connectome/parameters', params);
      }}
    >
      <div className="parameter-fields">
        {fields.map(([field, label, min, max, step]) => (
          <label key={field}>
            {label}
            <input
              aria-label={label}
              type="number"
              min={min}
              max={max}
              step={step}
              required
              value={params[field]}
              disabled={disabled}
              onChange={(e) => setParams({...params, [field]: Number(e.target.value)})}
            />
          </label>
        ))}
        <label>
          Dopamine, serotonin, octopamine, unknown
          <select
            aria-label="Sign of other transmitters"
            value={params.other_transmitters}
            disabled={disabled}
            onChange={(e) =>
              setParams({
                ...params,
                other_transmitters: e.target.value as ConnectomeParameters['other_transmitters'],
              })
            }
          >
            <option value="excluded">Excluded (default)</option>
            <option value="excitatory">Excitatory (Shiu et al. 2024)</option>
          </select>
        </label>
      </div>
      <button className="primary-button" disabled={disabled}>
        Apply parameters
      </button>
    </form>
  );
}

export function ConnectomeCircuitView({
  state,
  command,
  disabled,
}: {
  state: State | null;
  command: Command;
  disabled: boolean;
}) {
  const {circuit, error} = useCircuit(state);
  const [selected, setSelected] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const activeBatch = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const controlsDisabled = disabled || activeBatch;
  const layout = useMemo(
    () =>
      circuit ? layoutTypes(circuit.types, circuit.dna02.type_index) : new Map<number, Node>(),
    [circuit],
  );
  const drawn = useMemo(
    () =>
      circuit
        ? edgesToDraw(circuit.edges, DRAWN_EDGES, selected).filter(
            (i) =>
              circuit.edges.pre[i] !== circuit.dna02.type_index &&
              circuit.edges.post[i] !== circuit.dna02.type_index,
          )
        : [],
    [circuit, selected],
  );
  if (!circuit)
    return (
      <section className="panel empty-research" role="status">
        <Network size={28} />
        <h3>
          {error ? 'The connectome circuit is unavailable.' : 'Loading the connectome circuit…'}
        </h3>
        {error && <p>{error}</p>}
      </section>
    );
  const rates = state?.connectome?.type_rates ?? [];
  const dna02 = {left: state?.sample?.rates[0] ?? 0, right: state?.sample?.rates[1] ?? 0};
  const silenced = new Set(state?.interventions.silence_types ?? []);
  const dna02Silenced = state?.interventions.silence_dna02 ?? 'none';
  const selectedType = selected !== null ? circuit.types[selected] : null;
  const name = (index: number) => circuit.types[index]?.name ?? '?';
  const inputs = (side: 'left' | 'right') => {
    const edges = circuit.dna02_inputs[side];
    return edges.synapses
      .map((synapses, i) => ({pre: edges.pre[i], sign: edges.sign[i], synapses}))
      .sort((a, b) => b.synapses - a.synapses || a.pre - b.pre);
  };
  const silence = (types: string[]) =>
    void command('interventions', {...state?.interventions, silence_types: types});
  const matches = query
    ? circuit.types
        .map((t, i) => ({t, i}))
        .filter(({t}) => t.name.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 8)
    : [];
  return (
    <div className="circuit-layout">
      <section className="panel circuit-panel">
        <div className="panel-heading">
          <div>
            <Network size={17} />
            <h2>The DNa02 circuit</h2>
          </div>
          <span className="mini-badge">LIVE / FLYWIRE V783</span>
        </div>
        <div className="connectome-labels" aria-label="What each part of the model is">
          <span>
            Wiring <b>data-derived</b>
          </span>
          <span>
            Signs <b>assumed</b>
          </span>
          <span>
            Dynamics <b>engineered</b>
          </span>
          <span>
            Sensor input <b>engineered</b>
          </span>
        </div>
        <svg
          viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
          className="circuit-svg connectome-svg"
          role="group"
          aria-label="Connectome circuit by cell type, from two hops back to DNa02, with live computed activity"
        >
          <defs>
            <marker
              id="connectome-positive"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M0 0L10 5L0 10Z" fill="#6f8c6c" />
            </marker>
            <marker
              id="connectome-negative"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto-start-reverse"
            >
              <path d="M8 0V10" stroke="#b89158" strokeWidth="2" />
            </marker>
          </defs>
          {[
            ['Hop 2 · inputs to hop 1', 261],
            ['Hop 1 · direct inputs', 672],
            ['DNa02', DNA02_X],
          ].map(([label, x]) => (
            <text key={label} x={x} y="30" textAnchor="middle" className="circuit-stage">
              {label}
            </text>
          ))}
          {drawn.map((i) => {
            const from = layout.get(circuit.edges.pre[i]);
            const to = layout.get(circuit.edges.post[i]);
            if (!from || !to) return null;
            const involved =
              selected === null ||
              circuit.edges.pre[i] === selected ||
              circuit.edges.post[i] === selected;
            return (
              <Edge
                key={i}
                from={from}
                to={to}
                sign={circuit.edges.sign[i]}
                synapses={circuit.edges.synapses[i]}
                faded={!involved}
                title={`${name(circuit.edges.pre[i])} → ${name(circuit.edges.post[i])}: ${circuit.edges.synapses[i]} synapses, ${SIGN_TEXT[circuit.edges.sign[i]]} (assumed)`}
              />
            );
          })}
          {(['left', 'right'] as const).flatMap((side) =>
            inputs(side)
              .filter((e) => selected === null || e.pre === selected)
              .slice(0, selected === null ? DRAWN_DNA02_INPUTS : undefined)
              .map((e) => {
                const from = layout.get(e.pre);
                if (!from) return null;
                return (
                  <Edge
                    key={`${side}-${e.pre}-${e.sign}`}
                    from={from}
                    to={{x: DNA02_X - 30, y: DNA02_Y[side]}}
                    sign={e.sign}
                    synapses={e.synapses}
                    faded={false}
                    title={`${name(e.pre)} → DNa02 ${side}: ${e.synapses} synapses, ${SIGN_TEXT[e.sign]} (assumed)`}
                  />
                );
              }),
          )}
          {circuit.types.map((type, i) => {
            const node = layout.get(i);
            if (!node) return null;
            const active = selected === i;
            return (
              <g
                key={type.name}
                className="type-node"
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${type.name}: ${type.count} neurons, mean rate ${fmt(rates[i])}`}
                onClick={() => setSelected(active ? null : i)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setSelected(active ? null : i);
                }}
              >
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.r}
                  fill={silenced.has(type.name) ? '#e7e2d6' : activityColor(rates[i] ?? 0)}
                  stroke={active ? '#ba9455' : type.input ? '#c29a55' : '#9fb390'}
                  strokeWidth={active ? 2.5 : type.input ? 1.4 : 0.7}
                  strokeDasharray={silenced.has(type.name) ? '2 2' : undefined}
                >
                  <title>
                    {type.name} · {type.count} neurons · hop {type.layer} · {type.transmitter}
                  </title>
                </circle>
                {(active || type.count >= 12) && (
                  <text
                    x={node.x}
                    y={node.y - node.r - 3}
                    textAnchor="middle"
                    className="type-label"
                  >
                    {type.name}
                  </text>
                )}
              </g>
            );
          })}
          {(['left', 'right'] as const).map((side) => (
            <g key={side} transform={`translate(${DNA02_X},${DNA02_Y[side]})`}>
              <circle
                r="30"
                fill={activityColor(dna02[side])}
                stroke={side === 'left' ? '#52765e' : '#b18b51'}
                strokeWidth="2"
                strokeDasharray={side === 'right' ? '5 3' : undefined}
              />
              <text y="5" textAnchor="middle" className="dna02-rate">
                {dna02Silenced === side || dna02Silenced === 'both' ? 'off' : fmt(dna02[side])}
              </text>
              <text y="48" textAnchor="middle" className="dna02-label">
                DNa02 {side === 'left' ? 'L (left)' : 'R (right)'}
              </text>
            </g>
          ))}
          <text x={DNA02_X} y="472" textAnchor="middle" className="circuit-stage">
            turn = {fmt(state?.config.connectome_parameters.output_gain, 1)} × (R − L)
          </text>
          <text x={DNA02_X} y="488" textAnchor="middle" className="dna02-label">
            {fmt(state?.connectome?.turn)}{' '}
            {(state?.connectome?.turn ?? 0) > 0.005
              ? '→ right'
              : (state?.connectome?.turn ?? 0) < -0.005
                ? '← left'
                : 'straight'}
          </text>
        </svg>
        <div className="connectome-legend">
          <span>
            <svg width="26" height="8" aria-hidden="true">
              <path d="M1 4H25" stroke="#73936e" strokeWidth="2" />
            </svg>
            Solid: excitatory (acetylcholine)
          </span>
          <span>
            <svg width="26" height="8" aria-hidden="true">
              <path d="M1 4H25" stroke="#b48e59" strokeWidth="2" strokeDasharray="5 4" />
            </svg>
            Dashed, capped: inhibitory (GABA, glutamate)
          </span>
          <span>
            <svg width="14" height="14" aria-hidden="true">
              <circle cx="7" cy="7" r="5.5" fill="#f4f1e8" stroke="#c29a55" strokeWidth="1.4" />
            </svg>
            Gold ring: visual projection neurons that receive the sensor input
          </span>
          <span>Node size: neurons in the type · fill: live mean rate</span>
        </div>
        <div className="panel-footnote">
          {circuit.neurons.toLocaleString()} neurons, {circuit.types.length.toLocaleString()} cell
          types, {circuit.connections_active.toLocaleString()} active connections · the{' '}
          {DRAWN_EDGES} strongest type-to-type connections shown · positions are hop distance, not
          anatomy
        </div>
      </section>
      <aside className="panel circuit-inspector">
        <label className="type-search">
          <Search size={13} />
          <input
            aria-label="Find a cell type"
            placeholder="Find a cell type"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {matches.map(({t, i}) => (
          <button
            key={t.name}
            className="text-button"
            onClick={() => {
              setSelected(i);
              setQuery('');
            }}
          >
            {t.name} · {t.count} <ArrowRight size={11} />
          </button>
        ))}
        {selectedType && selected !== null ? (
          <>
            <span className="eyebrow">SELECTED CELL TYPE</span>
            <h2>{selectedType.name}</h2>
            <div className="selected-rate">
              {silenced.has(selectedType.name) ? 'silenced' : fmt(rates[selected], 3)}
              <small>mean computed rate across its neurons</small>
            </div>
            <dl>
              <div>
                <dt>Neurons in the circuit</dt>
                <dd>
                  {selectedType.count} · {selectedType.left} left, {selectedType.right} right
                </dd>
              </div>
              <div>
                <dt>Hops to DNa02 (closest member)</dt>
                <dd>{selectedType.layer}</dd>
              </div>
              <div>
                <dt>Predicted transmitter</dt>
                <dd>
                  {Object.entries(selectedType.transmitters)
                    .map(([nt, count]) => `${nt} ${count}`)
                    .join(', ')}{' '}
                  → {SIGN_TEXT[selectedType.sign]} (assumed)
                </dd>
              </div>
              <div>
                <dt>Super class</dt>
                <dd>
                  {selectedType.super_class.replaceAll('_', ' ')}
                  {selectedType.input ? ' · receives sensor input' : ''}
                </dd>
              </div>
            </dl>
            {(['in', 'out'] as const).map((direction) => (
              <div key={direction}>
                <h3>{direction === 'in' ? 'Strongest inputs' : 'Strongest outputs'}</h3>
                {topPartners(circuit.edges, selected, direction, 5).map((p) => (
                  <div className="weight-row" key={`${p.type}-${p.sign}`}>
                    <span>{name(p.type)}</span>
                    <b>
                      {p.sign > 0 ? '+' : '−'}
                      {p.synapses}
                    </b>
                  </div>
                ))}
              </div>
            ))}
            <button
              className="secondary-button"
              disabled={controlsDisabled || silenced.has(selectedType.name)}
              onClick={() => silence([...silenced, selectedType.name])}
            >
              Silence {selectedType.name}
            </button>
          </>
        ) : (
          <>
            <span className="eyebrow">STEERING OUTPUT</span>
            <h2>DNa02 left & right</h2>
            <dl>
              <div>
                <dt>DNa02 L (left) · computed rate</dt>
                <dd>{fmt(dna02.left, 3)}</dd>
              </div>
              <div>
                <dt>DNa02 R (right) · computed rate</dt>
                <dd>{fmt(dna02.right, 3)}</dd>
              </div>
              <div>
                <dt>Turn command</dt>
                <dd>
                  {fmt(state?.connectome?.turn, 3)} · positive turns right (Rayshubskiy et al. 2025)
                </dd>
              </div>
            </dl>
            <p className="microcopy">Click a cell type, or find one by name, to inspect it.</p>
          </>
        )}
        {silenced.size > 0 && (
          <div className="silenced-types" aria-label="Silenced cell types">
            {[...silenced].map((type) => (
              <button
                key={type}
                disabled={controlsDisabled}
                onClick={() => silence([...silenced].filter((t) => t !== type))}
                aria-label={`Restore ${type}`}
              >
                {type} ×
              </button>
            ))}
          </div>
        )}
        <button
          className="text-button"
          disabled={controlsDisabled}
          onClick={() =>
            void command('interventions', {
              zero_left: false,
              zero_right: false,
              silence: 'none',
              silence_dna02: 'none',
              silence_types: [],
            })
          }
        >
          Restore all inputs & neurons
        </button>
      </aside>
      <section className="panel parameter-panel">
        <div className="panel-heading">
          <div>
            <h2>Global parameters</h2>
          </div>
          <span className="subtle-label">
            No per-neuron or per-synapse tuning · recorded for replay
          </span>
        </div>
        <ParameterForm state={state} command={command} disabled={controlsDisabled} />
        <p className="panel-copy">
          Every connection weight is its predicted sign × synapse count × the global gain. Sensor
          values drive the visual projection neurons on their side. Forward drive is the tonic term;
          turning comes from the right − left difference of the two DNa02 neurons.
        </p>
        <code className="equation">
          r += dt / τ × [clip(W r + input, 0, 1) − r] · W = sign × synapses × gain
        </code>
        <CircuitSource circuit={circuit} />
      </section>
    </div>
  );
}

function CircuitSource({circuit}: {circuit: CircuitSummary}) {
  return (
    <p className="panel-copy">
      {circuit.provenance.dataset} {circuit.provenance.release} · {circuit.provenance.specimen} ·{' '}
      {circuit.provenance.coverage}. {circuit.provenance.license}. Circuit file SHA-256{' '}
      {circuit.sha256.slice(0, 12)}…
    </p>
  );
}
