import {useEffect, useMemo, useState} from 'react';
import {
  Copy,
  ExternalLink,
  Hammer,
  LoaderCircle,
  MoveUpRight,
  Network,
  Search,
  VolumeX,
  Zap,
} from 'lucide-react';
import type {InterventionChange, Side, State} from '../types';
import {describeError} from '../errors';
import {withCellType, manipulationLabel} from '../interventions';
import {DRAFT_KEYS, loadDraft, readBuildDraft, saveDraft} from '../localDrafts';
import {
  QUERIES,
  buildDraft,
  compact,
  defaultForm,
  formProblem,
  manipulationBlocker,
  pathGroups,
  percent,
  queryNames,
  queryUrl,
  rowGroups,
  rowManipulation,
  rowSide,
  signText,
  type ExploreForm,
  type InCircuit,
  type NeuroglancerGroup,
  type NeuronRow,
  type Query,
  type TypeRow,
} from './explore';
import './connectome.css';

type GraphInfo = {
  key: string;
  title: string;
  available: boolean;
  reason?: string;
  neurons?: number;
};
type Result = {kind: Query; data: any; seconds: number};
type Link = {url: string; neurons: number; truncated: boolean; label: string};

// The form and the last result survive switching tabs (not reloads).
let remembered: {form: ExploreForm; kind: Query; result: Result | null} = {
  form: defaultForm,
  kind: 'partners',
  result: null,
};

