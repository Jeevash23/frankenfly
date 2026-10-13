import {useEffect, useMemo, useState} from 'react';
import {Hammer, LoaderCircle, Plus, X} from 'lucide-react';
import type {BuildStatus, Command, Config, State} from '../types';
import {configForCircuit} from '../models';
import {buildProblem, defaultBuild, suggestTypes, type BuildRequest} from './build';
import {useCircuitList} from './useCircuit';
import './connectome.css';

type Catalog = {
  release: string;
  cell_types: {
    cell_type: string;
    neurons: number;
    left: number;
    right: number;
    super_class: string;
  }[];
};

const PREPARE = 'backend/.venv/bin/python scripts/build_circuit.py prepare';

function useCatalog(): {catalog: Catalog | null; missing: boolean} {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/connectome/catalog')
      .then((r) => {
        if (r.status === 404) {
          if (!cancelled) setMissing(true);
          return null;
        }
        return r.ok ? r.json() : null;
      })
      .then((data) => {
        if (data && !cancelled) setCatalog(data);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return {catalog, missing};
}

export function BuildPanel({
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
  const {catalog, missing} = useCatalog();
  const {circuits, refresh} = useCircuitList();
  const [request, setRequest] = useState<BuildRequest>(defaultBuild);
  const [seedDraft, setSeedDraft] = useState('');
  const [status, setStatus] = useState<BuildStatus>({status: 'idle', log: []});
  const names = useMemo(() => catalog?.cell_types.map((c) => c.cell_type) ?? [], [catalog]);
  const known = useMemo(() => (catalog ? new Set(names) : null), [catalog, names]);
  const counts = useMemo(
    () => new Map(catalog?.cell_types.map((c) => [c.cell_type, c]) ?? []),
    [catalog],
  );
  const builtIn = circuits.filter((c) => c.committed).map((c) => c.name);
  const problem = buildProblem(request, builtIn, known);
  const suggestions = suggestTypes(names, seedDraft, 8).filter((s) => !request.seeds.includes(s));
  const running = status.status === 'running';

  // Follow a running build, including one started before this page was opened.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = () =>
      fetch('/api/connectome/build')
        .then((r) => r.json())
        .then((next: BuildStatus) => {
          if (cancelled) return;
          setStatus((previous) => {
            if (previous.status === 'running' && next.status !== 'running') refresh();
            return next;
          });
          if (next.status === 'running') timer = setTimeout(poll, 1000);
        })
        .catch(() => undefined);
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [running, refresh]);

  const addSeed = (value: string) => {
    const seed = value.trim();
    if (!seed || request.seeds.includes(seed)) return;
    setRequest({...request, seeds: [...request.seeds, seed]});
    setSeedDraft('');
  };
  const start = async () => {
    const result = await command('connectome/build', request);
    if (result) setStatus(result);
  };
  const use = (name: string) => {
    if (!state) return;
    const next = configForCircuit(state.config, name, state.config.connectome_parameters.dynamics);
    reset({neural_model: 'connectome', connectome_parameters: next.connectome_parameters});
  };

  return (
    <div className="build-layout">
      <section className="panel build-panel">
        <div className="panel-heading">
          <div>
            <Hammer size={16} />
            <h2>Build a circuit</h2>
          </div>
          <span className="mini-badge">FLYWIRE V783 · LOCAL</span>
        </div>
        {missing ? (
          <div className="build-missing" role="status">
            <p>
              The builder needs the FlyWire data prepared once on this computer. Run this in the
              project folder, then reopen this page:
            </p>
            <code className="equation">{PREPARE}</code>
            <p className="microcopy">
              It uses the cached downloads in .cache/circuits/ (about 61 MB, fetched once with the
              build-only data lock; see docs/RESEARCH.md). Nothing is downloaded by this page.
            </p>
          </div>
        ) : (
          <form
            className="build-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!problem && !running) void start();
            }}
          >
            <label className="field-label">
              Circuit name
              <input
                aria-label="Circuit name"
                value={request.name}
                placeholder="e.g. lc10-to-dna02"
                disabled={disabled || running}
                onChange={(e) => setRequest({...request, name: e.target.value})}
              />
            </label>
            <label className="field-label">
              Seeds: cell types or FlyWire root IDs
              <div className="seed-entry">
                <input
                  aria-label="Add a seed"
                  value={seedDraft}
                  placeholder={catalog ? 'Type a cell type, e.g. DNa01' : 'Loading the catalog…'}
                  disabled={disabled || running}
                  onChange={(e) => setSeedDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addSeed(
                        suggestions.includes(seedDraft.trim()) || !suggestions.length
                          ? seedDraft
                          : suggestions[0],
                      );
                    }
                  }}
                />
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Add seed"
                  disabled={disabled || running || !seedDraft.trim()}
                  onClick={() => addSeed(seedDraft)}
                >
                  <Plus size={14} />
                </button>
              </div>
            </label>
            {suggestions.length > 0 && (
              <div className="seed-suggestions" role="listbox" aria-label="Matching cell types">
                {suggestions.map((name) => {
                  const info = counts.get(name);
                  return (
                    <button
                      type="button"
                      key={name}
                      role="option"
                      aria-selected="false"
                      onClick={() => addSeed(name)}
                    >
                      {name}
                      {info ? (
                        <small>
                          {info.neurons} neurons · {info.left} L / {info.right} R ·{' '}
                          {info.super_class.replaceAll('_', ' ')}
                        </small>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}
            {request.seeds.length > 0 && (
              <div className="silenced-types" aria-label="Seeds">
                {request.seeds.map((seed) => (
                  <button
                    type="button"
                    key={seed}
                    disabled={running}
                    aria-label={`Remove ${seed}`}
                    onClick={() =>
                      setRequest({...request, seeds: request.seeds.filter((s) => s !== seed)})
                    }
                  >
                    {seed} <X size={10} />
                  </button>
                ))}
              </div>
            )}
            <div className="parameter-fields">
              {(
                [
                  ['hops', 'Hops back from the seeds', 1, 6],
                  ['threshold', 'Synapse threshold', 1, 1000],
                  ['cap', 'Neuron cap', 10, 200000],
                ] as const
              ).map(([field, label, min, max]) => (
                <label key={field}>
                  {label}
                  <input
                    aria-label={label}
                    type="number"
                    min={min}
                    max={max}
                    step={1}
                    value={request[field]}
                    disabled={disabled || running || (request.whole_brain && field !== 'threshold')}
                    onChange={(e) => setRequest({...request, [field]: Number(e.target.value)})}
                  />
                </label>
              ))}
            </div>
            <label className="check-label">
              <input
                type="checkbox"
                checked={request.whole_brain}
                disabled={disabled || running}
                onChange={(e) => setRequest({...request, whole_brain: e.target.checked})}
              />
              Whole brain: every neuron with a connection at the threshold (the seeds only set hop
              distances; about 134,000 neurons at 5 synapses, slow to simulate)
            </label>
            {problem && request.name && (
              <p className="microcopy" role="status">
                {problem}
              </p>
            )}
            <button className="primary-button" disabled={disabled || running || !!problem}>
              {running ? <LoaderCircle size={15} className="spin" /> : <Hammer size={15} />}
              {running ? 'Building…' : 'Build circuit'}
            </button>
            <p className="microcopy">
              Seed cell types with neurons on both sides become the default steering readout. The
              build runs on this computer from the prepared FlyWire data and needs no network.
            </p>
          </form>
        )}
        {status.status !== 'idle' && (
          <div className="build-status" aria-live="polite">
            <span className="eyebrow">
              {status.status === 'running'
                ? `BUILDING ${status.name?.toUpperCase()}`
                : status.status === 'done'
                  ? `BUILT ${status.result?.name?.toUpperCase() ?? status.name?.toUpperCase()}`
                  : `BUILD FAILED (exit ${status.exit_code})`}
            </span>
            {status.status === 'done' && status.result && (
              <p>
                {status.result.neurons.toLocaleString()} neurons,{' '}
                {status.result.connections.toLocaleString()} connections,{' '}
                {status.result.cell_types.toLocaleString()} cell types.{' '}
                <button
                  className="text-button"
                  disabled={disabled}
                  onClick={() => use(status.result!.name)}
                >
                  Use this circuit
                </button>
              </p>
            )}
            <pre className="build-log">{status.log.slice(-12).join('\n')}</pre>
          </div>
        )}
      </section>
      <section className="panel build-list">
        <div className="panel-heading">
          <div>
            <h2>Available circuits</h2>
          </div>
          <span className="subtle-label">Committed and built on this computer</span>
        </div>
        <table className="circuit-table">
          <thead>
            <tr>
              <th>Circuit</th>
              <th>Neurons</th>
              <th>Seeds · readout</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {circuits.map((c) => (
              <tr key={c.name}>
                <td>
                  {c.name}
                  <small>
                    {c.error ? `Unreadable: ${c.error}` : c.committed ? 'committed' : 'local'}
                  </small>
                </td>
                <td>
                  {c.neurons?.toLocaleString() ?? '—'}
                  <small>
                    {c.connections ? `${c.connections.toLocaleString()} connections` : ''}
                  </small>
                </td>
                <td>
                  {c.seeds?.join(', ') ?? '—'}
                  <small>
                    {c.readout_types?.length
                      ? `readout ${c.readout_types.join(', ')}`
                      : 'no default readout'}
                  </small>
                </td>
                <td>
                  <button
                    className="text-button"
                    disabled={
                      disabled ||
                      !!c.error ||
                      (state?.config.connectome_parameters.circuit === c.name &&
                        state?.config.neural_model === 'connectome')
                    }
                    onClick={() => use(c.name)}
                  >
                    {state?.config.connectome_parameters.circuit === c.name &&
                    state?.config.neural_model === 'connectome'
                      ? 'In use'
                      : 'Use'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="panel-copy">
          Every circuit is FlyWire FAFB v783 data under CC BY-NC 4.0: non-commercial use only,
          credit the FlyWire Consortium. Local circuits live in data/circuits/local/ and are not
          committed. Using a circuit starts a fresh run.
        </p>
      </section>
    </div>
  );
}
