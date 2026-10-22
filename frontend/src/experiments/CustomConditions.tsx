import {ChevronDown, Plus, Trash2} from 'lucide-react';
import type {
  ConnectomeParameters,
  CustomCondition,
  Dynamics,
  Intervention,
  NeuralModel,
} from '../types';
import {noInterventions} from '../models';
import {CUSTOM_PARAMETERS, LABEL_LIMIT, customSummary, newCustomCondition} from '../comparison';
import {withCellType, withoutManipulation} from '../interventions';
import type {CircuitSummary} from '../connectome/layout';
import {ManipulationEditor, ManipulationList} from '../connectome/Manipulations';

// Labelled conditions of your own: interventions held for the whole trial and, with the connectome
// model, changes to a few live-editable parameters.
export function CustomConditions({
  custom,
  setCustom,
  model,
  dynamics,
  parameters,
  circuit,
  disabled,
  canAdd,
}: {
  custom: CustomCondition[];
  setCustom: (update: (previous: CustomCondition[]) => CustomCondition[]) => void;
  model: NeuralModel;
  dynamics: Dynamics;
  // The configuration's values, shown for parameters a condition leaves unchanged.
  parameters: ConnectomeParameters | undefined;
  circuit: CircuitSummary | null;
  disabled: boolean;
  canAdd: boolean;
}) {
  const update = (index: number, change: (c: CustomCondition) => CustomCondition) =>
    setCustom((previous) => previous.map((c, i) => (i === index ? change(c) : c)));
  const intervene = (index: number, change: (i: Intervention) => Partial<Intervention>) =>
    update(index, (c) => {
      const current = {...noInterventions, ...c.interventions};
      return {...c, interventions: {...current, ...change(current)}};
    });
  return (
    <div className="custom-conditions">
      {custom.map((condition, index) => {
        const interventions = {...noInterventions, ...condition.interventions};
        return (
          <fieldset className="custom-condition" key={index}>
            <legend>Custom condition {index + 1}</legend>
            <div className="custom-heading">
              <label className="field-label">
                Label
                <input
                  value={condition.label}
                  maxLength={LABEL_LIMIT}
                  disabled={disabled}
                  onChange={(e) => update(index, (c) => ({...c, label: e.target.value}))}
                />
              </label>
              <button
                type="button"
                className="icon-button"
                disabled={disabled}
                aria-label={`Remove custom condition ${condition.label || index + 1}`}
                onClick={() => setCustom((previous) => previous.filter((_, i) => i !== index))}
              >
                <Trash2 size={14} />
              </button>
            </div>
            <p className="microcopy">Changes: {customSummary(condition)}.</p>
            <div className="custom-sensors">
              {(['zero_left', 'zero_right'] as const).map((field) => (
                <label key={field} className="check-label">
                  <input
                    type="checkbox"
                    checked={interventions[field]}
                    disabled={disabled}
                    onChange={(e) => intervene(index, () => ({[field]: e.target.checked}))}
                  />
                  {field === 'zero_left' ? 'Left sensor off' : 'Right sensor off'}
                </label>
              ))}
            </div>
            {model === 'engineered' ? (
              <label className="field-label">
                Silence a neural group
                <div className="select-wrap">
                  <select
                    value={interventions.silence}
                    disabled={disabled}
                    onChange={(e) =>
                      intervene(index, () => ({silence: e.target.value as Intervention['silence']}))
                    }
                  >
                    <option value="none">None</option>
                    <option value="sensory">Sensory units</option>
                    <option value="steering">Steering units</option>
                    <option value="descending">Descending units</option>
                    <option value="all">All neural units</option>
                  </select>
                  <ChevronDown size={14} />
                </div>
              </label>
            ) : (
              <>
                <ManipulationEditor
                  circuit={circuit}
                  dynamics={dynamics}
                  interventions={interventions}
                  disabled={disabled || !circuit}
                  onSet={(entry) => intervene(index, (current) => withCellType(current, entry))}
                />
                <ManipulationList
                  interventions={interventions}
                  dynamics={dynamics}
                  disabled={disabled}
                  onRemove={(item) =>
                    intervene(index, (current) => withoutManipulation(current, item))
                  }
                />
                <div className="parameter-fields custom-parameters">
                  {CUSTOM_PARAMETERS.map(([field, label, min, max, step]) => (
                    <label key={field}>
                      {label}
                      <input
                        type="number"
                        min={min}
                        max={max}
                        step={step}
                        disabled={disabled}
                        placeholder={`${parameters?.[field] ?? 0} (unchanged)`}
                        value={condition.connectome_parameters?.[field] ?? ''}
                        onChange={(e) =>
                          update(index, (c) => {
                            const next = {...c.connectome_parameters};
                            if (e.target.value === '') delete next[field];
                            else next[field] = Number(e.target.value);
                            return {
                              ...c,
                              connectome_parameters: Object.keys(next).length ? next : null,
                            };
                          })
                        }
                      />
                    </label>
                  ))}
                </div>
              </>
            )}
          </fieldset>
        );
      })}
      <button
        type="button"
        className="text-button"
        disabled={disabled || !canAdd}
        title={canAdd ? undefined : 'A comparison has at most six conditions.'}
        onClick={() => setCustom((previous) => [...previous, newCustomCondition(previous)])}
      >
        <Plus size={14} />
        Add a custom condition
      </button>
    </div>
  );
}
