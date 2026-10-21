import {useId, useState} from 'react';
import {ChevronDown, RotateCcw, X} from 'lucide-react';
import type {CellTypeIntervention, Dynamics, Intervention, ManipulationMode, Side} from '../types';
import {
  entryProblem,
  manipulationLabel,
  manipulations,
  modeNames,
  neuronCounts,
  replaced,
  sideNames,
  valueRange,
  type Manipulation,
} from '../interventions';
import type {CircuitSummary} from './layout';

export const MANIPULATION_NOTE =
  'Engineered manipulations: activation approximates optogenetic activation and scaling is graded inhibition or a boost of transmission; neither is calibrated to an opsin, light level or recorded firing rate.';

const valueNames: Record<Exclude<ManipulationMode, 'silence'>, Record<Dynamics, string>> = {
  scale: {rate: 'Output multiplier', spiking: 'Output multiplier'},
  activate: {rate: 'Clamped rate', spiking: 'Poisson input per neuron'},
};

// Sets one manipulation of a cell type: side, mode and, for scaling and activation, a value in the
// units of the active dynamics. Setting it replaces whatever already acts on the same side(s) of
// that type. `name` fixes the cell type (the circuit inspector); otherwise it is typed here.
export function ManipulationEditor({
  name: fixedName,
  circuit,
  dynamics,
  interventions,
  disabled,
  onSet,
}: {
  name?: string;
  circuit: CircuitSummary | null;
  dynamics: Dynamics;
  interventions: Intervention | null | undefined;
  disabled: boolean;
  onSet: (entry: CellTypeIntervention) => void;
}) {
  const id = useId();
  const [typed, setTyped] = useState('');
  const [side, setSide] = useState<Side>('both');
  const [mode, setMode] = useState<ManipulationMode>('silence');
  // The value last chosen for each mode and dynamics; a fresh one starts at a typical value.
  const [values, setValues] = useState<Record<string, number>>({});
  const range = valueRange(mode, dynamics);
  const value = values[`${mode}:${dynamics}`] ?? range?.initial ?? 0;
  const name = (fixedName ?? typed).trim();
  const type = circuit?.types.find((t) => t.name === name);
  // Large circuits list only the types nearest the readout; the server checks the rest.
  const complete = !circuit || circuit.types_shown >= circuit.types_total;
  const entry: CellTypeIntervention = {name, side, mode, value: mode === 'silence' ? 0 : value};
  const problem = entryProblem(entry, dynamics, type, complete);
  const replacing = name ? replaced(interventions, name, side) : [];
  const apply = () => {
    if (disabled || problem) return;
    onSet(entry);
    if (!fixedName) setTyped('');
  };
  return (
    <div
      className="manipulation-editor"
      role="group"
      aria-label={`Manipulate ${fixedName ?? 'a cell type'}`}
    >
      {!fixedName && (
        <>
          <label className="field-label">
            Cell type
            <input
              className="type-input"
              list={`${id}-types`}
              value={typed}
              disabled={disabled || !circuit}
              placeholder={circuit ? 'Name, e.g. DNa02' : 'Loading cell types…'}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') apply();
              }}
            />
          </label>
          <datalist id={`${id}-types`}>
            {circuit?.types.map((t) => (
              <option key={t.name} value={t.name}>
                {t.count} neurons ({t.left} L, {t.right} R), hop {t.layer}
              </option>
            ))}
          </datalist>
        </>
      )}
      <div className="manipulation-choices">
        <label className="field-label">
          Side
          <div className="select-wrap">
            <select
              aria-label="Side"
              value={side}
              disabled={disabled}
              onChange={(e) => setSide(e.target.value as Side)}
            >
              {(Object.keys(sideNames) as Side[]).map((s) => (
                <option key={s} value={s}>
                  {sideNames[s]}
                  {type && s !== 'both' ? ` (${type[s]})` : ''}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </div>
        </label>
        <label className="field-label">
          Manipulation
          <div className="select-wrap">
            <select
              aria-label="Manipulation"
              value={mode}
              disabled={disabled}
              onChange={(e) => setMode(e.target.value as ManipulationMode)}
            >
              {(Object.keys(modeNames) as ManipulationMode[]).map((m) => (
                <option key={m} value={m}>
                  {modeNames[m]}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </div>
        </label>
      </div>
      {range && mode !== 'silence' && (
        <div className="value-field">
          <label htmlFor={`${id}-value`}>{valueNames[mode][dynamics]}</label>
          <span>
            <input
              id={`${id}-value`}
              type="number"
              min={range.min}
              max={range.max}
              step={range.step}
              value={value}
              disabled={disabled}
              onChange={(e) =>
                setValues((v) => ({...v, [`${mode}:${dynamics}`]: Number(e.target.value)}))
              }
            />
            <small>{range.unit}</small>
          </span>
          <input
            type="range"
            aria-label={`${valueNames[mode][dynamics]} (${range.unit})`}
            min={range.min}
            max={range.max}
            step={range.step}
            value={value}
            disabled={disabled}
            onChange={(e) =>
              setValues((v) => ({...v, [`${mode}:${dynamics}`]: Number(e.target.value)}))
            }
          />
        </div>
      )}
      {name && problem ? (
        <p className="microcopy" role="status">
          {problem}
        </p>
      ) : replacing.length ? (
        <p className="microcopy">
          Replaces {replacing.map((m) => manipulationLabel(m, dynamics)).join(', ')}.
        </p>
      ) : null}
      <button
        type="button"
        className="secondary-button"
        disabled={disabled || !!problem}
        onClick={apply}
      >
        {replacing.length ? 'Replace with' : 'Apply'}{' '}
        {name ? manipulationLabel(entry, dynamics) : 'manipulation'}
      </button>
    </div>
  );
}

// The cell-type manipulations in force, each with a remove button, and the neurons they reach.
export function ManipulationList({
  interventions,
  dynamics,
  counts,
  disabled,
  onRemove,
  onRestoreAll,
}: {
  interventions: Intervention | null | undefined;
  dynamics: Dynamics;
  counts?: {silence: number; scale: number; activate: number};
  disabled: boolean;
  onRemove: (item: Manipulation) => void;
  onRestoreAll?: () => void;
}) {
  const items = manipulations(interventions);
  if (!items.length) return null;
  const reached = neuronCounts(counts);
  return (
    <div className="manipulation-list">
      <ul aria-label="Cell-type manipulations in force">
        {items.map((m) => {
          const label = manipulationLabel(m, dynamics);
          return (
            <li key={`${m.source}-${m.name}-${m.side}`}>
              <span>{label}</span>
              <button
                type="button"
                className="icon-button"
                disabled={disabled}
                aria-label={`Remove: ${label}`}
                title="Remove this manipulation"
                onClick={() => onRemove(m)}
              >
                <X size={13} />
              </button>
            </li>
          );
        })}
      </ul>
      <p className="microcopy">
        {reached ? `Neurons now: ${reached}.` : 'Applies from the next step.'}
        {onRestoreAll && (
          <>
            {' '}
            <button
              type="button"
              className="text-button"
              disabled={disabled}
              onClick={onRestoreAll}
            >
              <RotateCcw size={11} /> Remove all
            </button>
          </>
        )}
      </p>
    </div>
  );
}
