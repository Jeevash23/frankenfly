import {ChevronDown} from 'lucide-react';
import type {Config, State} from '../types';
import {fmt} from '../format';

export function SessionLog({
  state,
  editDisabled,
  running,
  reset,
}: {
  state: State | null;
  editDisabled: boolean;
  running: boolean;
  reset: (override?: Partial<Config>) => void;
}) {
  return (
    <section className="session-section" id="session-log">
      <div className="session-heading">
        <div>
          <span className="eyebrow">EXPERIMENT RECORD</span>
          <h2>Session log</h2>
        </div>
        <span>
          {state?.recording_samples ?? 0} / {state?.recording_limit ?? 30000} samples retained
        </span>
      </div>
      <div className="session-grid">
        <div className="event-list" aria-label="Session events">
          {state?.events.length ? (
            [...state.events]
              .reverse()
              .slice(0, 6)
              .map((event) => (
                <div className="event-row" key={`${state.run_id}-${event.seq}`}>
                  <time>{fmt(event.t, 3)} s</time>
                  <span className={`event-dot ${event.kind === 'error' ? 'error' : ''}`} />
                  <span>{event.message}</span>
                  <small>STEP {String(event.step).padStart(4, '0')}</small>
                </div>
              ))
          ) : (
            <p className="microcopy">Events appear here when the local experiment is ready.</p>
          )}
        </div>
        <div className="configuration">
          <label className="field-label">
            Body engine
            <div className="select-wrap">
              <select
                aria-label="Body engine"
                disabled={editDisabled || running}
                value={state?.config.engine ?? 'flygym'}
                onChange={(e) =>
                  reset({
                    engine: e.target.value as Config['engine'],
                    sensor_model:
                      e.target.value === 'toy'
                        ? 'geometric'
                        : (state?.config.sensor_model ?? 'geometric'),
                  })
                }
              >
                <option value="flygym">FlyGym · real physics</option>
                <option value="toy">Toy demo · kinematic</option>
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
          <label className="field-label">
            Control mode
            <div className="select-wrap">
              <select
                aria-label="Control mode"
                disabled={editDisabled || running}
                value={state?.config.controller ?? 'neural'}
                onChange={(e) => reset({controller: e.target.value as Config['controller']})}
              >
                <option value="neural">Engineered neural loop</option>
                <option value="baseline">Controller-only baseline</option>
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
          <p className="microcopy">Changing either starts a fresh experiment.</p>
        </div>
      </div>
    </section>
  );
}
