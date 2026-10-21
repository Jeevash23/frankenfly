import {useEffect, useRef, useState, type RefObject} from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  FlaskConical,
  Layers3,
  LoaderCircle,
  X,
} from 'lucide-react';
import type {Command, Config, InterventionChange, State, Stimulus} from '../types';
import {fmt} from '../format';
import {neuralStage} from '../models';
import {BodyMeasurements, EyePanel} from '../ResearchPanels';
import {InterventionPanel} from './InterventionPanel';
import {SessionLog} from './SessionLog';
import {Signals} from './Signals';
import {type Draft, StimulusPanel} from './StimulusPanel';
import {type WorldView, WorldPanel} from './WorldPanel';

export function Workbench({
  state,
  command,
  transportPending,
  exportPending,
  disabled,
  editDisabled,
  valid,
  running,
  batchActive,
  effectiveView,
  setView,
  viewportRef,
  seed,
  setSeed,
  draft,
  setDraft,
  moveTarget,
  intervene,
  reset,
  exportRun,
  openModelNotes,
  openExperiments,
}: {
  state: State | null;
  command: Command;
  transportPending: boolean;
  exportPending: boolean;
  disabled: boolean;
  editDisabled: boolean;
  valid: boolean;
  running: boolean;
  batchActive: boolean;
  effectiveView: WorldView;
  setView: (view: WorldView) => void;
  viewportRef: RefObject<HTMLDivElement | null>;
  seed: number;
  setSeed: (seed: number) => void;
  draft: Draft;
  setDraft: (draft: Draft | ((previous: Draft) => Draft)) => void;
  moveTarget: (target: Partial<Stimulus>) => Promise<unknown>;
  intervene: (change: InterventionChange) => void;
  reset: (override?: Partial<Config>) => Promise<unknown>;
  exportRun: () => Promise<void>;
  openModelNotes: () => void;
  openExperiments: () => void;
}) {
  const runButton = useRef<HTMLButtonElement>(null);
  // The banner and its button disappear with the protocol, so focus moves on to Run.
  const [focusRun, setFocusRun] = useState(false);
  const protocol = state?.config.protocol;
  useEffect(() => {
    if (!focusRun || protocol) return;
    runButton.current?.focus();
    setFocusRun(false);
  }, [focusRun, protocol]);
  const freeRun = async () => {
    if (await reset({protocol: null})) setFocusRun(true);
  };
  return (
    <>
      {state?.config.protocol && (
        <div className="protocol-banner">
          <span>
            <FlaskConical size={15} />
            <strong>{state.config.protocol.name}</strong> · stops at{' '}
            {fmt(state.config.protocol.duration_steps / 100)} s
            {state.metrics.protocol_complete ? ' · completed' : ''}
          </span>
          <span>
            <button onClick={openExperiments}>
              {batchActive
                ? `Comparison trial ${state.batch?.current}/${state.batch?.total}`
                : 'Edit protocol'}{' '}
              <ArrowRight size={13} />
            </button>
            {!batchActive && (
              <button
                disabled={editDisabled}
                title="Start a fresh run without a protocol; it runs until you pause it"
                onClick={() => void freeRun()}
              >
                <X size={13} />
                Remove protocol (free run)
              </button>
            )}
          </span>
        </div>
      )}
      <div className="workspace-grid">
        <div className="main-column">
          <WorldPanel
            state={state}
            command={command}
            transportPending={transportPending}
            runButton={runButton}
            disabled={disabled}
            editDisabled={editDisabled}
            valid={valid}
            running={running}
            effectiveView={effectiveView}
            setView={setView}
            viewportRef={viewportRef}
            moveTarget={moveTarget}
            reset={() => void reset()}
            seed={seed}
            setSeed={setSeed}
          />
          <Signals state={state} />
          <EyePanel state={state} />
          <BodyMeasurements state={state} />
          <section className="loop-strip" aria-label="Model provenance">
            <div>
              <Layers3 size={16} />
              <strong>One continuous loop</strong>
            </div>
            <span>World</span>
            <ArrowRight size={13} />
            <span>
              {
                {vision: 'Compound eyes', flyvis: 'FlyVis eyes', geometric: 'Geometric sensors'}[
                  state?.config.sensor_model ?? 'geometric'
                ]
              }
            </span>
            <ArrowRight size={13} />
            <span>{neuralStage(state?.config ?? {neural_model: 'engineered'})}</span>
            <ArrowRight size={13} />
            <span>{state?.config.engine === 'toy' ? 'Kinematics' : 'FlyGym body'}</span>
            <button onClick={openModelNotes} aria-label="Inspect model provenance">
              <ArrowUpRight size={17} />
            </button>
          </section>
        </div>
        <aside className="inspector">
          <StimulusPanel
            state={state}
            editDisabled={editDisabled}
            running={running}
            reset={reset}
            moveTarget={moveTarget}
            draft={draft}
            setDraft={setDraft}
          />
          <InterventionPanel state={state} editDisabled={editDisabled} intervene={intervene} />
          <button
            className="export-button"
            disabled={disabled || !state?.sample}
            aria-busy={exportPending}
            onClick={() => {
              if (!exportPending) void exportRun();
            }}
          >
            {exportPending ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <ArrowDownToLine size={16} />
            )}
            <span>
              Export this run<small>Telemetry, configuration & events</small>
            </span>
            <ArrowUpRight size={15} />
          </button>
        </aside>
      </div>
      <SessionLog state={state} editDisabled={editDisabled} running={running} reset={reset} />
    </>
  );
}
