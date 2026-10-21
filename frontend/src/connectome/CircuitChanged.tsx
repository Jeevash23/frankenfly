import {RotateCcw, TriangleAlert} from 'lucide-react';

// Shown when the server refuses the circuit summary because the circuit file was rebuilt since the
// run loaded it (HTTP 409): the run keeps its wiring until a Reset loads the new build.
export function CircuitChanged({
  message,
  reset,
  disabled,
}: {
  message: string;
  reset: () => void;
  disabled: boolean;
}) {
  return (
    <div className="alert error-alert circuit-changed" role="alert">
      <TriangleAlert size={17} />
      <span>
        {message ||
          'The circuit file changed since this run loaded it. Reset to load the new build.'}
      </span>
      <button type="button" className="secondary-button" disabled={disabled} onClick={reset}>
        <RotateCcw size={13} />
        Reset
      </button>
    </div>
  );
}
