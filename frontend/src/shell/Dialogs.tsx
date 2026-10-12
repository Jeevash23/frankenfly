import {useEffect, useRef} from 'react';
import {ArrowDownToLine, ArrowRight, X} from 'lucide-react';
import type {State} from '../types';

export function ModelDialog({state, close}: {state: State | null; close: () => void}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="model-dialog"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <button className="icon-button dialog-close" onClick={close} aria-label="Close model notes">
        <X size={20} />
      </button>
      <span className="eyebrow">MODEL NOTES / VERSION 0.2</span>
      <h2>An inspectable research loop.</h2>
      <p>
        Real biomechanics, optional compound-eye input, and an engineered neural controller.
        Published male and female anatomy is available in a separate explorer.
      </p>
      <div className="model-chain">
        <span>World</span>
        <ArrowRight />
        <span>Sensors</span>
        <ArrowRight />
        <span>Rates</span>
        <ArrowRight />
        <span>Body</span>
      </div>
      <dl>
        {Object.entries(state?.provenance ?? {})
          .filter(([key]) => key !== 'viewport')
          .map(([key, value]) => (
            <div key={key}>
              <dt>{key.replaceAll('_', ' ')}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
      <h3>What is actually computed?</h3>
      <p>
        The selected sensor uses geometric target bearing or rendered compound-eye pixels. Six leaky
        rate units update every 1 ms. Their left/right outputs drive the upstream hybrid walking
        controller. Physics advances every 0.1 ms; a Step advances 10 ms.
      </p>
      <p>
        The neural rates and weights are engineered. The female-derived body has actual joint and
        contact physics. The anatomical explorer retains real neuron identities and source
        coordinates; those skeletons do not supply this controller's dynamics. A separate male
        biomechanical model is not included.
      </p>
      <div className="model-notice">No biological connectome loaded</div>
      <button className="primary-button" onClick={close}>
        Back to the experiment <ArrowRight size={15} />
      </button>
    </dialog>
  );
}

export function QuitDialog({
  close,
  quit,
  busy,
  hasSample,
}: {
  close: () => void;
  quit: (save: boolean) => Promise<void>;
  busy: boolean;
  hasSample: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="model-dialog quit-dialog"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else close();
      }}
    >
      <span className="eyebrow">CLOSE DIGITALFLY</span>
      <h2>Finish this session.</h2>
      <p>
        This stops the simulation and its local server. Remaining comparison trials will stop too.
        Saved runs stay on this computer.
      </p>
      <button
        className="primary-button"
        disabled={busy || !hasSample}
        onClick={() => void quit(true)}
      >
        <ArrowDownToLine size={15} />
        Save current run & quit
      </button>
      <div className="quit-dialog-actions">
        <button className="text-button" disabled={busy} onClick={() => void quit(false)}>
          Quit without saving
        </button>
        <button className="secondary-button" disabled={busy} onClick={close}>
          Keep working
        </button>
      </div>
    </dialog>
  );
}
