import {ChevronDown, Crosshair} from 'lucide-react';
import type {Config, Dynamics, NeuralModel, Sample, State, Stimulus} from '../types';
import {configForCircuit, dynamicsNames, modelNames} from '../models';
import {fmt} from '../format';
import {useCircuitList} from '../connectome/useCircuit';
import {Arena} from './Arena';

// Circuit and dynamics of the connectome model. Either change starts a fresh run.
function CircuitSelect({
  state,
  disabled,
  reset,
}: {
  state: State;
  disabled: boolean;
  reset: (override?: Partial<Config>) => void;
}) {
  const {circuits} = useCircuitList();
  const current = state.config.connectome_parameters;
  const usable = circuits.filter((c) => !c.error);
  const listed = usable.some((c) => c.name === current.circuit)
    ? usable
    : [{name: current.circuit}, ...usable];
  const choose = (circuit: string, dynamics: Dynamics) => {
    const next = configForCircuit(state.config, circuit, dynamics);
    reset({neural_model: 'connectome', connectome_parameters: next.connectome_parameters});
  };
  return (
    <>
      <label className="field-label sensory-select">
        Circuit
        <div className="select-wrap">
          <select
            aria-label="Connectome circuit"
            disabled={disabled}
            value={current.circuit}
            onChange={(e) => choose(e.target.value, current.dynamics)}
          >
            {listed.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
                {c.neurons ? ` · ${c.neurons.toLocaleString()} neurons` : ''}
                {c.committed === false ? ' · local' : ''}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </div>
      </label>
      <label className="field-label sensory-select">
        Dynamics
        <div className="select-wrap">
          <select
            aria-label="Connectome dynamics"
            disabled={disabled}
            value={current.dynamics}
            onChange={(e) => choose(current.circuit, e.target.value as Dynamics)}
          >
            {(Object.keys(dynamicsNames) as Dynamics[]).map((d) => (
              <option key={d} value={d}>
                {dynamicsNames[d]}
              </option>
            ))}
          </select>
          <ChevronDown size={14} />
        </div>
      </label>
    </>
  );
}

export type Draft = {x: string; y: string};

export function StimulusPanel({
  state,
  editDisabled,
  running,
  reset,
  moveTarget,
  draft,
  setDraft,
}: {
  state: State | null;
  editDisabled: boolean;
  running: boolean;
  reset: (override?: Partial<Config>) => void;
  moveTarget: (target: Partial<Stimulus>) => void;
  draft: Draft;
  setDraft: (draft: Draft | ((previous: Draft) => Draft)) => void;
}) {
  const sample: Sample | undefined = state?.sample ?? undefined;
  const stimulus = state?.config.stimulus;
  return (
    <section className="stimulus-panel panel">
      <div className="panel-heading">
        <div>
          <Crosshair size={16} />
          <h2>Stimulus</h2>
        </div>
        <span className="mini-badge">
          {state?.config.sensor_model === 'vision' ? 'COMPOUND EYE' : 'GEOMETRIC'}
        </span>
      </div>
      <div className="inspector-body">
        <label className="field-label sensory-select">
          Sensor model
          <div className="select-wrap">
            <select
              aria-label="Sensor model"
              disabled={editDisabled || running}
              value={state?.config.sensor_model ?? 'geometric'}
              onChange={(e) => reset({sensor_model: e.target.value as Config['sensor_model']})}
            >
              <option value="geometric">Geometric bearing</option>
              <option value="vision" disabled={state?.config.engine !== 'flygym'}>
                Rendered compound eyes
              </option>
            </select>
            <ChevronDown size={14} />
          </div>
        </label>
        <label className="field-label sensory-select">
          Neural model
          <div className="select-wrap">
            <select
              aria-label="Neural model"
              disabled={editDisabled || running}
              value={state?.config.neural_model ?? 'engineered'}
              onChange={(e) => reset({neural_model: e.target.value as NeuralModel})}
            >
              {(Object.keys(modelNames) as NeuralModel[]).map((model) => (
                <option key={model} value={model}>
                  {modelNames[model]}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </div>
        </label>
        {state?.config.neural_model === 'connectome' && (
          <CircuitSelect state={state} disabled={editDisabled || running} reset={reset} />
        )}
        <div className="target-map">
          <Arena state={state} compact disabled={editDisabled} onTarget={moveTarget} />
          <span className="map-hint">Click to reposition</span>
          <span className="map-legend">
            <i />
            Target
          </span>
        </div>
        <div className="coordinate-fields">
          {(['x', 'y'] as const).map((axis) => (
            <label key={axis}>
              <span>{axis.toUpperCase()}</span>
              <input
                aria-label={`Target ${axis.toUpperCase()} position`}
                type="number"
                min="-40"
                max="40"
                step="1"
                value={draft[axis]}
                disabled={editDisabled}
                onChange={(e) => setDraft({...draft, [axis]: e.target.value})}
                onBlur={() => {
                  const v = Number(draft[axis]);
                  if (
                    draft[axis] !== '' &&
                    Number.isFinite(v) &&
                    v >= -40 &&
                    v <= 40 &&
                    v !== stimulus?.[axis]
                  )
                    moveTarget({[axis]: v});
                  else if (stimulus)
                    setDraft((prev) => ({...prev, [axis]: String(stimulus[axis])}));
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') e.currentTarget.blur();
                }}
              />
              <small>mm</small>
            </label>
          ))}
        </div>
        <label className="slider-label">
          <span>Intensity</span>
          <b>
            {fmt(stimulus?.intensity, 1)}
            <small>a.u.</small>
          </b>
          <input
            aria-label="Stimulus intensity"
            type="range"
            min="0"
            max="2"
            step=".1"
            value={stimulus?.intensity ?? 1}
            disabled={editDisabled}
            onChange={(e) => moveTarget({intensity: Number(e.target.value)})}
          />
        </label>
        <div className="sensor-readouts">
          <div>
            <span>
              <i className="legend-dot left" />
              Left sensor
            </span>
            <b>{fmt(sample?.sensors.left, 3)}</b>
          </div>
          <div>
            <span>
              <i className="legend-dot right" />
              Right sensor
            </span>
            <b>{fmt(sample?.sensors.right, 3)}</b>
          </div>
        </div>
        <p className="microcopy">
          {state?.config.sensor_model === 'vision'
            ? 'Green contrast from rendered eye images.'
            : 'Bearing + distance approximation. Select compound eyes for rendered visual input.'}{' '}
          Changing the sensor, neural model, circuit or dynamics starts a fresh run.
        </p>
      </div>
    </section>
  );
}
