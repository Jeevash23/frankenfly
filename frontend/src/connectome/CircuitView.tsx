import {useEffect, useMemo, useState} from 'react';
import {ArrowRight, Network, Route, Search} from 'lucide-react';
import type {Command, Config, ConnectomeParameters, State} from '../types';
import {fmt} from '../format';
import {dynamicsLabels, readoutPairs} from '../models';
import {useCircuit} from './useCircuit';
import {parseTypes} from './build';
import {
  activityColor,
  edgesToDraw,
  layoutTypes,
  readoutRows,
  READOUT_X,
  topPartners,
  VIEW,
  type CircuitSummary,
  type CircuitType,
  type Node,
} from './layout';
import './connectome.css';

const SIGN_TEXT: Record<number, string> = {1: 'excitatory', [-1]: 'inhibitory', 0: 'excluded'};
const DRAWN_EDGES = 140;
const DRAWN_READOUT_INPUTS = 12;

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
  reset,
  disabled,
}: {
  state: State | null;
  command: Command;
  reset: (override?: Partial<Config>) => void;
  disabled: boolean;
}) {
  const current = state?.config.connectome_parameters;
  const [params, setParams] = useState<ConnectomeParameters | null>(current ?? null);
  const [populations, setPopulations] = useState({readout: '', input: '', speed: ''});
  const key = JSON.stringify(current);
  useEffect(() => {
    if (!current) return;
    setParams(current);
    setPopulations({
      readout: (current.readout_types ?? []).join('; '),
      input: (current.input_types ?? []).join('; '),
      speed: current.speed_types.join('; '),
    });
  }, [key]);
  if (!params || !current) return null;
  const spiking = params.dynamics === 'spiking';
  const fields = [
    ['synapse_threshold', 'Synapse threshold', 1, 1000, 1],
    ...(spiking ? [] : ([['global_gain', 'Global gain', 0, 1, 0.0001]] as const)),
    ['input_gain', 'Input gain', 0, 10, 0.1],
    ['output_gain', 'Output gain', 0, 20, 0.1],
    ['tonic_drive', 'Tonic drive', 0, 1, 0.05],
    ...(spiking ? [] : ([['tau_ms', 'Time constant (ms)', 5, 200, 1]] as const)),
    ...(params.speed_types.length ? ([['speed_gain', 'Speed gain', 0, 10, 0.1]] as const) : []),
  ] as const;
  const spikingFields = [
    ['synapse_weight_mv', 'Weight per synapse (mV)', 0.001, 5, 0.005],
    ['input_rate_hz', 'Input rate at sensor 1 (Hz)', 0, 1000, 5],
    ['rate_window_ms', 'Rate readout window (ms)', 5, 1000, 5],
    ['rate_scale_hz', 'Rate treated as activity 1 (Hz)', 1, 1000, 5],
  ] as const;
  const resetWithPopulations = () =>
    reset({
      connectome_parameters: {
        ...current,
        readout_types: parseTypes(populations.readout),
        input_types: parseTypes(populations.input),
        speed_types: parseTypes(populations.speed) ?? [],
      },
    });
  return (
    <>
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
          {spiking &&
            spikingFields.map(([field, label, min, max, step]) => (
              <label key={field}>
                {label}
                <input
                  aria-label={label}
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  required
                  value={params.spiking[field]}
                  disabled={disabled}
                  onChange={(e) =>
                    setParams({
                      ...params,
                      spiking: {...params.spiking, [field]: Number(e.target.value)},
                    })
                  }
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
      <form
        className="population-form"
        onSubmit={(e) => {
          e.preventDefault();
          resetWithPopulations();
        }}
      >
        <h3>Populations by cell type</h3>
        <p className="microcopy">
          Separate names with semicolons. Leave a field empty for the circuit's default. Changing
          them starts a fresh run.
        </p>
        {(
          [
            ['readout', 'Steering readout (right − left, summed)', 'e.g. DNa01; DNa02'],
            ['input', 'Sensor input (each side drives its own neurons)', 'All visual projection'],
            ['speed', 'Speed drive (adds to forward drive)', 'None, e.g. DNp09'],
          ] as const
        ).map(([field, label, placeholder]) => (
          <label key={field} className="field-label">
            {label}
            <input
              aria-label={label}
              value={populations[field]}
              placeholder={placeholder}
              disabled={disabled}
              onChange={(e) => setPopulations({...populations, [field]: e.target.value})}
            />
          </label>
        ))}
        <button className="secondary-button" disabled={disabled}>
          Reset with these populations
        </button>
      </form>
    </>
  );
}

type Path = {cell_types: string[]; strength: number; net_sign: number};

function PathTrace({source, targets}: {source: string; targets: string[]}) {
  const [target, setTarget] = useState(targets[0] ?? '');
  const [paths, setPaths] = useState<Path[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setPaths(null);
    setError('');
  }, [source, target]);
  useEffect(() => {
    if (!targets.includes(target)) setTarget(targets[0] ?? '');
  }, [targets.join('\n')]);
  const trace = () => {
    setLoading(true);
    const query = new URLSearchParams({source, target, max_hops: '4', limit: '5'});
    fetch(`/api/connectome/paths?${query}`)
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'No paths found.');
        setPaths(data.paths);
        setError('');
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  if (!targets.length || targets.includes(source)) return null;
  return (
    <div className="path-trace">
      <h3>
        <Route size={13} /> Strongest paths
      </h3>
      <div className="path-controls">
        <span>to</span>
        <select aria-label="Path target" value={target} onChange={(e) => setTarget(e.target.value)}>
          {targets.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <button className="text-button" onClick={trace} disabled={loading}>
          {loading ? 'Tracing…' : 'Trace'}
        </button>
      </div>
      {error && <p className="microcopy">{error}</p>}
      {paths && !paths.length && <p className="microcopy">No path within four steps.</p>}
      {paths?.map((p) => (
        <div className="path-row" key={p.cell_types.join('>')}>
          <span>{p.cell_types.join(' → ')}</span>
          <b title="Product of input fractions along the path; sign multiplies the assumed signs">
            {p.net_sign > 0 ? '+' : '−'}
            {fmt(p.strength, 3)}
          </b>
        </div>
      ))}
      {paths && paths.length > 0 && (
        <p className="microcopy">
          Strength multiplies each step's share of its target's input synapses. Signs are assumed.
        </p>
      )}
    </div>
  );
}

export function ConnectomeCircuitView({
  state,
  command,
  reset,
  disabled,
}: {
  state: State | null;
  command: Command;
  reset: (override?: Partial<Config>) => void;
  disabled: boolean;
}) {
  const {circuit, error} = useCircuit(state);
  const [selected, setSelected] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const activeBatch = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const controlsDisabled = disabled || activeBatch;
  const readoutIndex = useMemo(
    () => new Set(circuit?.readouts.map((r) => r.type_index) ?? []),
    [circuit],
  );
  const byIndex = useMemo(
    () => new Map<number, CircuitType>(circuit?.types.map((t) => [t.index, t]) ?? []),
    [circuit],
  );
  const layout = useMemo(
    () => (circuit ? layoutTypes(circuit.types, readoutIndex) : new Map<number, Node>()),
    [circuit, readoutIndex],
  );
  const drawn = useMemo(
    () =>
      circuit
        ? edgesToDraw(circuit.edges, DRAWN_EDGES, selected).filter(
            (i) =>
              !readoutIndex.has(circuit.edges.pre[i]) && !readoutIndex.has(circuit.edges.post[i]),
          )
        : [],
    [circuit, selected, readoutIndex],
  );
  useEffect(() => setSelected(null), [circuit?.name]);
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
  return (
    <CircuitDiagram
      circuit={circuit}
      state={state}
      command={command}
      reset={reset}
      controlsDisabled={controlsDisabled}
      selected={selected}
      setSelected={setSelected}
      query={query}
      setQuery={setQuery}
      layout={layout}
      drawn={drawn}
      byIndex={byIndex}
    />
  );
}

function CircuitDiagram({
  circuit,
  state,
  command,
  reset,
  controlsDisabled,
  selected,
  setSelected,
  query,
  setQuery,
  layout,
  drawn,
  byIndex,
}: {
  circuit: CircuitSummary;
  state: State | null;
  command: Command;
  reset: (override?: Partial<Config>) => void;
  controlsDisabled: boolean;
  selected: number | null;
  setSelected: (index: number | null) => void;
  query: string;
  setQuery: (query: string) => void;
  layout: Map<number, Node>;
  drawn: number[];
  byIndex: Map<number, CircuitType>;
}) {
  const rates = state?.connectome?.type_rates ?? [];
  const dynamics = state?.config.connectome_parameters.dynamics ?? 'rate';
  const silenced = new Set(state?.interventions.silence_types ?? []);
  const dna02Silenced = state?.interventions.silence_dna02 ?? 'none';
  const pairs = readoutPairs(circuit.readouts.map((r) => r.cell_type));
  const rows = readoutRows(circuit.readouts.length);
  const radius = Math.max(
    12,
    Math.min(30, (VIEW.bottom - 70 - VIEW.top) / circuit.readouts.length / 6),
  );
  const sampleRate = (index: number) => state?.sample?.rates[index] ?? 0;
  const isOff = (name: string, side: 'left' | 'right') =>
    silenced.has(name) ||
    (name === 'DNa02' && (dna02Silenced === side || dna02Silenced === 'both'));
  const selectedType = selected !== null ? (byIndex.get(selected) ?? null) : null;
  const name = (index: number) => byIndex.get(index)?.name ?? '?';
  const silence = (types: string[]) =>
    void command('interventions', {...state?.interventions, silence_types: types});
  const matches = query
    ? circuit.types.filter((t) => t.name.toLowerCase().includes(query.toLowerCase())).slice(0, 8)
    : [];
  const readoutNames = circuit.readouts.map((r) => r.cell_type);
  const subset = circuit.types_shown < circuit.types_total;
  return (
    <div className="circuit-layout">
      <section className="panel circuit-panel">
        <div className="panel-heading">
          <div>
            <Network size={17} />
            <h2>The {circuit.name} circuit</h2>
          </div>
          <span className="mini-badge">
            LIVE / FLYWIRE V783 / {dynamics === 'spiking' ? 'SPIKING' : 'RATE'}
          </span>
        </div>
        <div className="connectome-labels" aria-label="What each part of the model is">
          <span>
            Wiring <b>data-derived</b>
          </span>
          <span>
            Signs <b>assumed</b>
          </span>
          <span>
            Dynamics <b>{dynamicsLabels[dynamics]}</b>
          </span>
          <span>
            Sensor input & readout <b>engineered</b>
          </span>
        </div>
        <svg
          viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
          className="circuit-svg connectome-svg"
          role="group"
          aria-label={`Connectome circuit by cell type, from deeper inputs to the ${readoutNames.join(', ')} readout, with live computed activity`}
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
            ['Hop 2+ · deeper inputs', 261],
            ['Hop 1 · direct inputs', 672],
            ['Readout', READOUT_X],
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
          {circuit.readouts.flatMap((readout, k) =>
            (['left', 'right'] as const).flatMap((side) => {
              const edges = readout.inputs[side];
              return edges.synapses
                .map((synapses, i) => ({pre: edges.pre[i], sign: edges.sign[i], synapses}))
                .sort((a, b) => b.synapses - a.synapses || a.pre - b.pre)
                .filter((e) => selected === null || e.pre === selected)
                .slice(
                  0,
                  selected === null
                    ? Math.ceil(DRAWN_READOUT_INPUTS / circuit.readouts.length)
                    : undefined,
                )
                .map((e) => {
                  const from = layout.get(e.pre);
                  if (!from) return null;
                  return (
                    <Edge
                      key={`${k}-${side}-${e.pre}-${e.sign}`}
                      from={from}
                      to={{x: READOUT_X - radius, y: rows[k][side]}}
                      sign={e.sign}
                      synapses={e.synapses}
                      faded={false}
                      title={`${name(e.pre)} → ${readout.cell_type} ${side}: ${e.synapses} synapses, ${SIGN_TEXT[e.sign]} (assumed)`}
                    />
                  );
                });
            }),
          )}
          {circuit.types.map((type) => {
            const node = layout.get(type.index);
            if (!node) return null;
            const active = selected === type.index;
            return (
              <g
                key={type.index}
                className="type-node"
                role="button"
                tabIndex={0}
                aria-label={`Inspect ${type.name}: ${type.count} neurons, mean activity ${fmt(rates[type.index])}`}
                onClick={() => setSelected(active ? null : type.index)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setSelected(active ? null : type.index);
                }}
              >
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.r}
                  fill={silenced.has(type.name) ? '#e7e2d6' : activityColor(rates[type.index] ?? 0)}
                  stroke={active ? '#ba9455' : type.input ? '#c29a55' : '#9fb390'}
                  strokeWidth={active ? 2.5 : type.input ? 1.4 : 0.7}
                  strokeDasharray={silenced.has(type.name) ? '2 2' : undefined}
                >
                  <title>
                    {type.name} · {type.count} neurons · hop {type.layer < 0 ? 'none' : type.layer}{' '}
                    · {type.transmitter}
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
          {circuit.readouts.flatMap((readout, k) =>
            (['left', 'right'] as const).map((side) => {
              const value = sampleRate(side === 'left' ? pairs[k].left : pairs[k].right);
              return (
                <g
                  key={`${readout.cell_type}-${side}`}
                  transform={`translate(${READOUT_X},${rows[k][side]})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`Inspect ${readout.cell_type}`}
                  onClick={() => setSelected(readout.type_index)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') setSelected(readout.type_index);
                  }}
                >
                  <circle
                    r={radius}
                    fill={activityColor(value)}
                    stroke={side === 'left' ? '#52765e' : '#b18b51'}
                    strokeWidth="2"
                    strokeDasharray={side === 'right' ? '5 3' : undefined}
                  />
                  <text y="5" textAnchor="middle" className="dna02-rate">
                    {isOff(readout.cell_type, side) ? 'off' : fmt(value)}
                  </text>
                  <text y={radius + 12} textAnchor="middle" className="dna02-label">
                    {readout.cell_type} {side === 'left' ? 'L' : 'R'}
                  </text>
                </g>
              );
            }),
          )}
          <text x={READOUT_X} y="520" textAnchor="middle" className="circuit-stage">
            turn = {fmt(state?.config.connectome_parameters.output_gain, 1)} × Σ (R − L)
          </text>
          <text x={READOUT_X} y="536" textAnchor="middle" className="dna02-label">
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
            Gold ring: neurons that receive the sensor input
          </span>
          <span>
            Node size: neurons in the type · fill: live mean{' '}
            {dynamics === 'spiking' ? 'firing rate ÷ rate scale' : 'rate'}
          </span>
        </div>
        <div className="panel-footnote">
          {circuit.neurons.toLocaleString()} neurons, {circuit.types_total.toLocaleString()} cell
          types
          {subset ? ` (the ${circuit.types_shown.toLocaleString()} nearest the readout shown)` : ''}
          , {circuit.connections_active.toLocaleString()} active connections · the {DRAWN_EDGES}{' '}
          strongest type-to-type connections drawn · positions are hop distance, not anatomy
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
        {matches.map((t) => (
          <button
            key={t.index}
            className="text-button"
            onClick={() => {
              setSelected(t.index);
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
              <small>
                mean computed {dynamics === 'spiking' ? 'activity (rate ÷ scale)' : 'rate'} across
                its neurons
              </small>
            </div>
            <dl>
              <div>
                <dt>Neurons in the circuit</dt>
                <dd>
                  {selectedType.count} · {selectedType.left} left, {selectedType.right} right
                </dd>
              </div>
              <div>
                <dt>Hops to the seeds (closest member)</dt>
                <dd>{selectedType.layer < 0 ? 'not connected to them' : selectedType.layer}</dd>
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
                  {readoutNames.includes(selectedType.name) ? ' · steering readout' : ''}
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
            <PathTrace source={selectedType.name} targets={readoutNames} />
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
            <h2>{readoutNames.join(' + ')}</h2>
            <dl>
              {pairs.map((pair) =>
                (['left', 'right'] as const).map((side) => (
                  <div key={`${pair.name}-${side}`}>
                    <dt>
                      {pair.name} {side === 'left' ? 'L (left)' : 'R (right)'} · computed{' '}
                      {dynamics === 'spiking' ? 'activity' : 'rate'}
                    </dt>
                    <dd>{fmt(sampleRate(side === 'left' ? pair.left : pair.right), 3)}</dd>
                  </div>
                )),
              )}
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
        <ParameterForm state={state} command={command} reset={reset} disabled={controlsDisabled} />
        <p className="panel-copy">
          {dynamics === 'spiking'
            ? 'Leaky integrate-and-fire neurons with the constants of Shiu et al. 2024: each spike adds sign × synapses × the weight per synapse to its targets 1.8 ms later. Sensor values set the Poisson input rate of the input neurons on their side.'
            : 'Every connection weight is its predicted sign × synapse count × the global gain. Sensor values drive the input neurons on their side.'}{' '}
          Forward drive is the tonic term
          {state?.config.connectome_parameters.speed_types.length ? ' plus the speed drive' : ''};
          turning is the right − left difference summed over {readoutNames.join(', ')} (equal
          weights, assumed).
        </p>
        <code className="equation">
          {dynamics === 'spiking'
            ? 'dv/dt = (v_rest − v + g) / τm · dg/dt = −g / τs · spike: g_post += sign × synapses × w'
            : 'r += dt / τ × [clip(W r + input, 0, 1) − r] · W = sign × synapses × gain'}
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
