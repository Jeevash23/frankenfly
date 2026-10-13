import {useEffect, useState} from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  ChevronDown,
  FlaskConical,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react';
import type {Command, Condition, Config, Protocol, SavedRun, State} from './types';
import {fmt} from './format';
import {
  conditionNames,
  conditionProblem,
  conditionsFor,
  firstExperiment,
  modelPhrases,
  normalizeModel,
  noInterventions,
} from './models';
import {useCircuit} from './connectome/useCircuit';
import {
  edited,
  freeStep,
  preset,
  presets,
  scheduleProblem,
  sortedEvents,
  withDuration,
} from './protocol';

const lineColors = ['#527751', '#ba9152', '#8584b2', '#a26e67'];
// Each overlaid run also gets its own line style, so runs never differ by color alone.
const lineDashes = [undefined, '7 4', '2 3', '9 3 2 3'];
const conditionName = (condition: string) =>
  conditionNames[condition as Condition] ?? condition.replaceAll('_', ' ');

export default function Experiments({
  state,
  command,
  disabled,
  onLoaded,
}: {
  state: State | null;
  command: Command;
  disabled: boolean;
  onLoaded: () => void;
}) {
  const [protocol, setProtocol] = useState<Protocol>(
    state?.config.protocol ?? preset('Target reversal', 2),
  );
  const [seeds, setSeeds] = useState('42, 43');
  const [conditions, setConditions] = useState<Condition[]>(['control', 'left_sensor_off']);
  const [cellType, setCellType] = useState('');
  const model = state?.config.neural_model ?? 'engineered';
  const {circuit} = useCircuit(state);
  // DNa02 conditions need a circuit with DNa02; assume one until the circuit has loaded.
  const hasDNa02 = !circuit || circuit.types.some((t) => t.name === 'DNa02');
  const available = conditionsFor(model, hasDNa02);
  // Switching models or circuits drops conditions that are no longer available.
  useEffect(() => {
    setConditions((previous) => {
      const kept = previous.filter((c) => conditionsFor(model, hasDNa02).includes(c));
      return kept.length ? kept : ['control'];
    });
  }, [model, hasDNa02]);
  const [runs, setRuns] = useState<SavedRun[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [details, setDetails] = useState<SavedRun[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [includeEmpty, setIncludeEmpty] = useState(false);
  const active = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const refresh = () =>
    fetch('/api/runs')
      .then((r) => {
        if (!r.ok)
          throw Error(
            'The run library could not be read. Check that the local server is still running, then press Refresh.',
          );
        return r.json();
      })
      .then((d) => setRuns(d.runs))
      .catch((e) => setError(e.message));
  useEffect(() => {
    void refresh();
  }, [state?.batch?.results.length]);
  useEffect(() => {
    let cancelled = false;
    Promise.all(
      selected.map((key) =>
        fetch(`/api/runs/${key}`).then((r) => {
          if (!r.ok)
            throw Error(
              'A selected run could not be read. Its files may have been moved or deleted.',
            );
          return r.json();
        }),
      ),
    )
      .then((d) => {
        if (!cancelled) setDetails(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);
  const problem = scheduleProblem(protocol);
  const config = (): Config => ({
    ...state!.config,
    stimulus: {x: 12, y: 8, intensity: 1},
    protocol: sortedEvents(protocol),
    initial_interventions: noInterventions,
  });
  const load = async () => {
    if (!state) return;
    setError('');
    setNotice('');
    const result = await command('reset', config());
    if (result) {
      setNotice('Protocol loaded, starting paused.');
      onLoaded();
    }
  };
  const batch = async () => {
    if (!state) return;
    setError('');
    setNotice('');
    const list = seeds.split(',').map((x) => Number(x.trim()));
    if (
      seeds.split(',').some((x) => !x.trim()) ||
      list.length > 5 ||
      list.some((x) => !Number.isInteger(x) || x < 0 || x > 2147483647)
    ) {
      setError('Enter one to five whole-number seeds, separated by commas.');
      return;
    }
    if (new Set(list).size !== list.length) {
      setError('Use each seed only once.');
      return;
    }
    const conditionError = conditionProblem(conditions, model, cellType, hasDNa02);
    if (conditionError) {
      setError(conditionError);
      return;
    }
    const result = await command('batch/start', {
      config: config(),
      seeds: list,
      conditions,
      cell_type: conditions.includes('cell_type_off') ? cellType.trim() : null,
    });
    if (result) setNotice('Comparison started. Each complete trial is saved automatically.');
  };
  const loadFirstExperiment = () => {
    const preset = firstExperiment(model, hasDNa02);
    setProtocol(preset.protocol);
    setSeeds(preset.seeds);
    setConditions(preset.conditions);
    setError('');
    setNotice(
      `First experiment ready: ${preset.protocol.name.toLowerCase()} over ${preset.protocol.duration_steps / 100} simulated seconds, seeds ${preset.seeds}, comparing “${conditionNames[preset.conditions[0]]}” with “${conditionNames[preset.conditions[1]]}”. Press Run comparison to start. The research guide's walkthrough also switches to compound-eye input on the Workbench.`,
    );
  };
  const duration = protocol.duration_steps / 100;
  const paths = details.flatMap((d) => d.trajectory ?? []);
  const extent = Math.max(10, ...paths.flatMap((p) => [Math.abs(p[1]), Math.abs(p[2])])) * 1.12;
  return (
    <>
      <div className="research-intro">
        <div>
          <span className="eyebrow">EXPERIMENT DESIGN</span>
          <h2>Ask a repeatable question.</h2>
          <p>Control the stimulus, vary one condition, and keep a record of every trial.</p>
        </div>
        <div className="intro-actions">
          <button
            className="secondary-button"
            disabled={disabled || active}
            onClick={loadFirstExperiment}
          >
            <Sparkles size={14} />
            Set up the first experiment
          </button>
          <span className="mini-badge">ONE ANIMAL AT A TIME / LOCAL</span>
        </div>
      </div>
      {(error || notice) && (
        <div
          className={`alert ${error ? 'error-alert' : 'export-alert'}`}
          role={error ? 'alert' : 'status'}
        >
          {error || notice}
        </div>
      )}
      <div className="protocol-layout">
        <section className="panel protocol-panel">
          <div className="panel-heading">
            <div>
              <FlaskConical size={16} />
              <h2>Stimulus protocol</h2>
            </div>
            <span className="subtle-label">Exact simulation steps</span>
          </div>
          <div className="protocol-fields">
            <label>
              Starting protocol
              <div className="select-wrap">
                <select
                  aria-label="Protocol preset"
                  disabled={disabled || active}
                  value={presets.includes(protocol.name) ? protocol.name : 'custom'}
                  onChange={(e) => setProtocol(preset(e.target.value, duration))}
                >
                  {presets.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                  <option value="custom" disabled>
                    Custom sequence
                  </option>
                </select>
                <ChevronDown size={13} />
              </div>
            </label>
            <label>
              Duration (simulated seconds)
              <input
                aria-label="Protocol duration"
                type="number"
                min=".1"
                max="15"
                step=".1"
                disabled={disabled || active}
                value={duration}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  if (value >= 0.1 && value <= 15) setProtocol((p) => withDuration(p, value));
                }}
              />
            </label>
          </div>
          <p className="panel-copy">
            Starts with a target at (12, 8) mm, intensity 1. Each row changes the target at the
            specified time. The simulation pauses at the end.
          </p>
          <div className="protocol-timeline">
            <div className="timeline-rule" />
            <span className="timeline-start">0 s</span>
            {protocol.events.map((event, i) => (
              <div
                key={i}
                className="timeline-marker"
                style={{left: `${5 + (event.step / protocol.duration_steps) * 90}%`}}
              >
                <i />
                <span>{fmt(event.step / 100, 2)} s</span>
              </div>
            ))}
            <span className="timeline-end">{fmt(duration, 1)} s · stop</span>
          </div>
          <div className="protocol-table-wrap">
            <table className="protocol-table">
              <thead>
                <tr>
                  <th>At (s)</th>
                  <th>X (mm)</th>
                  <th>Y (mm)</th>
                  <th>Intensity</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {protocol.events.map((event, i) => (
                  <tr key={i}>
                    <td>
                      <input
                        aria-label={`Event ${i + 1} time`}
                        type="number"
                        min="0"
                        max={Math.max(0, duration - 0.01)}
                        step=".01"
                        disabled={disabled || active}
                        value={event.step / 100}
                        onChange={(e) =>
                          setProtocol((p) =>
                            edited(
                              p,
                              p.events.map((ev, j) =>
                                j === i
                                  ? {...ev, step: Math.round(Number(e.target.value) * 100)}
                                  : ev,
                              ),
                            ),
                          )
                        }
                      />
                    </td>
                    {(['x', 'y', 'intensity'] as const).map((key) => (
                      <td key={key}>
                        <input
                          aria-label={`Event ${i + 1} ${key}`}
                          type="number"
                          min={key === 'intensity' ? 0 : -40}
                          max={key === 'intensity' ? 2 : 40}
                          step={key === 'intensity' ? '.1' : '1'}
                          disabled={disabled || active}
                          value={event.stimulus?.[key] ?? 0}
                          onChange={(e) =>
                            setProtocol((p) =>
                              edited(
                                p,
                                p.events.map((ev, j) =>
                                  j === i
                                    ? {
                                        ...ev,
                                        stimulus: {
                                          x: 12,
                                          y: 8,
                                          intensity: 1,
                                          ...ev.stimulus,
                                          [key]: Number(e.target.value),
                                        },
                                      }
                                    : ev,
                                ),
                              ),
                            )
                          }
                        />
                      </td>
                    ))}
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`Remove event ${i + 1}`}
                        disabled={disabled || active}
                        onClick={() =>
                          setProtocol((p) =>
                            edited(
                              p,
                              p.events.filter((_, j) => i !== j),
                            ),
                          )
                        }
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="protocol-actions">
            <button
              className="text-button"
              disabled={disabled || active || protocol.events.length >= 8}
              onClick={() =>
                setProtocol((p) =>
                  edited(p, [
                    ...p.events,
                    {step: freeStep(p), stimulus: {x: 12, y: -8, intensity: 1}},
                  ]),
                )
              }
            >
              <Plus size={14} />
              Add stimulus change
            </button>
            <button
              className="secondary-button"
              disabled={disabled || active || !!problem}
              onClick={() => void load()}
            >
              Load into workbench <ArrowRight size={14} />
            </button>
          </div>
          {problem && (
            <p className="schedule-problem" role="status">
              {problem}
            </p>
          )}
          <div className="panel-footnote">
            1 step = 10 ms · changes run in time order · loading begins a fresh run
          </div>
        </section>
        <section className="panel comparison-builder">
          <div className="panel-heading">
            <div>
              <h2>Compare conditions</h2>
            </div>
          </div>
          <div className="comparison-body">
            <label className="field-label">
              Random seeds
              <input
                aria-label="Comparison seeds"
                value={seeds}
                disabled={disabled || active}
                onChange={(e) => setSeeds(e.target.value)}
                placeholder="42, 43"
              />
            </label>
            <p className="microcopy">The same seeds are used for each condition.</p>
            <div className="condition-list">
              {available.map((key) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={conditions.includes(key)}
                    disabled={
                      disabled || active || (!conditions.includes(key) && conditions.length >= 4)
                    }
                    onChange={(e) =>
                      setConditions((prev) =>
                        e.target.checked ? [...prev, key] : prev.filter((k) => k !== key),
                      )
                    }
                  />
                  <span>{conditionNames[key]}</span>
                </label>
              ))}
            </div>
            {conditions.includes('cell_type_off') && (
              <label className="field-label">
                Cell type to silence
                <input
                  className="type-input"
                  list="comparison-cell-types"
                  aria-label="Cell type to silence in the comparison"
                  value={cellType}
                  disabled={disabled || active}
                  placeholder={circuit ? 'e.g. DNa03' : 'Loading cell types…'}
                  onChange={(e) => setCellType(e.target.value)}
                />
                <datalist id="comparison-cell-types">
                  {circuit?.types.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.count} neurons
                    </option>
                  ))}
                </datalist>
              </label>
            )}
            <p className="microcopy">
              Each condition holds its intervention for the whole trial. Runs happen sequentially
              using the selected body, sensor and the {modelPhrases[model]} (unless a condition
              switches the model). Up to four conditions.
            </p>
            <button
              className="primary-button"
              disabled={disabled || active || !!problem}
              title={problem ?? undefined}
              onClick={() => void batch()}
            >
              <Play size={14} />
              Run comparison
            </button>
            <small className="comparison-bound">
              Up to 5 seeds × 4 conditions · 300 simulated seconds total
            </small>
          </div>
        </section>
      </div>
      {state?.batch && (
        <section className={`batch-progress panel ${state.batch.status}`} role="status">
          <div>
            <span className="eyebrow">{state.batch.status.toUpperCase()}</span>
            <h3>{state.batch.protocol}</h3>
            <p>
              Trial {state.batch.current} of {state.batch.total} ·{' '}
              {conditionName(state.batch.condition)}
              {state.batch.condition === 'cell_type_off' && state.batch.cell_type
                ? ` (${state.batch.cell_type})`
                : ''}{' '}
              · seed {state.batch.seed}
            </p>
          </div>
          <div className="batch-meter">
            <span>{state.batch.results.length} trials saved</span>
            <progress max={state.batch.total} value={state.batch.results.length} />
            <small>
              {state.batch.error ??
                (active
                  ? `${fmt(state.sample?.t)} / ${fmt((state.config.protocol?.duration_steps ?? 0) / 100)} simulated seconds in this trial`
                  : 'All completed trials are in the local library below.')}
            </small>
          </div>
          {active && (
            <div className="batch-buttons">
              <button
                className="secondary-button"
                disabled={disabled}
                onClick={() => void command(state.batch?.status === 'paused' ? 'run' : 'pause')}
              >
                {state.batch.status === 'paused' ? <Play size={14} /> : <Pause size={14} />}{' '}
                {state.batch.status === 'paused' ? 'Resume' : 'Pause'}
              </button>
              <button
                className="secondary-button"
                disabled={disabled}
                onClick={() => void command('batch/cancel')}
              >
                <Square size={12} />
                Cancel remaining
              </button>
            </div>
          )}
        </section>
      )}
      <section className="run-library">
        <div className="session-heading">
          <div>
            <span className="eyebrow">LOCAL EXPERIMENT RECORDS</span>
            <h2>Run library</h2>
          </div>
          <button className="secondary-button" onClick={() => void refresh()}>
            <RotateCcw size={13} />
            Refresh
          </button>
        </div>
        <div className="library-filter">
          <p className="library-hint">
            Select up to four saved runs to overlay their paths and compare measured outcomes.
          </p>
          <label>
            <input
              type="checkbox"
              checked={includeEmpty}
              onChange={(e) => setIncludeEmpty(e.target.checked)}
            />
            Include zero-step runs
          </label>
        </div>
        {!runs.length ? (
          <section className="panel empty-research">
            <ArrowDownToLine size={26} />
            <h3>Your first record starts here.</h3>
            <p>
              Export a workbench run or complete a comparison. Everything is saved on this computer.
            </p>
          </section>
        ) : (
          <div className="panel library-table-wrap">
            <table className="library-table">
              <thead>
                <tr>
                  <th>Compare</th>
                  <th>Experiment</th>
                  <th>Body / sensor</th>
                  <th>Seed</th>
                  <th>Time</th>
                  <th>Mean speed</th>
                  <th>Files</th>
                </tr>
              </thead>
              <tbody>
                {runs
                  .filter((run) => includeEmpty || run.samples > 1)
                  .map((run) => (
                    <tr key={run.key} className={selected.includes(run.key) ? 'selected' : ''}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Compare run ${run.key}`}
                          checked={selected.includes(run.key)}
                          disabled={!selected.includes(run.key) && selected.length >= 4}
                          onChange={(e) =>
                            setSelected((prev) =>
                              e.target.checked
                                ? [...prev, run.key]
                                : prev.filter((k) => k !== run.key),
                            )
                          }
                        />
                      </td>
                      <td>
                        <strong>
                          {run.trial
                            ? conditionName(run.trial.condition) +
                              (run.trial.cell_type ? ` (${run.trial.cell_type})` : '')
                            : (run.config.protocol?.name ?? 'Workbench run')}
                        </strong>
                        <small>
                          {new Date(run.created_utc).toLocaleString()} · {run.samples} samples
                          {run.error ? ' · interrupted' : ''}
                        </small>
                      </td>
                      <td>
                        {run.config.engine === 'flygym' ? 'FlyGym' : 'Toy'}
                        <small>
                          {run.config.sensor_model === 'vision' ? 'Compound eye' : 'Geometric'} ·{' '}
                          {normalizeModel(run.config.neural_model) === 'connectome'
                            ? `connectome · ${run.config.connectome_parameters?.circuit ?? 'fafb783-dna02'}${run.config.connectome_parameters?.dynamics === 'spiking' ? ' · spiking' : ''}`
                            : 'engineered'}
                        </small>
                      </td>
                      <td>{run.config.seed}</td>
                      <td>{fmt(run.metrics.duration_s ?? (run.samples - 1) * 0.01)} s</td>
                      <td>{fmt(run.metrics.mean_speed_mm_s)} mm/s</td>
                      <td>
                        <a href={run.download_url} download aria-label={`Download run ${run.key}`}>
                          <ArrowDownToLine size={15} />
                        </a>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
        {details.length > 0 && (
          <div className="saved-comparison">
            <section className="panel trajectory-panel">
              <div className="panel-heading">
                <div>
                  <h2>Recorded trajectories</h2>
                </div>
                <span className="subtle-label">World coordinates / mm</span>
              </div>
              <svg
                viewBox="0 0 440 340"
                role="img"
                aria-label="Overlay of selected saved fly trajectories"
              >
                <path d="M220 20V310M35 165H405" stroke="#d8dfcf" />
                {details.map((run, i) => (
                  <polyline
                    key={run.key}
                    points={run.trajectory
                      ?.map((p) => `${220 + (p[1] / extent) * 150},${165 - (p[2] / extent) * 140}`)
                      .join(' ')}
                    fill="none"
                    stroke={lineColors[i]}
                    strokeDasharray={lineDashes[i]}
                    strokeWidth="2"
                  />
                ))}
                <circle cx="220" cy="165" r="3" fill="#768e61" />
                <text x="220" y="328" textAnchor="middle">
                  X ±{fmt(extent, 1)} mm
                </text>
                <text x="15" y="170" transform="rotate(-90,15,170)" textAnchor="middle">
                  Y ±{fmt(extent, 1)} mm
                </text>
              </svg>
            </section>
            <section className="comparison-outcomes">
              <h3>Measured outcomes</h3>
              {details.map((run, i) => (
                <div className="outcome" key={run.key}>
                  <div>
                    <svg width="24" height="8" aria-hidden="true">
                      <path
                        d="M1 4H23"
                        stroke={lineColors[i]}
                        strokeWidth="2"
                        strokeDasharray={lineDashes[i]}
                      />
                    </svg>
                    <strong>
                      {run.trial
                        ? conditionName(run.trial.condition)
                        : (run.config.protocol?.name ?? 'Workbench run')}
                    </strong>
                    <span>seed {run.config.seed}</span>
                  </div>
                  <dl>
                    <div>
                      <dt>Path</dt>
                      <dd>{fmt(run.metrics.path_length_mm)} mm</dd>
                    </div>
                    <div>
                      <dt>Net turn</dt>
                      <dd>{fmt(run.metrics.net_turn_deg, 1)}°</dd>
                    </div>
                    <div>
                      <dt>Final target distance</dt>
                      <dd>{fmt(run.metrics.target_distance_mm)} mm</dd>
                    </div>
                  </dl>
                  <button
                    className="text-button"
                    disabled={disabled || active}
                    onClick={async () => {
                      const result = await command('reset', run.config);
                      if (result) onLoaded();
                    }}
                  >
                    Restore starting configuration <ArrowRight size={12} />
                  </button>
                </div>
              ))}
              <p className="microcopy">
                These are descriptive results from the selected runs. Different settings, sensors,
                durations, or target schedules change what a comparison means.
              </p>
            </section>
          </div>
        )}
      </section>
    </>
  );
}
