import {useEffect, useRef, useState} from 'react';
import {Sparkles} from 'lucide-react';
import type {
  BatchRequest,
  Command,
  Condition,
  Config,
  CustomCondition,
  Job,
  Protocol,
  State,
} from '../types';
import type {Pending} from '../useSimulation';
import {request} from '../api';
import {
  conditionNames,
  conditionProblem,
  conditionsFor,
  firstExperiment,
  noInterventions,
} from '../models';
import {customProblem, customRequest, parseSeeds, sizeProblem} from '../comparison';
import {preset, scheduleProblem, sortedEvents} from '../protocol';
import {finishedReplays} from '../jobs';
import {clearDraft, DRAFT_KEYS, loadDraft, readExperimentsDraft} from '../localDrafts';
import {useLocalDraft} from '../useLocalDraft';
import {useJobs} from '../useJobs';
import {useCircuit} from '../connectome/useCircuit';
import {BatchProgress} from './BatchProgress';
import {ComparisonBuilder} from './ComparisonBuilder';
import {ComparisonSummary} from './ComparisonSummary';
import {JobsPanel} from './JobsPanel';
import {ProtocolEditor} from './ProtocolEditor';
import {RunLibrary} from './RunLibrary';
import {ScorecardPanel} from './Scorecard';

export default function Experiments({
  state,
  command,
  pending,
  disabled,
  onLoaded,
}: {
  state: State | null;
  command: Command;
  pending: Pending;
  disabled: boolean;
  onLoaded: () => void;
}) {
  // The draft (protocol, seeds, conditions) survives page switches and reloads until it is run.
  const [draft] = useState(() => loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft) ?? {});
  const [protocol, setProtocol] = useState<Protocol>(
    draft.protocol ?? state?.config.protocol ?? preset('Target reversal', 2),
  );
  const [seeds, setSeeds] = useState(draft.seeds ?? '42, 43');
  const [conditions, setConditions] = useState<Condition[]>(
    draft.conditions ?? ['control', 'left_sensor_off'],
  );
  const [cellType, setCellType] = useState(draft.cellType ?? '');
  const [custom, setCustom] = useState<CustomCondition[]>(draft.custom ?? []);
  const [maxSpeed, setMaxSpeed] = useState(draft.maxSpeed ?? false);
  const edits = {protocol, seeds, conditions, cellType, custom, maxSpeed};
  useLocalDraft(DRAFT_KEYS.experiments, edits);
  const model = state?.config.neural_model ?? 'engineered';
  const sensor = state?.config.sensor_model ?? 'geometric';
  const dynamics = state?.config.connectome_parameters.dynamics ?? 'rate';
  const {circuit} = useCircuit(state);
  // DNa02 conditions need a circuit with DNa02; assume one until the circuit has loaded.
  const hasDNa02 = !circuit || circuit.types.some((t) => t.name === 'DNa02');
  const available = conditionsFor(model, hasDNa02, sensor);
  const customCount = useRef(custom.length);
  customCount.current = custom.length;
  // Switching models, sensors or circuits drops conditions that are no longer available (not
  // before the first snapshot says which model is selected).
  useEffect(() => {
    if (!state) return;
    setConditions((previous) => {
      const kept = previous.filter((c) => conditionsFor(model, hasDNa02, sensor).includes(c));
      return kept.length || customCount.current ? kept : ['control'];
    });
  }, [model, hasDNa02, sensor, !!state]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [runError, setRunError] = useState('');
  const [starting, setStarting] = useState(false);
  // A refusal from the server stays until the comparison is edited.
  const editsJson = JSON.stringify(edits);
  useEffect(() => setRunError(''), [editsJson]);
  const active = !!state?.batch && ['running', 'paused'].includes(state.batch.status);

  // Background jobs; the library reloads when a replay check finishes, for its new verdict.
  const {jobs, loaded, error: jobsError, refresh: refreshJobs, cancel: cancelJob} = useJobs();
  const [reload, setReload] = useState(0);
  // The comparison whose trials the library lists ("Show these trials in the library").
  const [showBatch, setShowBatch] = useState<{id: string; at: number} | null>(null);
  // The jobs of the first listing that have finished are not news.
  const previousJobs = useRef<Job[] | null>(null);
  useEffect(() => {
    if (!loaded) return;
    if (previousJobs.current && finishedReplays(previousJobs.current, jobs).length)
      setReload((n) => n + 1);
    previousJobs.current = jobs;
  }, [jobs, loaded]);

  const schedule = scheduleProblem(protocol);
  const parsedSeeds = parseSeeds(seeds);
  const problem =
    ('problem' in parsedSeeds ? parsedSeeds.problem : null) ??
    conditionProblem(conditions, model, cellType, hasDNa02, sensor, custom.length) ??
    customProblem(custom, model) ??
    ('seeds' in parsedSeeds
      ? sizeProblem(
          protocol.duration_steps,
          parsedSeeds.seeds.length,
          conditions.length + custom.length,
        )
      : null);
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
  const run = async () => {
    if (!state || starting || problem || schedule || !('seeds' in parsedSeeds)) return;
    setRunError('');
    setError('');
    setNotice('');
    setStarting(true);
    const body: BatchRequest = {
      config: config(),
      seeds: parsedSeeds.seeds,
      conditions,
      cell_type: conditions.includes('cell_type_off') ? cellType.trim() : null,
      custom_conditions: custom.map(customRequest),
      max_speed: maxSpeed,
    };
    const r = await request('POST', '/api/batch/start', body);
    setStarting(false);
    if (!r.ok) return setRunError(r.error);
    clearDraft(DRAFT_KEYS.experiments);
    setNotice('Comparison started. Each complete trial is saved automatically.');
  };
  const loadFirstExperiment = () => {
    const first = firstExperiment(model, hasDNa02);
    setProtocol(first.protocol);
    setSeeds(first.seeds);
    setConditions(first.conditions);
    setCustom([]);
    setError('');
    setNotice(
      `First experiment ready: ${first.protocol.name.toLowerCase()} over ${first.protocol.duration_steps / 100} simulated seconds, seeds ${first.seeds}, comparing “${conditionNames[first.conditions[0]]}” with “${conditionNames[first.conditions[1]]}”. Press Run comparison to start. The research guide's walkthrough also switches to compound-eye input on the Workbench.`,
    );
  };
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
        <ProtocolEditor
          protocol={protocol}
          setProtocol={setProtocol}
          disabled={disabled || active}
          load={() => void load()}
        />
        <ComparisonBuilder
          model={model}
          dynamics={dynamics}
          parameters={state?.config.connectome_parameters}
          circuit={circuit}
          available={available}
          seeds={seeds}
          setSeeds={setSeeds}
          conditions={conditions}
          setConditions={setConditions}
          cellType={cellType}
          setCellType={setCellType}
          custom={custom}
          setCustom={setCustom}
          maxSpeed={maxSpeed}
          setMaxSpeed={setMaxSpeed}
          problem={problem ?? (schedule ? `Fix the stimulus protocol first: ${schedule}` : null)}
          serverError={runError}
          disabled={disabled || active}
          pending={starting || !!pending['batch/start']}
          run={() => void run()}
        />
      </div>
      {state?.batch && <BatchProgress state={state} command={command} disabled={disabled} />}
      {state?.batch && !active && state.batch.results.length > 0 && (
        <ComparisonSummary
          batchId={state.batch.id}
          reload={`${state.batch.status}-${state.batch.results.length}-${reload}`}
          showTrials={() => setShowBatch({id: state.batch!.id, at: Date.now()})}
        />
      )}
      {jobsError && <p className="microcopy">{jobsError}</p>}
      <ScorecardPanel state={state} jobs={jobs} refreshJobs={refreshJobs} disabled={disabled} />
      <JobsPanel jobs={jobs} cancel={(id) => void cancelJob(id)} />
      <RunLibrary
        state={state}
        command={command}
        disabled={disabled}
        batchActive={active}
        jobs={jobs}
        refreshJobs={refreshJobs}
        cancelJob={cancelJob}
        reload={reload}
        showBatch={showBatch}
        onLoaded={onLoaded}
      />
    </>
  );
}
