import {useState} from 'react';
import {ChevronDown, SlidersHorizontal} from 'lucide-react';
import type {Intervention, InterventionChange, Sample, State} from '../types';
import {fmt} from '../format';
import {useCircuit} from '../connectome/useCircuit';
import '../connectome/connectome.css';
import {Toggle} from './Toggle';

export function activeInterventions(interventions: Intervention | undefined): number {
  if (!interventions) return 0;
  return (
    (interventions.zero_left ? 1 : 0) +
    (interventions.zero_right ? 1 : 0) +
    (interventions.silence !== 'none' ? 1 : 0) +
    ((interventions.silence_dna02 ?? 'none') !== 'none' ? 1 : 0) +
    (interventions.silence_types?.length ?? 0)
  );
}

function CellTypeSilencing({
  state,
  editDisabled,
  intervene,
}: {
  state: State | null;
  editDisabled: boolean;
  intervene: (change: InterventionChange) => void;
}) {
  const {circuit, error} = useCircuit(state);
  const [draft, setDraft] = useState('');
  const silenced = state?.interventions.silence_types ?? [];
  const names = new Set(circuit?.types.map((t) => t.name));
  // Large circuits list only the types nearest the readout; the server checks the rest.
  const complete = !circuit || circuit.types_shown >= circuit.types_total;
  const hasDNa02 = names.has('DNa02');
  const problem =
    draft && complete && !names.has(draft.trim())
      ? 'Not a cell type in this circuit. Pick one from the suggestions.'
      : '';
  const add = () => {
    const name = draft.trim();
    if (!name || (complete && !names.has(name)) || silenced.includes(name)) return;
    intervene((current) => ({
      silence_types: [...(current.silence_types ?? []).filter((t) => t !== name), name],
    }));
    setDraft('');
  };
  return (
    <>
      {hasDNa02 && (
        <label className="field-label">
          Silence DNa02
          <div className="select-wrap">
            <select
              aria-label="Silence DNa02"
              value={state?.interventions.silence_dna02 ?? 'none'}
              disabled={editDisabled}
              onChange={(e) =>
                intervene({silence_dna02: e.target.value as Intervention['silence_dna02']})
              }
            >
              <option value="none">None · both active</option>
              <option value="left">Left DNa02 (L)</option>
              <option value="right">Right DNa02 (R)</option>
              <option value="both">Both DNa02</option>
            </select>
            <ChevronDown size={14} />
          </div>
        </label>
      )}
      <label className="field-label">
        Silence a cell type
        <input
          className="type-input"
          list="connectome-cell-types"
          aria-label="Cell type to silence"
          value={draft}
          disabled={editDisabled || !circuit}
          placeholder={circuit ? 'Name, e.g. DNa03, then Enter' : error || 'Loading cell types…'}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add();
          }}
          onBlur={add}
        />
        <datalist id="connectome-cell-types">
          {circuit?.types.map((t) => (
            <option key={t.name} value={t.name}>
              {t.count} neurons, hop {t.layer}
            </option>
          ))}
        </datalist>
      </label>
      {problem && (
        <p className="microcopy" role="status">
          {problem}
        </p>
      )}
      {silenced.length > 0 && (
        <div className="silenced-types" aria-label="Silenced cell types">
          {silenced.map((type) => (
            <button
              key={type}
              disabled={editDisabled}
              aria-label={`Restore ${type}`}
              onClick={() =>
                intervene((current) => ({
                  silence_types: (current.silence_types ?? []).filter((t) => t !== type),
                }))
              }
            >
              {type} ×
            </button>
          ))}
        </div>
      )}
    </>
  );
}

export function InterventionPanel({
  state,
  editDisabled,
  intervene,
}: {
  state: State | null;
  editDisabled: boolean;
  intervene: (change: InterventionChange) => void;
}) {
  const sample: Sample | undefined = state?.sample ?? undefined;
  const interventions = state?.interventions;
  const count = activeInterventions(interventions);
  return (
    <section className="intervention-panel panel">
      <div className="panel-heading">
        <div>
          <SlidersHorizontal size={16} />
          <h2>Interventions</h2>
        </div>
        <span className={`intervention-count ${count ? 'active' : ''}`}>{count} active</span>
      </div>
      <div className="inspector-body">
        <Toggle
          label="Silence left sensor"
          subtitle="Zero the left input channel"
          checked={interventions?.zero_left ?? false}
          disabled={editDisabled}
          onChange={() => intervene((current) => ({zero_left: !current.zero_left}))}
        />
        <Toggle
          label="Silence right sensor"
          subtitle="Zero the right input channel"
          checked={interventions?.zero_right ?? false}
          disabled={editDisabled}
          onChange={() => intervene((current) => ({zero_right: !current.zero_right}))}
        />
        {state?.config.neural_model === 'connectome' ? (
          <CellTypeSilencing state={state} editDisabled={editDisabled} intervene={intervene} />
        ) : (
          <label className="field-label">
            Silence a neural group
            <div className="select-wrap">
              <select
                aria-label="Silence neural group"
                value={interventions?.silence ?? 'none'}
                disabled={editDisabled}
                onChange={(e) => intervene({silence: e.target.value as Intervention['silence']})}
              >
                <option value="none">None · all groups active</option>
                <option value="sensory">Sensory units</option>
                <option value="steering">Steering units</option>
                <option value="descending">Descending units</option>
                <option value="all">All neural units</option>
              </select>
              <ChevronDown size={14} />
            </div>
          </label>
        )}
        <div className="motor-output">
          <span>
            Motor command <small>L / R</small>
          </span>
          <strong>
            {fmt(sample?.motor[0])}
            <span>/</span>
            {fmt(sample?.motor[1])}
          </strong>
        </div>
        <p className="microcopy">
          {state?.config.controller === 'baseline' ? (
            <>
              Baseline bypasses neural output.
              <br />
              Interventions affect circuit readings only.
            </>
          ) : (
            <>
              Interventions change the computations
              <br />
              that drive movement.
            </>
          )}
        </p>
      </div>
    </section>
  );
}