async function getJson(url: string, init?: RequestInit) {
  const response = await fetch(url, {...init, signal: AbortSignal.timeout(60000)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(describeError(data.detail, response.status));
  return data;
}

// Cell types and neurons matching what is typed, for an input's datalist.
function useSuggestions(graph: string, text: string): {value: string; label: string}[] {
  const [matches, setMatches] = useState<{value: string; label: string}[]>([]);
  useEffect(() => {
    const term = text.split(',').pop()?.trim() ?? '';
    if (term.length < 2) {
      setMatches([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      getJson(`/api/explore/lookup?${new URLSearchParams({graph, q: term, limit: '12'})}`)
        .then((data) => {
          if (cancelled) return;
          setMatches(
            data.matches.map((m: any) =>
              m.kind === 'neuron'
                ? {value: m.id, label: `${m.cell_type} · ${m.side}`}
                : {
                    value: m.cell_type,
                    label: `${m.neurons} neurons · ${m.left} L / ${m.right} R · ${String(m.super_class).replaceAll('_', ' ')}`,
                  },
            ),
          );
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [graph, text]);
  return matches;
}

function NameInput({
  id,
  label,
  value,
  graph,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  graph: string;
  onChange: (value: string) => void;
}) {
  const suggestions = useSuggestions(graph, value);
  const prefix = value.includes(',') ? value.slice(0, value.lastIndexOf(',') + 1) + ' ' : '';
  return (
    <label className="field-label">
      {label}
      <input
        aria-label={label}
        list={`${id}-list`}
        value={value}
        placeholder="Cell type or FlyWire root ID; several with commas"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={`${id}-list`}>
        {suggestions.map((s) => (
          <option key={s.value} value={prefix + s.value} label={s.label} />
        ))}
      </datalist>
    </label>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div className="explore-choice">
      <span>{label}</span>
      <div className="segmented" role="group" aria-label={label}>
        {options.map(([v, text]) => (
          <button
            type="button"
            key={v}
            className={value === v ? 'selected' : ''}
            aria-pressed={value === v}
            onClick={() => onChange(v)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ExplorePanel({
  state,
  intervene,
  disabled,
  openBuild,
  openWorkbench,
  focus = null,
  focusDone,
}: {
  state: State | null;
  intervene: (change: InterventionChange) => Promise<unknown>;
  disabled: boolean;
  openBuild: () => void;
  openWorkbench: () => void;
  // A cell type to look up (from the command palette or the Overview): its partners are queried
  // once the graphs are listed, then focusDone clears it.
  focus?: string | null;
  focusDone?: () => void;
}) {
  const [graphs, setGraphs] = useState<GraphInfo[] | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [form, setFormState] = useState<ExploreForm>(remembered.form);
  const [kind, setKindState] = useState<Query>(remembered.kind);
  const [result, setResultState] = useState<Result | null>(remembered.result);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [link, setLink] = useState<Link | null>(null);
  const [linking, setLinking] = useState<string | null>(null);
  const set = (change: Partial<ExploreForm>) =>
    setFormState((f) => (remembered.form = {...f, ...change}));
  const setKind = (k: Query) => {
    remembered.kind = k;
    setKindState(k);
  };
  const setResult = (r: Result | null) => {
    remembered.result = r;
    setResultState(r);
  };
  const dynamics = state?.config.connectome_parameters.dynamics ?? 'rate';
  const problem = formProblem(kind, form);

  useEffect(() => {
    let cancelled = false;
    getJson('/api/explore/graphs')
      .then((data) => {
        if (cancelled) return;
        setGraphs(data.graphs);
        setRunning(data.running);
        const current = data.graphs.find((g: GraphInfo) => g.key === remembered.form.graph);
        if (!current?.available) {
          const fallback = data.graphs.find(
            (g: GraphInfo) => g.available && (g.key === 'brain' || g.key === data.running),
          );
          if (fallback) set({graph: fallback.key});
        }
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [state?.config.connectome_parameters.circuit, state?.config.neural_model]);

  const graph = graphs?.find((g) => g.key === form.graph);
  const run = async (k: Query = kind, f: ExploreForm = form) => {
    if (formProblem(k, f) || loading) return;
    setLoading(true);
    setError(null);
    setNotice(null);
    setLink(null);
    const started = performance.now();
    try {
      const data = await getJson(queryUrl(k, f));
      setResult({kind: k, data, seconds: (performance.now() - started) / 1000});
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The query failed.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!focus || !graphs) return;
    focusDone?.();
    const next = {...remembered.form, query: focus};
    setFormState((remembered.form = next));
    setKind('partners');
    void run('partners', next);
  }, [focus, !!graphs]);

  const act = async (cellType: string, side: Side, mode: 'silence' | 'activate') => {
    const entry = rowManipulation(cellType, side, mode, dynamics);
    const done = await intervene((current) => withCellType(current, entry));
    if (done)
      setNotice(
        `${manipulationLabel(entry, dynamics)} in the running circuit (${state?.config.connectome_parameters.circuit}).`,
      );
  };
  const build = (seeds: string[]) => {
    const previous = loadDraft(DRAFT_KEYS.build, readBuildDraft)?.request;
    saveDraft(DRAFT_KEYS.build, buildDraft(seeds, previous));
    openBuild();
  };
  const neuroglancer = async (
    label: string,
    body: {groups?: NeuroglancerGroup[]; circuit?: string},
  ) => {
    setLinking(label);
    setError(null);
    try {
      const data = await getJson('/api/explore/neuroglancer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({graph: form.graph, title: `DigitalFly · ${label}`, ...body}),
      });
      setLink({url: data.url, neurons: data.neurons, truncated: data.truncated, label});
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make the Neuroglancer link.');
    } finally {
      setLinking(null);
    }
  };

  const Actions = ({
    cellType,
    side,
    inCircuit,
    seed,
  }: {
    cellType: string;
    side: Side;
    inCircuit: InCircuit;
    seed: string;
  }) => {
    const blocker = disabled
      ? 'Not connected to the simulation.'
      : manipulationBlocker(state, cellType, side, inCircuit);
    const where = side === 'both' ? cellType : `${cellType} (${side})`;
    return (
      <div className="explore-actions">
        <button
          type="button"
          className="icon-button"
          disabled={!!blocker}
          title={blocker ?? `Silence ${where} in the Workbench`}
          aria-label={`Silence ${where} in the Workbench`}
          onClick={() => void act(cellType, side, 'silence')}
        >
          <VolumeX size={13} />
        </button>
        <button
          type="button"
          className="icon-button"
          disabled={!!blocker}
          title={blocker ?? `Activate ${where} in the Workbench`}
          aria-label={`Activate ${where} in the Workbench`}
          onClick={() => void act(cellType, side, 'activate')}
        >
          <Zap size={13} />
        </button>
        <button
          type="button"
          className="icon-button"
          title={`Build a circuit around ${seed}`}
          aria-label={`Build a circuit around ${seed}`}
          onClick={() => build([seed])}
        >
          <Hammer size={13} />
        </button>
      </div>
    );
  };

  const data = result?.data;
  const rows: (TypeRow | NeuronRow)[] = result && result.kind !== 'paths' ? data.rows : [];
  const byNeuron = result?.kind !== 'paths' && data?.group === 'neuron';
  const graphTitle = useMemo(
    () => graphs?.find((g) => g.key === data?.graph)?.title ?? data?.graph,
    [graphs, data],
  );

  return (
    <div className="explore-layout">
      <section className="panel explore-panel">
        <div className="panel-heading">
          <div>
            <Network size={16} />
            <h2>Connectivity explorer</h2>
          </div>
          <span className="mini-badge">FLYWIRE V783 · LOCAL</span>
        </div>
        <form
          className="explore-form"
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
        >
          <div className="explore-row">
            <label className="field-label">
              Graph
              <select
                aria-label="Graph"
                value={form.graph}
                onChange={(e) => set({graph: e.target.value})}
              >
                {(graphs ?? [{key: form.graph, title: form.graph, available: true}]).map((g) => (
                  <option key={g.key} value={g.key} disabled={!g.available}>
                    {g.key === 'brain' ? g.title : g.key}
                    {g.key === running ? ' (running)' : ''}
                    {g.neurons ? ` · ${g.neurons.toLocaleString()} neurons` : ''}
                    {!g.available ? ' · not prepared' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-label">
              Synapse threshold
              <input
                aria-label="Synapse threshold"
                type="number"
                min={1}
                max={1000}
                value={form.threshold}
                onChange={(e) => set({threshold: Number(e.target.value)})}
              />
            </label>
            <label className="field-label">
              Rows
              <input
                aria-label="Rows"
                type="number"
                min={1}
                max={500}
                value={form.limit}
                onChange={(e) => set({limit: Number(e.target.value)})}
              />
            </label>
          </div>
          {graphs && graph && !graph.available && graph.reason && (
            <p className="microcopy" role="status">
              {graph.reason}
            </p>
          )}
          <div className="segmented explore-kinds" role="tablist" aria-label="Query">
            {QUERIES.map((q) => (
              <button
                type="button"
                role="tab"
                key={q}
                aria-selected={kind === q}
                className={kind === q ? 'selected' : ''}
                onClick={() => setKind(q)}
              >
                {queryNames[q]}
              </button>
            ))}
          </div>
          {kind === 'paths' ? (
            <>
              <div className="explore-row">
                <NameInput
                  id="explore-source"
                  label="From"
                  value={form.source}
                  graph={form.graph}
                  onChange={(source) => set({source})}
                />
                <NameInput
                  id="explore-target"
                  label="To"
                  value={form.target}
                  graph={form.graph}
                  onChange={(target) => set({target})}
                />
              </div>
              <div className="explore-row">
                <Choice
                  label="Rank by"
                  value={form.mode}
                  options={[
                    ['strongest', 'Strongest'],
                    ['shortest', 'Fewest steps'],
                  ]}
                  onChange={(mode) => set({mode})}
                />
                <Choice
                  label="Between"
                  value={form.level}
                  options={[
                    ['cell_type', 'Cell types'],
                    ['neuron', 'Neurons'],
                  ]}
                  onChange={(level) => set({level})}
                />
                <label className="field-label">
                  At most steps
                  <input
                    aria-label="At most steps"
                    type="number"
                    min={1}
                    max={20}
                    value={form.maxHops}
                    onChange={(e) => set({maxHops: Number(e.target.value)})}
                  />
                </label>
              </div>
            </>
          ) : (
            <>
              <NameInput
                id="explore-query"
                label="Cell types or neurons"
                value={form.query}
                graph={form.graph}
                onChange={(query) => set({query})}
              />
              <div className="explore-row">
                {kind === 'partners' ? (
                  <Choice
                    label="Partners"
                    value={form.direction}
                    options={[
                      ['upstream', 'Upstream (inputs)'],
                      ['downstream', 'Downstream (outputs)'],
                    ]}
                    onChange={(direction) => set({direction})}
                  />
                ) : (
                  <Choice
                    label="Influence"
                    value={form.influenceDirection}
                    options={[
                      ['onto', 'Onto the query'],
                      ['from', 'From the query'],
                    ]}
                    onChange={(influenceDirection) => set({influenceDirection})}
                  />
                )}
                <Choice
                  label="Rows by"
                  value={form.group}
                  options={[
                    ['cell_type', 'Cell type'],
                    ['neuron', 'Neuron'],
                  ]}
                  onChange={(group) => set({group})}
                />
                <Choice
                  label="Query side"
                  value={form.side}
                  options={[
                    ['both', 'Both'],
                    ['left', 'Left'],
                    ['right', 'Right'],
                  ]}
                  onChange={(side) => set({side})}
                />
              </div>
              {kind === 'influence' && (
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={form.signed}
                    onChange={(e) => set({signed: e.target.checked})}
                  />
                  <span>
                    Signed by predicted transmitter
                    <small>
                      Acetylcholine excites; GABA and glutamate inhibit; other transmitters are left
                      out. Unticked, every connection counts as excitatory.
                    </small>
                  </span>
                </label>
              )}
            </>
          )}
          {problem && (
            <p className="microcopy" role="status">
              {problem}
            </p>
          )}
          <div className="explore-buttons">
            <button className="primary-button" disabled={!!problem || loading || !graph?.available}>
              {loading ? <LoaderCircle size={15} className="spin" /> : <Search size={15} />}
              {loading ? 'Searching…' : `Find ${queryNames[kind].toLowerCase()}`}
            </button>
            {running && (
              <button
                type="button"
                className="text-button"
                disabled={!!linking}
                onClick={() => void neuroglancer(`circuit ${running}`, {circuit: running})}
              >
                <ExternalLink size={12} /> Running circuit in Neuroglancer
              </button>
            )}
          </div>
        </form>
        <p className="panel-copy">
          {kind === 'partners'
            ? 'Who connects to the query, and how much of its input or output each partner carries.'
            : kind === 'paths'
              ? 'Strongest: the path whose steps carry the largest product of input fractions. Fewest steps: the shortest path, ties broken by strength. Further rows are the best path through each other connection.'
              : 'A linear steady state after the BANC influence calculator: signed synapse counts, rescaled so the largest real eigenvalue is 0.99, with constant input to the stimulated neurons. An approximation of polysynaptic reach, not a simulation.'}{' '}
          Signs are assumed from predicted transmitters. FlyWire v783 data, CC BY-NC 4.0: credit the
          FlyWire Consortium.
        </p>
      </section>

      <section className="panel explore-results" aria-live="polite">
        <div className="panel-heading">
          <div>
            <h2>{result ? queryNames[result.kind] : 'Results'}</h2>
          </div>
          <span className="subtle-label">
            {result
              ? `${graphTitle} · ≥${data.threshold} synapses · ${result.seconds.toFixed(2)} s`
              : 'Run a query'}
          </span>
        </div>
        {error && (
          <p className="form-error explore-message" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="explore-message explore-notice" role="status">
            {notice}{' '}
            <button type="button" className="text-button" onClick={openWorkbench}>
              Open the Workbench <MoveUpRight size={12} />
            </button>
          </p>
        )}
        {link && (
          <p className="explore-message" role="status">
            Neuroglancer link for {link.label}: {link.neurons.toLocaleString()} neurons
            {link.truncated ? ' (the first ones only)' : ''}.{' '}
            <a href={link.url} target="_blank" rel="noopener noreferrer" className="text-button">
              Open <ExternalLink size={12} />
            </a>{' '}
            <button
              type="button"
              className="text-button"
              onClick={() => void navigator.clipboard?.writeText(link.url)}
            >
              Copy <Copy size={12} />
            </button>
          </p>
        )}
        {!result && !error && (
          <p className="panel-copy">
            Pick a graph and a query. The whole brain loads once (a few seconds); later queries take
            under two seconds. Each row can silence or activate its cell type in the running
            circuit, or start a circuit build around it.
          </p>
        )}
        {result && result.kind !== 'paths' && (
          <>
            <p className="panel-copy explore-summary">
              {result.kind === 'partners'
                ? `${data.direction === 'upstream' ? 'Inputs to' : 'Outputs of'} ${data.query.join(', ')} (${data.query_neurons.count} neurons${data.side !== 'both' ? `, ${data.side} side` : ''}): ${data.total_synapses.toLocaleString()} synapses from ${data.groups.toLocaleString()} ${data.group === 'neuron' ? 'neurons' : 'cell types'}.`
                : `${data.direction === 'from' ? 'What stimulating' : 'What reaches'} ${data.query.join(', ')} (${data.query_neurons} neurons): ${data.neurons_reached.toLocaleString()} neurons with nonzero influence. λ = ${compact(data.model.lambda)}, ${data.model.solver}, residual ${data.model.relative_residual.toExponential(1)}.`}{' '}
              <button
                type="button"
                className="text-button"
                disabled={!!linking || !rows.length}
                onClick={() =>
                  void neuroglancer(`${data.query.join(', ')} and ${result.kind}`, {
                    groups: [
                      {
                        label: data.query.join(', '),
                        cell_type: data.query.join(', '),
                        side: data.side,
                      },
                      ...rowGroups(rows),
                    ],
                  })
                }
              >
                <ExternalLink size={12} /> Query and rows in Neuroglancer
              </button>
            </p>
            <div className="explore-table-wrap">
              <table className="circuit-table explore-table">
                <thead>
                  <tr>
                    <th>{byNeuron ? 'Neuron' : 'Cell type'}</th>
                    {result.kind === 'partners' ? (
                      <>
                        <th>Synapses</th>
                        <th>Share</th>
                      </>
                    ) : (
                      <>
                        <th>Influence</th>
                        <th>{byNeuron ? 'log₁₀' : 'Left / right'}</th>
                      </>
                    )}
                    <th>Sign</th>
                    <th>In running circuit</th>
                    <th>
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row: any) => {
                    const side = rowSide(row);
                    const seed = byNeuron ? row.id : row.cell_type;
                    const inCircuit: InCircuit = row.in_running_circuit;
                    return (
                      <tr key={byNeuron ? row.id : row.cell_type}>
                        <td>
                          {byNeuron ? row.cell_type : row.cell_type}
                          <small>
                            {byNeuron
                              ? `${row.id} · ${row.side} · ${row.transmitter}`
                              : result.kind === 'partners'
                                ? `${row.partners} of ${row.type_neurons} neurons (${row.left} L / ${row.right} R) · ${row.transmitter}`
                                : `${row.reached} of ${row.neurons} neurons reached · ${String(row.super_class).replaceAll('_', ' ')}`}
                          </small>
                        </td>
                        {result.kind === 'partners' ? (
                          <>
                            <td>{row.synapses.toLocaleString()}</td>
                            <td>{percent(row.fraction)}</td>
                          </>
                        ) : (
                          <>
                            <td>{compact(row.influence)}</td>
                            <td>
                              {byNeuron
                                ? row.log10.toFixed(2)
                                : `${compact(row.left)} / ${compact(row.right)}`}
                            </td>
                          </>
                        )}
                        <td>{signText(row.sign)}</td>
                        <td>
                          {inCircuit
                            ? `${inCircuit.neurons} (${inCircuit.left} L / ${inCircuit.right} R)`
                            : '—'}
                        </td>
                        <td>
                          <Actions
                            cellType={row.cell_type}
                            side={side}
                            inCircuit={inCircuit}
                            seed={seed}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
        {result && result.kind === 'paths' && (
          <>
            <p className="panel-copy explore-summary">
              {data.paths.length
                ? `${data.mode === 'strongest' ? 'Strongest' : 'Shortest'} paths from ${data.source.join(', ')} to ${data.target.join(', ')}, between ${data.level === 'neuron' ? 'neurons' : 'cell types'}.`
                : `No path from ${data.source.join(', ')} to ${data.target.join(', ')} within ${data.max_hops} steps.`}
            </p>
            <ol className="explore-paths">
              {data.paths.map((path: any, k: number) => (
                <li key={k}>
                  <div className="explore-path-steps">
                    {path.cell_types.map((t: string, i: number) => {
                      const neuron = path.neurons?.[i];
                      const side: Side = neuron ? rowSide(neuron) : 'both';
                      return (
                        <span key={i} className="explore-step">
                          {i > 0 && (
                            <span
                              className="explore-arrow"
                              title={`${path.edges[i - 1].synapses} synapses, ${percent(path.edges[i - 1].fraction)} of the input`}
                            >
                              {signText(path.edges[i - 1].sign)}
                              {path.edges[i - 1].synapses}→
                            </span>
                          )}
                          <span className="explore-node">
                            {t}
                            {neuron && <small>{neuron.side}</small>}
                            <Actions
                              cellType={t}
                              side={side}
                              inCircuit={path.in_running_circuit[i]}
                              seed={neuron ? neuron.id : t}
                            />
                          </span>
                        </span>
                      );
                    })}
                  </div>
                  <div className="explore-path-meta">
                    {path.steps} {path.steps === 1 ? 'step' : 'steps'} · strength{' '}
                    {compact(path.strength)} · net sign {signText(path.net_sign)}{' '}
                    <button
                      type="button"
                      className="text-button"
                      onClick={() =>
                        build(path.neurons ? path.neurons.map((n: any) => n.id) : path.cell_types)
                      }
                    >
                      <Hammer size={12} /> Build around this path
                    </button>{' '}
                    <button
                      type="button"
                      className="text-button"
                      disabled={!!linking}
                      onClick={() => void neuroglancer(`path ${k + 1}`, {groups: pathGroups(path)})}
                    >
                      <ExternalLink size={12} /> Neuroglancer
                    </button>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
        {result && <p className="microcopy explore-rule">{data.rule}</p>}
      </section>
    </div>
  );
}
