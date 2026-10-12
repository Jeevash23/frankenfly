import {ArrowDownToLine, Check, CircleHelp, FlaskConical, Layers3, Unplug, X} from 'lucide-react';
import type {State} from '../types';

export type Exported = {samples: number; download_url: string; path: string};

export function Alerts({
  state,
  connected,
  serverClosed,
  error,
  clearError,
  exported,
  dismissExport,
}: {
  state: State | null;
  connected: boolean;
  serverClosed: boolean;
  error: string | null;
  clearError: () => void;
  exported: Exported | null;
  dismissExport: () => void;
}) {
  return (
    <>
      {serverClosed && (
        <div className="alert export-alert" role="status">
          <Check size={18} />
          <span>
            <strong>DigitalFly is closed.</strong> The Python server and simulation have stopped.
            You can close this tab. Start it again with <code>./scripts/start.sh --open</code>.
          </span>
        </div>
      )}
      {!connected && !serverClosed && (
        <div className="alert connection-alert" role="status">
          <Unplug size={17} />
          <span>
            {state
              ? 'Connection lost. Displaying the last received state; controls resume when the server reconnects.'
              : 'Connecting to the local simulation. The first body initialization can take a few seconds.'}
          </span>
        </div>
      )}
      {(error || state?.error) && (
        <div className="alert error-alert" role="alert">
          <CircleHelp size={18} />
          <span>{error || state?.error}</span>
          {error && (
            <button className="icon-button" onClick={clearError} aria-label="Dismiss command error">
              <X size={16} />
            </button>
          )}
        </div>
      )}
      {state?.config.engine === 'toy' && (
        <div className="alert toy-alert">
          <FlaskConical size={17} />
          <strong>Toy demo: not FlyGym physics or a biological connectome</strong>
        </div>
      )}
      {state?.config.controller === 'baseline' && (
        <div className="alert toy-alert">
          <Layers3 size={17} />
          <span>
            Controller-only baseline · neural activity is computed, but its output is bypassed.
            Motor commands stay at [1, 1].
          </span>
        </div>
      )}
      {exported && (
        <div className="alert export-alert" role="status">
          <Check size={17} />
          <span>
            Run saved locally · {exported.samples} samples, configuration, and input schedule.
          </span>
          <a href={exported.download_url} download>
            Download ZIP <ArrowDownToLine size={14} />
          </a>
          <button
            className="icon-button"
            onClick={dismissExport}
            aria-label="Dismiss export notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </>
  );
}
