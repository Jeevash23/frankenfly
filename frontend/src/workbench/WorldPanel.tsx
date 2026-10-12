import type {RefObject} from 'react';
import {ChevronDown, Expand, LoaderCircle, Pause, Play, RotateCcw, SkipForward} from 'lucide-react';
import type {Command, Sample, State, Stimulus} from '../types';
import {fmt} from '../format';
import {modelDrivers, modelNames, modelPhrases, slowdownNote} from '../models';
import {Arena} from './Arena';

export type WorldView = 'specimen' | 'arena';

export function WorldPanel({
  state,
  command,
  busy,
  disabled,
  editDisabled,
  valid,
  running,
  effectiveView,
  setView,
  viewportRef,
  moveTarget,
  reset,
  seed,
  setSeed,
}: {
  state: State | null;
  command: Command;
  busy: boolean;
  disabled: boolean;
  editDisabled: boolean;
  valid: boolean;
  running: boolean;
  effectiveView: WorldView;
  setView: (view: WorldView) => void;
  viewportRef: RefObject<HTMLDivElement | null>;
  moveTarget: (target: Partial<Stimulus>) => void;
  reset: () => void;
  seed: number;
  setSeed: (seed: number) => void;
}) {
  const sample: Sample | undefined = state?.sample ?? undefined;
  const model = state?.config.neural_model ?? 'engineered';
  const slow = slowdownNote(state?.real_time_factor ?? 0, state?.config.speed ?? 1, running);
  return (
    <section className="world-panel panel">
      <div className="panel-heading">
        <div>
          <span className="section-no">01</span>
          <h2>The world</h2>
        </div>
        <div className="segmented" aria-label="World view">
          <button
            className={effectiveView === 'specimen' ? 'selected' : ''}
            disabled={!state?.rendering}
            onClick={() => setView('specimen')}
          >
            Specimen
          </button>
          <button
            className={effectiveView === 'arena' ? 'selected' : ''}
            onClick={() => setView('arena')}
          >
            Arena
          </button>
        </div>
      </div>
      <div className={`world-canvas ${effectiveView}`} ref={viewportRef}>
        {effectiveView === 'specimen' ? (
          <img
            className="physics-frame"
            src={`/api/frame?v=${state?.frame_revision}`}
            alt="Live MuJoCo rendering of the simulated NeuroMechFly body"
          />
        ) : (
          <Arena state={state} disabled={editDisabled} onTarget={moveTarget} />
        )}
        <div className="viewport-top">
          <span className="viewport-label">
            <i className={running ? 'running-dot' : ''} />
            {!state ? 'INITIALIZING' : state.status.toUpperCase()}
          </span>
          <span className="viewport-label">
            {effectiveView === 'specimen'
              ? 'MUJOCO / TRACKING CAMERA'
              : 'POSE SCHEMATIC / TOP VIEW'}
          </span>
        </div>
        {!state?.sample && (
          <div className="viewport-loading">
            <LoaderCircle className="spin" size={22} />
            <span>
              {state?.error ? 'Body unavailable · see the error above' : 'Preparing the specimen'}
            </span>
          </div>
        )}
        <div className="viewport-bottom">
          <div className="specimen-caption">
            <span>
              {state?.config.engine === 'toy'
                ? 'Kinematic demonstration'
                : 'Drosophila melanogaster'}
            </span>
            <small>
              {effectiveView === 'specimen'
                ? 'NeuroMechFly body · actual physics render'
                : 'Measured position · click the map to place a target'}
            </small>
          </div>
          <button
            className="viewport-expand"
            title="Expand world view"
            aria-label="Expand world view"
            onClick={() => {
              if (!document.fullscreenElement) void viewportRef.current?.requestFullscreen();
              else void document.exitFullscreen();
            }}
          >
            <Expand size={16} />
          </button>
        </div>
      </div>
      {state?.render_error && (
        <div className="render-note" role="status">
          {state.render_error}
        </div>
      )}
      <div className="transport">
        <div className="playback">
          <button
            className="primary-button run-button"
            disabled={disabled || !valid || !!state?.metrics.protocol_complete}
            onClick={() => void command(running ? 'pause' : 'run')}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : running ? (
              <Pause size={15} fill="currentColor" />
            ) : (
              <Play size={15} fill="currentColor" />
            )}
            {running ? 'Pause' : 'Run simulation'}
            <kbd>␣</kbd>
          </button>
          <button
            className="secondary-button step-button"
            disabled={editDisabled || !valid || running || !!state?.metrics.protocol_complete}
            title="Advance one 10 ms control interval"
            onClick={() => void command('step')}
          >
            <SkipForward size={16} />
            Step
          </button>
          <button
            className="icon-button reset-button"
            disabled={editDisabled}
            title="Reset body, clock, circuit, and target to defaults"
            aria-label="Reset experiment"
            onClick={() => reset()}
          >
            <RotateCcw size={16} />
          </button>
        </div>
        <div className="transport-options">
          <label className="seed-label">
            Seed
            <input
              aria-label="Random seed"
              type="number"
              min="0"
              max="2147483647"
              value={seed}
              disabled={editDisabled || running}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isInteger(v) && v >= 0 && v <= 2147483647) setSeed(v);
              }}
              title="Applied on Reset"
            />
          </label>
          <div className="select-wrap speed-select">
            <select
              aria-label="Requested simulation speed"
              disabled={editDisabled}
              value={state?.config.speed ?? 0.25}
              onChange={(e) => void command('speed', {speed: Number(e.target.value)})}
            >
              {[0.05, 0.1, 0.25, 0.5, 1, 2].map((speed) => (
                <option key={speed} value={speed}>
                  {speed}× speed
                </option>
              ))}
            </select>
            <ChevronDown size={12} />
          </div>
        </div>
      </div>
      {slow && (
        <p className="slowdown-note" role="status">
          {slow}
        </p>
      )}
      <div className="telemetry-strip">
        <div>
          <span>Simulated time</span>
          <strong>
            {fmt(sample?.t)}
            <small>s</small>
          </strong>
        </div>
        <div>
          <span>Body speed</span>
          <strong>
            {fmt(sample?.pose.velocity)}
            <small>mm/s</small>
          </strong>
        </div>
        <div>
          <span>Real-time factor</span>
          <strong>
            {fmt(state?.real_time_factor)}
            <small>×</small>
          </strong>
        </div>
        <div>
          <span>Active wall time</span>
          <strong>
            {fmt(state?.wall_s, 1)}
            <small>s</small>
          </strong>
        </div>
      </div>
      <div className="model-driver" aria-label="What drives the fly">
        <strong>Driving the fly</strong>
        <span>
          {state?.config.controller === 'baseline'
            ? `Controller-only baseline: the ${modelPhrases[model]} is computed but bypassed`
            : `${modelNames[model]} · ${modelDrivers[model]}`}
        </span>
      </div>
    </section>
  );
}
