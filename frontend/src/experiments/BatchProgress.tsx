import {Pause, Play, Square} from 'lucide-react';
import type {Command, State} from '../types';
import {fmt} from '../format';
import {conditionName} from '../models';

// The running or last comparison: progress, pause/resume/cancel and, once it ended, what was saved
// and whether the Workbench configuration from before it was restored.
export function BatchProgress({
  state,
  command,
  disabled,
}: {
  state: State;
  command: Command;
  disabled: boolean;
}) {
  const batch = state.batch;
  if (!batch) return null;
  const active = batch.status === 'running' || batch.status === 'paused';
  // Servers since v0.6 restore the Workbench after a comparison; they also report max_speed.
  const restores = batch.max_speed !== undefined;
  return (
    <section className={`batch-progress panel ${batch.status}`} aria-label="Comparison progress">
      {/* Announced on transitions only (status, trial, condition, seed); the per-tick
          simulated time below stays outside the live region. */}
      <div role="status">
        <span className="eyebrow">
          {batch.status.toUpperCase()}
          {batch.max_speed ? ' · AS FAST AS POSSIBLE' : ''}
        </span>
        <h3>{batch.protocol}</h3>
        <p>
          Trial {batch.current} of {batch.total} · {conditionName(batch.condition ?? '')}
          {batch.condition === 'cell_type_off' && batch.cell_type ? ` (${batch.cell_type})` : ''} ·
          seed {batch.seed}
        </p>
      </div>
      <div className="batch-meter">
        <span>{batch.results.length} trials saved</span>
        <progress max={batch.total} value={batch.results.length} />
        <small>
          {batch.error ??
            (active
              ? `${fmt(state.sample?.t)} / ${fmt((state.config.protocol?.duration_steps ?? 0) / 100)} simulated seconds in this trial`
              : 'All completed trials are in the local library below.')}
        </small>
        {!active && (
          <ul className="batch-notes" role="status">
            {batch.partial && (
              <li>
                The unfinished trial ({conditionName(batch.partial.condition ?? batch.condition)},
                seed {batch.partial.seed ?? batch.seed}) was saved too, marked <b>partial</b>.
              </li>
            )}
            {batch.partial_error && <li className="form-error">{batch.partial_error}</li>}
            {batch.restore_error ? (
              <li className="form-error">{batch.restore_error}</li>
            ) : restores ? (
              <li>The Workbench is back to its configuration from before the comparison.</li>
            ) : null}
          </ul>
        )}
      </div>
      {active && (
        <div className="batch-buttons">
          <button
            className="secondary-button"
            disabled={disabled}
            onClick={() => void command(batch.status === 'paused' ? 'run' : 'pause')}
          >
            {batch.status === 'paused' ? <Play size={14} /> : <Pause size={14} />}{' '}
            {batch.status === 'paused' ? 'Resume' : 'Pause'}
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
  );
}
