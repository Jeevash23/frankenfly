import {ChevronDown, SlidersHorizontal} from 'lucide-react';
import type {Intervention, InterventionChange, Sample, State} from '../types';
import {fmt} from '../format';
import {activeInterventions, withCellType, withoutManipulation} from '../interventions';
import {clippingNote} from '../models';
import {useCircuit} from '../connectome/useCircuit';
import {CircuitChanged} from '../connectome/CircuitChanged';
import {MANIPULATION_NOTE, ManipulationEditor, ManipulationList} from '../connectome/Manipulations';
import '../connectome/connectome.css';
import {Toggle} from './Toggle';

// Silencing, scaling and activating cell types of the connectome model, on either side or both.
function CellTypeManipulation({
  state,
  editDisabled,
  intervene,
  reset,
}: {
  state: State;
  editDisabled: boolean;
  intervene: (change: InterventionChange) => void;
  reset: () => void;
}) {
  const {circuit, error, changed} = useCircuit(state);
  const dynamics = state.config.connectome_parameters.dynamics;
  return (
    <>
      {changed && <CircuitChanged message={error} reset={reset} disabled={editDisabled} />}
      <ManipulationEditor
        circuit={circuit}
        dynamics={dynamics}
        interventions={state.interventions}
        disabled={editDisabled || !circuit}
        onSet={(entry) => intervene((current) => withCellType(current, entry))}
      />
      {!circuit && error && !changed && <p className="microcopy">{error}</p>}
      <ManipulationList
        interventions={state.interventions}
        dynamics={dynamics}
        counts={state.connectome?.manipulated_neurons}
        disabled={editDisabled}
        onRemove={(item) => intervene((current) => withoutManipulation(current, item))}
      />
      <p className="microcopy manipulation-note">{MANIPULATION_NOTE}</p>
    </>
  );
}

export function InterventionPanel({
  state,
  editDisabled,
  intervene,
  reset,
}: {
  state: State | null;
  editDisabled: boolean;
  intervene: (change: InterventionChange) => void;
  reset: () => void;
}) {
  const sample: Sample | undefined = state?.sample ?? undefined;
  const interventions = state?.interventions;
  const count = activeInterventions(interventions);
  const clipping =
    state?.config.neural_model === 'connectome'
      ? clippingNote(state.connectome?.motor_clipped_fraction)
      : null;
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
          <CellTypeManipulation
            state={state}
            editDisabled={editDisabled}
            intervene={intervene}
            reset={reset}
          />
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
        {clipping && <p className="clipping-note">{clipping}</p>}
        <p className="microcopy">
          {state?.config.controller === 'baseline'
            ? 'Baseline bypasses neural output. Interventions affect circuit readings only.'
            : 'Interventions change the computations that drive movement.'}
        </p>
      </div>
    </section>
  );
}
