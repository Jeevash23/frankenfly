import {Play} from 'lucide-react';
import type {
  Condition,
  ConnectomeParameters,
  CustomCondition,
  Dynamics,
  NeuralModel,
} from '../types';
import {conditionNames, MAX_BUILT_IN, MAX_CONDITIONS, modelPhrases} from '../models';
import type {CircuitSummary} from '../connectome/layout';
import {CustomConditions} from './CustomConditions';

// Seeds × conditions, built-in and custom, run one trial at a time on this computer.
export function ComparisonBuilder({
  model,
  dynamics,
  parameters,
  circuit,
  available,
  seeds,
  setSeeds,
  conditions,
  setConditions,
  cellType,
  setCellType,
  custom,
  setCustom,
  maxSpeed,
  setMaxSpeed,
  problem,
  serverError,
  disabled,
  pending,
  run,
}: {
  model: NeuralModel;
  dynamics: Dynamics;
  parameters: ConnectomeParameters | undefined;
  circuit: CircuitSummary | null;
  available: Condition[];
  seeds: string;
  setSeeds: (seeds: string) => void;
  conditions: Condition[];
  setConditions: (update: (previous: Condition[]) => Condition[]) => void;
  cellType: string;
  setCellType: (cellType: string) => void;
  custom: CustomCondition[];
  setCustom: (update: (previous: CustomCondition[]) => CustomCondition[]) => void;
  maxSpeed: boolean;
  setMaxSpeed: (on: boolean) => void;
  // Why the comparison cannot run as set up, or null.
  problem: string | null;
  // The server's refusal of the last attempt, as a sentence.
  serverError: string;
  disabled: boolean;
  pending: boolean;
  run: () => void;
}) {
  const total = conditions.length + custom.length;
  return (
    <section className="panel comparison-builder">
      <div className="panel-heading">
        <div>
          <h2>Compare conditions</h2>
        </div>
        <span className="subtle-label">
          {total} of {MAX_CONDITIONS} conditions
        </span>
      </div>
      <div className="comparison-body">
        <label className="field-label">
          Random seeds
          <input
            aria-label="Comparison seeds"
            value={seeds}
            disabled={disabled}
            onChange={(e) => setSeeds(e.target.value)}
            placeholder="42, 43"
          />
        </label>
        <p className="microcopy">The same seeds are used for each condition.</p>
        <fieldset className="condition-list">
          <legend>Built-in conditions (up to {MAX_BUILT_IN})</legend>
          {available.map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={conditions.includes(key)}
                disabled={
                  disabled ||
                  (!conditions.includes(key) &&
                    (conditions.length >= MAX_BUILT_IN || total >= MAX_CONDITIONS))
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
        </fieldset>
        {conditions.includes('cell_type_off') && (
          <label className="field-label">
            Cell type to silence
            <input
              className="type-input"
              list="comparison-cell-types"
              aria-label="Cell type to silence in the comparison"
              value={cellType}
              disabled={disabled}
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
        <div className="custom-block">
          <h3>Custom conditions</h3>
          <p className="microcopy">
            Your own labelled conditions: interventions held for the whole trial
            {model === 'connectome' ? ' and, optionally, other values of a few parameters' : ''}.
          </p>
          <CustomConditions
            custom={custom}
            setCustom={setCustom}
            model={model}
            dynamics={dynamics}
            parameters={parameters}
            circuit={circuit}
            disabled={disabled}
            canAdd={total < MAX_CONDITIONS}
          />
        </div>
        <label className="check-label max-speed">
          <input
            type="checkbox"
            checked={maxSpeed}
            disabled={disabled}
            onChange={(e) => setMaxSpeed(e.target.checked)}
          />
          <span>
            Run as fast as possible
            <small>Trials run unpaced instead of at the Workbench display speed.</small>
          </span>
        </label>
        <p className="microcopy">
          Runs happen sequentially using the selected body, sensor and the {modelPhrases[model]}{' '}
          (unless a condition switches the model). Up to {MAX_CONDITIONS} conditions, at most{' '}
          {MAX_BUILT_IN} of them built-in. The Workbench returns to its configuration afterwards.
        </p>
        {problem && (
          <p className="schedule-problem" role="status">
            {problem}
          </p>
        )}
        {serverError && (
          <p className="form-error" role="alert">
            The comparison could not start: {serverError}
          </p>
        )}
        <button
          className="primary-button"
          disabled={disabled || !!problem}
          aria-busy={pending}
          onClick={run}
        >
          <Play size={14} />
          Run comparison
        </button>
        <small className="comparison-bound">
          Up to 5 seeds × {MAX_CONDITIONS} conditions · 300 simulated seconds total
        </small>
      </div>
    </section>
  );
}
