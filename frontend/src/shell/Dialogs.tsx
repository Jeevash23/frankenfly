import {useEffect, useRef} from 'react';
import {ArrowDownToLine, ArrowRight, X} from 'lucide-react';
import type {State} from '../types';

export function ModelDialog({
  state,
  version,
  close,
}: {
  state: State | null;
  version: string | null;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const sensor = state?.config.sensor_model ?? 'geometric';
  const spiking =
    state?.config.neural_model === 'connectome' &&
    state.config.connectome_parameters.dynamics === 'spiking';
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
      <span className="eyebrow">MODEL NOTES{version ? ` / VERSION ${version}` : ''}</span>
      <h2>An inspectable research loop.</h2>
      <p>
        A physics-simulated female fly body (NeuroMechFly) steered by one of two neural models: an
        engineered six-unit controller, or a circuit wired from the FlyWire v783 connectome, with
        rate units or the spiking neurons of Shiu et al. 2024. Two circuits ship with the app: 3,000
        neurons around the DNa02 steering neurons, and 4,000 neurons around DNa01, DNa02 and DNp09;
        you can build others. The fly senses its target by geometric bearing, through rendered
        compound eyes or, with the optional install, through FlyVis eyes: a connectome-constrained
        optic-lobe network whose cell types drive the circuit's visual neurons. Published male and
        female anatomy is available in a separate explorer.
      </p>
      <div className="model-chain">
        <span>World</span>
        <ArrowRight />
        <span>{sensor === 'flyvis' ? 'FlyVis' : 'Sensors'}</span>
        <ArrowRight />
        <span>{spiking ? 'Spikes' : 'Rates'}</span>
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
      {state?.config.neural_model === 'connectome' ? (
        <>
          <p>
            {sensor === 'flyvis'
              ? "FlyVis eyes run the rendered eye images through FlyVis (Lappalainen et al. 2024), a connectome-constrained optic-lobe network stepped every 10 ms. Each FlyVis cell type's strongest response in each eye drives the visual projection neurons of the"
              : sensor === 'vision'
                ? "The compound-eye sensor pools rendered eye pixels into one engineered green-contrast value per side. Each side's value drives the input neurons on that side of the"
                : "The geometric sensor turns the target's bearing and distance into one value per side. Each side's value drives the input neurons on that side of the"}{' '}
            FlyWire v783 circuit <b>{state.config.connectome_parameters.circuit}</b>
            {sensor === 'flyvis' ? ', in proportion to their FlyWire synapses from that type' : ''}
            {state.connectome
              ? ` (readout: ${state.connectome.readout_types.join(', ')})`
              : ''}.{' '}
            {spiking
              ? `Leaky integrate-and-fire neurons with the constants of Shiu et al. 2024 update every 0.1 ms; ${sensor === 'flyvis' ? 'their visual input sets' : 'sensor values set'} Poisson input rates.`
              : 'Leaky rate units update every 1 ms.'}{' '}
            The right − left difference of the readout cell types, summed, sets the turn; forward
            drive is a tonic term. Physics advances every 0.1 ms; a Step advances 10 ms.
          </p>
          <p>
            Which neurons connect, and with how many synapses, is data-derived. Each connection's
            sign is assumed from its predicted transmitter. The gains, the sensor-to-neuron input
            and the readout are engineered. This is a connectome-constrained model, not an uploaded
            brain and not biologically validated.
            {sensor === 'flyvis'
              ? ' FlyVis is task-trained on FIB-25/FIB-19 connectivity; its link to these FlyWire neurons is by synapse counts with engineered pooling, not fitted to recordings.'
              : ''}
          </p>
          <div className="model-notice">
            Connectome-constrained circuit · data-derived wiring, assumed signs, engineered input
            and readout
          </div>
        </>
      ) : (
        <>
          <p>
            The selected sensor uses geometric target bearing or rendered compound-eye pixels. Six
            leaky rate units update every 1 ms. Their left/right outputs drive the upstream hybrid
            walking controller. Physics advances every 0.1 ms; a Step advances 10 ms.
          </p>
          <p>
            The neural rates and weights are engineered. The female-derived body has actual joint
            and contact physics. The anatomical explorer retains real neuron identities and source
            coordinates; those skeletons do not supply this controller's dynamics. A separate male
            biomechanical model is not included.
          </p>
          <div className="model-notice">No biological connectome loaded</div>
        </>
      )}
      <button className="primary-button" onClick={close}>
        Back to the experiment <ArrowRight size={15} />
      </button>
    </dialog>
  );
}

export function QuitDialog({
  close,
  quit,
  quitting,
  error,
  hasSample,
}: {
  close: () => void;
  quit: (save: boolean) => Promise<void>;
  quitting: boolean;
  // Why the last attempt to quit failed; shown here because the modal hides the page's alerts.
  error: string | null;
  hasSample: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  // While quitting the buttons are aria-disabled, not disabled, so focus stays in the dialog.
  const act = (action: () => void) => () => {
    if (!quitting) action();
  };
  return (
    <dialog
      ref={ref}
      className="model-dialog quit-dialog"
      aria-busy={quitting}
      onCancel={(e) => {
        if (quitting) e.preventDefault();
        else close();
      }}
    >
      <span className="eyebrow">CLOSE DIGITALFLY</span>
      <h2>Finish this session.</h2>
      <p>
        This stops the simulation and its local server. Remaining comparison trials will stop too.
        Saved runs stay on this computer.
      </p>
      {error && (
        <div className="alert error-alert" role="alert">
          <span>
            <strong>DigitalFly is still running.</strong> {error}
          </span>
        </div>
      )}
      <button
        className="primary-button"
        disabled={!hasSample}
        aria-disabled={quitting}
        onClick={act(() => void quit(true))}
      >
        <ArrowDownToLine size={15} />
        {quitting ? 'Closing…' : 'Save current run & quit'}
      </button>
      <div className="quit-dialog-actions">
        <button
          className="text-button"
          aria-disabled={quitting}
          onClick={act(() => void quit(false))}
        >
          Quit without saving
        </button>
        <button className="secondary-button" aria-disabled={quitting} onClick={act(close)}>
          Keep working
        </button>
      </div>
    </dialog>
  );
}
