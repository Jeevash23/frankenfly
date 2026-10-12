import type {RefObject} from 'react';
import {ArrowDownToLine, ArrowRight, ArrowUpRight, FlaskConical, Layers3} from 'lucide-react';
import type {Command, Config, Intervention, State, Stimulus} from '../types';
import {fmt} from '../format';
import {BodyMeasurements, EyePanel} from '../ResearchPanels';
import {InterventionPanel} from './InterventionPanel';
import {SessionLog} from './SessionLog';
import {Signals} from './Signals';
import {type Draft, StimulusPanel} from './StimulusPanel';
import {type WorldView, WorldPanel} from './WorldPanel';

export function Workbench({
  state,
  command,
  busy,
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
  busy: boolean;
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
  moveTarget: (target: Partial<Stimulus>) => void;
  intervene: (value: Partial<Intervention>) => void;
  reset: (override?: Partial<Config>) => void;
  exportRun: () => Promise<void>;
  openModelNotes: () => void;
  openExperiments: () => void;
}) {
  return (
    <>
      {state?.config.protocol && (
        <div className="protocol-banner">
          <span>
            <FlaskConical size={15} />
            <strong>{state.config.protocol.name}</strong> · stops at{' '}
            {fmt(state.config.protocol.duration_steps / 100)} s
          </span>
          <button onClick={openExperiments}>
            {batchActive
              ? `Comparison trial ${state.batch?.current}/${state.batch?.total}`
              : 'Edit protocol'}{' '}
            <ArrowRight size={13} />
          </button>
        </div>
      )}
      <div className="workspace-grid">
        <div className="main-column">
          <WorldPanel
            state={state}
            command={command}
            busy={busy}
            disabled={disabled}
            editDisabled={editDisabled}
            valid={valid}
            running={running}
            effectiveView={effectiveView}
            setView={setView}
            viewportRef={viewportRef}
            moveTarget={moveTarget}
            reset={() => reset()}
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
              {state?.config.sensor_model === 'vision' ? 'Compound eyes' : 'Geometric sensors'}
            </span>
            <ArrowRight size={13} />
            <span>6 rate units</span>
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
            onClick={() => void exportRun()}
          >
            <ArrowDownToLine size={16} />
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
