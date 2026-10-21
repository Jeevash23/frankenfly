import {ArrowRight, ChevronDown, FlaskConical, Plus, Trash2} from 'lucide-react';
import type {Protocol} from '../types';
import {fmt} from '../format';
import {edited, freeStep, preset, presets, scheduleProblem, withDuration} from '../protocol';

// The stimulus protocol: a preset or custom sequence of timed target changes, loaded into the
// Workbench as a fresh run or used by every trial of a comparison.
export function ProtocolEditor({
  protocol,
  setProtocol,
  disabled,
  load,
}: {
  protocol: Protocol;
  setProtocol: (protocol: Protocol | ((previous: Protocol) => Protocol)) => void;
  disabled: boolean;
  load: () => void;
}) {
  const problem = scheduleProblem(protocol);
  const duration = protocol.duration_steps / 100;
  return (
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
              disabled={disabled}
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
            disabled={disabled}
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
                    disabled={disabled}
                    value={event.step / 100}
                    onChange={(e) =>
                      setProtocol((p) =>
                        edited(
                          p,
                          p.events.map((ev, j) =>
                            j === i ? {...ev, step: Math.round(Number(e.target.value) * 100)} : ev,
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
                      disabled={disabled}
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
                    disabled={disabled}
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
          disabled={disabled || protocol.events.length >= 8}
          onClick={() =>
            setProtocol((p) =>
              edited(p, [...p.events, {step: freeStep(p), stimulus: {x: 12, y: -8, intensity: 1}}]),
            )
          }
        >
          <Plus size={14} />
          Add stimulus change
        </button>
        <button className="secondary-button" disabled={disabled || !!problem} onClick={load}>
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
  );
}
