import {ChevronDown, SlidersHorizontal} from 'lucide-react';
import type {Intervention, Sample, State} from '../types';
import {fmt} from '../format';
import {Toggle} from './Toggle';

export function InterventionPanel({
  state,
  editDisabled,
  intervene,
}: {
  state: State | null;
  editDisabled: boolean;
  intervene: (value: Partial<Intervention>) => void;
}) {
  const sample: Sample | undefined = state?.sample ?? undefined;
  const interventions = state?.interventions;
  return (
    <section className="intervention-panel panel">
      <div className="panel-heading">
        <div>
          <SlidersHorizontal size={16} />
          <h2>Interventions</h2>
        </div>
        <span
          className={`intervention-count ${interventions && (interventions.zero_left || interventions.zero_right || interventions.silence !== 'none') ? 'active' : ''}`}
        >
          {(interventions?.zero_left ? 1 : 0) +
            (interventions?.zero_right ? 1 : 0) +
            (interventions && interventions.silence !== 'none' ? 1 : 0)}{' '}
          active
        </span>
      </div>
      <div className="inspector-body">
        <Toggle
          label="Silence left sensor"
          subtitle="Zero the left input channel"
          checked={interventions?.zero_left ?? false}
          disabled={editDisabled}
          onChange={() => intervene({zero_left: !interventions?.zero_left})}
        />
        <Toggle
          label="Silence right sensor"
          subtitle="Zero the right input channel"
          checked={interventions?.zero_right ?? false}
          disabled={editDisabled}
          onChange={() => intervene({zero_right: !interventions?.zero_right})}
        />
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
