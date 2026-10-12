import {useEffect, useRef, useState} from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  ArrowRight,
  Check,
  ChevronDown,
  CircleHelp,
  Crosshair,
  Expand,
  FlaskConical,
  Layers3,
  LoaderCircle,
  MoveUpRight,
  Pause,
  Play,
  Power,
  RotateCcw,
  SkipForward,
  SlidersHorizontal,
  Unplug,
  X,
} from 'lucide-react';
import type {Config, Intervention, Sample, State, Stimulus} from './types';
import {useSimulation} from './useSimulation';
import {targetFromPoint, trace} from './plot';
import {AnatomyPanel, ConnectivityPanel} from './Atlas';
import {BodyMeasurements, CircuitPanel, EyePanel} from './ResearchPanels';
import Experiments from './Experiments';
import './research.css';

const n = (value: number | undefined, digits = 2) =>
  value === undefined ? '—' : value.toFixed(digits);
const rateNames = [
  'Sensory L',
  'Sensory R',
  'Steering L',
  'Steering R',
  'Descending L',
  'Descending R',
];

function FlyMark({small = false}: {small?: boolean}) {
  return (
    <svg
      viewBox="0 0 40 40"
      width={small ? 20 : 31}
      height={small ? 20 : 31}
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M20 9v24M20 15C7 0 2 18 18 23M20 15C33 0 38 18 22 23M15 22l-7 8m17-8 7 8M15 27l-4 7m14-7 4 7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <ellipse cx="20" cy="24" rx="3.5" ry="8" fill="currentColor" />
      <circle cx="20" cy="10" r="3" fill="currentColor" />
    </svg>
  );
}

function Arena({
  state,
  compact = false,
  onTarget,
  disabled,
}: {
  state: State | null;
  compact?: boolean;
  onTarget: (target: Partial<Stimulus>) => void;
  disabled: boolean;
}) {
  const pose = state?.sample?.pose;
  const target = state?.config.stimulus;
  const extent = 40;
  const point = (x: number, y: number) => [150 + (x / extent) * 150, 150 - (y / extent) * 150];
  const [tx, ty] = target ? point(target.x, target.y) : [150, 150];
  const [fx, fy] = pose ? point(pose.x, pose.y) : [150, 150];
  return (
    <svg
      className={`arena ${compact ? 'compact' : ''}`}
      viewBox="0 0 300 300"
      role="img"
      aria-label="Arena map: click to move stimulus, coordinates in millimeters"
      onPointerDown={(event) => {
        if (disabled) return;
        // SVG's square is letterboxed in the element; use its actual square drawing area.
        const r = event.currentTarget.getBoundingClientRect();
        const side = Math.min(r.width, r.height);
        onTarget(
          targetFromPoint(
            event.clientX,
            event.clientY,
            {
              left: r.left + (r.width - side) / 2,
              top: r.top + (r.height - side) / 2,
              width: side,
              height: side,
            },
            extent,
          ),
        );
      }}
    >
      <defs>
        <pattern
          id={compact ? 'grid-mini' : 'grid-main'}
          width="37.5"
          height="37.5"
          patternUnits="userSpaceOnUse"
        >
          <path d="M37.5 0H0V37.5" fill="none" stroke="#dedfd5" strokeWidth=".7" />
        </pattern>
      </defs>
      <rect width="300" height="300" fill={`url(#${compact ? 'grid-mini' : 'grid-main'})`} />
      <path d="M150 0V300M0 150H300" stroke="#b9c0b5" strokeWidth=".7" />
      <text x="286" y="143" className="map-axis">
        x
      </text>
      <text x="156" y="13" className="map-axis">
        y
      </text>
      <polyline
        points={state?.trail.map((p) => point(p[0], p[1]).join(',')).join(' ')}
        fill="none"
        stroke="#496b57"
        strokeOpacity=".5"
        strokeWidth="1.2"
      />
      {pose && target && (
        <line
          x1={fx}
          y1={fy}
          x2={tx}
          y2={ty}
          stroke="#aaa67e"
          strokeDasharray="3 4"
          strokeWidth=".8"
        />
      )}
      {target && (
        <g transform={`translate(${tx},${ty})`}>
          <circle r="14" fill="#bd9956" opacity=".1" />
          <circle r="7" fill="none" stroke="#af8645" strokeWidth="1" />
          <circle r="2" fill="#af8645" />
          <path d="M-11 0h5M6 0h5M0-11v5M0 6v5" stroke="#af8645" strokeWidth=".8" />
        </g>
      )}
      {pose && (
        <g transform={`translate(${fx},${fy}) rotate(${(-pose.yaw * 180) / Math.PI})`}>
          <path d="M8 0L-5-4L-2 0L-5 4Z" fill="#284b39" />
          {!compact &&
            pose.legs.map((leg, i) => (
              <polyline
                key={i}
                points={leg
                  .map((p) => {
                    // Convert measured world joint positions into the glyph's local frame.
                    const dx = ((p[0] - pose.x) / extent) * 150;
                    const dy = (-(p[1] - pose.y) / extent) * 150;
                    return `${dx * Math.cos(pose.yaw) - dy * Math.sin(pose.yaw)},${dx * Math.sin(pose.yaw) + dy * Math.cos(pose.yaw)}`;
                  })
                  .join(' ')}
                fill="none"
                stroke="#284b39"
                strokeWidth=".8"
              />
            ))}
        </g>
      )}
      <text x="8" y="291" className="map-axis">
        −40
      </text>
      <text x="272" y="291" className="map-axis">
        40 mm
      </text>
    </svg>
  );
}

function Toggle({
  label,
  subtitle,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  subtitle: string;
  checked: boolean;
  onChange: () => void;
  disabled: boolean;
}) {
  return (
    <label className="toggle-row">
      <span>
        <span className="toggle-label">{label}</span>
        <small>{subtitle}</small>
      </span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span className="toggle-track" />
    </label>
  );
}

function Signals({state}: {state: State | null}) {
  const [group, setGroup] = useState<'descending' | 'sensory' | 'steering'>('descending');
  const index = {sensory: 0, steering: 2, descending: 4}[group];
  const history = state?.history ?? [];
  const end = Math.max(2, state?.sample?.t ?? 0);
  const start = Math.max(0, end - 4);
  return (
    <section className="signals panel" aria-label="Computed neural activity">
      <div className="panel-heading">
        <div>
          <span className="section-no">02</span>
          <h2>Inside the loop</h2>
          <span className="subtle-label">Computed activity</span>
        </div>
        <div className="select-wrap small-select">
          <select
            aria-label="Neural trace group"
            value={group}
            onChange={(e) => setGroup(e.target.value as typeof group)}
          >
            <option value="descending">Descending units</option>
            <option value="sensory">Sensory units</option>
            <option value="steering">Steering units</option>
          </select>
          <ChevronDown size={13} />
        </div>
      </div>
      <div className="signal-body">
        <div className="trace-area">
          <div className="trace-legend">
            <span>
              <i className="legend-dot left" />
              Left
            </span>
            <span>
              <i className="legend-dot right" />
              Right
            </span>
            <span className="unit">Rate · a.u.</span>
          </div>
          <div className="chart">
            <div className="y-labels">
              <span>1.4</span>
              <span>0.7</span>
              <span>0.0</span>
            </div>
            <svg
              viewBox="0 0 600 110"
              preserveAspectRatio="none"
              role="img"
              aria-label={`${group} neural rates over simulated time`}
            >
              <path
                d="M0 1H600M0 55H600M0 109H600"
                stroke="#e3e5de"
                strokeWidth="1"
                strokeDasharray="3 4"
              />
              <path
                d={trace(history, (s) => s.rates[index])}
                fill="none"
                stroke="#416a55"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
              <path
                d={trace(history, (s) => s.rates[index + 1])}
                fill="none"
                stroke="#bc9452"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          </div>
          <div className="x-labels">
            <span>{n(start, 1)}</span>
            <span>{n((start + end) / 2, 1)}</span>
            <span>{n(end, 1)} s</span>
          </div>
        </div>
        <div className="unit-grid">
          {rateNames.map((label, i) => (
            <div className="rate-cell" key={label}>
              <div>
                <span>{label}</span>
                <b>{n(state?.sample?.rates[i])}</b>
              </div>
              <div className="rate-track">
                <span
                  style={{
                    width: `${(state?.sample?.rates[i] ?? 0) * 100}%`,
                    background: i % 2 ? '#bc9452' : '#416a55',
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="panel-footnote">
        <span className="tiny-dot" />6 engineered rate units · hand-chosen weights
        <span>Simulation time, not wall time</span>
      </div>
    </section>
  );
}

function ModelDialog({state, close}: {state: State | null; close: () => void}) {
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

export default function App() {
  const [serverClosed, setServerClosed] = useState(false);
  const {state, connected, busy, error, command, clearError} = useSimulation(!serverClosed);
  const [page, setPage] = useState<'workbench' | 'atlas' | 'experiments'>('workbench');
  const [atlasView, setAtlasView] = useState<'anatomy' | 'circuit' | 'connectivity'>('anatomy');
  const [quitOpen, setQuitOpen] = useState(false);
  const [view, setView] = useState<'specimen' | 'arena'>('specimen');
  const [modelNotes, setModelNotes] = useState(false);
  const [seed, setSeed] = useState(42);
  const [draft, setDraft] = useState({x: '12', y: '8'});
  const [exported, setExported] = useState<{
    samples: number;
    download_url: string;
    path: string;
  } | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const disabled = !connected || busy || serverClosed || state?.status === 'initializing';
  const batchActive = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const editDisabled = disabled || batchActive;
  const valid = !!state?.sample && state?.status !== 'error';
  const running = state?.status === 'running';
  const sample: Sample | undefined = state?.sample ?? undefined;
  const stimulus = state?.config.stimulus;
  const interventions = state?.interventions;
  const effectiveView = view === 'specimen' && state?.rendering ? 'specimen' : 'arena';

  useEffect(() => {
    setExported(null);
  }, [state?.run_id]);
  useEffect(() => {
    if (stimulus) setDraft({x: String(stimulus.x), y: String(stimulus.y)});
  }, [stimulus?.x, stimulus?.y]);
  useEffect(() => {
    if (state?.config.seed !== undefined) setSeed(state.config.seed);
  }, [state?.config.seed]);
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (
        e.code !== 'Space' ||
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLSelectElement ||
        e.target instanceof HTMLButtonElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target instanceof Element && e.target.closest('[role="button"]')) ||
        modelNotes ||
        quitOpen ||
        page !== 'workbench'
      )
        return;
      e.preventDefault();
      if (!disabled && valid) void command(running ? 'pause' : 'run');
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [disabled, running, valid, command, modelNotes, quitOpen, page]);

  const moveTarget = (values: Partial<Stimulus>) => {
    if (stimulus) void command('stimulus', {...stimulus, ...values});
  };
  const intervene = (value: Partial<Intervention>) => {
    if (interventions) void command('interventions', {...interventions, ...value});
  };
  const reset = (override: Partial<Config> = {}) => {
    if (!state) return;
    setExported(null);
    void command('reset', {
      ...state.config,
      seed,
      initial_interventions: {zero_left: false, zero_right: false, silence: 'none'},
      stimulus: {x: 12, y: 8, intensity: 1},
      ...override,
    });
  };
  const exportRun = async () => {
    const data = await command('export');
    if (data) setExported(data);
  };

  const quit = async (save: boolean) => {
    if (!state) return;
    if (running && !(await command('pause'))) return;
    if (save && !(await command('export'))) return;
    const result = await command('shutdown', {instance_id: state.instance_id});
    if (result) {
      setServerClosed(true);
      setQuitOpen(false);
    }
  };

  return (
    <>
      <header className="app-header">
        <a
          href="#"
          onClick={() => setPage('workbench')}
          className="brand"
          aria-label="DigitalFly home"
        >
          <span className="brand-mark">
            <FlyMark />
          </span>
          <span>
            DigitalFly<span className="brand-period">.</span>
          </span>
        </a>
        <nav aria-label="Main navigation">
          {(['workbench', 'atlas', 'experiments'] as const).map((p) => (
            <button key={p} className={page === p ? 'nav-active' : ''} onClick={() => setPage(p)}>
              {p === 'atlas' ? 'Neural atlas' : p === 'experiments' ? 'Experiments' : 'Workbench'}
            </button>
          ))}
        </nav>
        <div className="header-right">
          <span className={`connection-dot ${connected && !serverClosed ? 'online' : ''}`} />
          <span>
            {serverClosed
              ? 'Server stopped'
              : connected
                ? 'Local connection'
                : 'Connecting locally'}
          </span>
          <span className="version">v0.2</span>
          <button
            className="icon-button"
            onClick={() => setModelNotes(true)}
            aria-label="Open model notes"
          >
            <CircleHelp size={16} />
          </button>
          <button className="quit-button" disabled={disabled} onClick={() => setQuitOpen(true)}>
            <Power size={14} />
            Quit
          </button>
        </div>
      </header>
      <main>
        <section className="workspace-heading">
          <div>
            <div className="eyebrow">
              <span className="tiny-line" /> EMBODIED INTELLIGENCE / LOCAL LAB
            </div>
            <h1>
              {page === 'workbench'
                ? 'The sensorimotor workbench'
                : page === 'atlas'
                  ? 'Structure, signals & behavior'
                  : 'The experiment notebook'}
              <span>.</span>
            </h1>
            <p>
              {page === 'workbench'
                ? 'Change the world. Observe the response. Follow the loop.'
                : page === 'atlas'
                  ? 'Anatomy from published data. Activity from an explicit model.'
                  : 'Design a protocol. Compare conditions. Keep the evidence.'}
            </p>
          </div>
          <div className="experiment-label">
            <span className="eyebrow">
              RUN{' '}
              {state?.run_id && state.run_id !== 'initializing'
                ? state.run_id.slice(-8).toUpperCase()
                : 'INITIALIZING'}
            </span>
            <span>
              <i />
              Female-derived body · single animal
            </span>
            <small>
              {state?.config.sensor_model === 'vision' ? 'Compound-eye input' : 'Geometric input'} ·
              engineered neural controller
            </small>
          </div>
        </section>
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
              <button
                className="icon-button"
                onClick={clearError}
                aria-label="Dismiss command error"
              >
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
              onClick={() => setExported(null)}
              aria-label="Dismiss export notification"
            >
              <X size={16} />
            </button>
          </div>
        )}
        {page === 'atlas' && (
          <>
            <div className="research-tabs" aria-label="Neural explorer view">
              {(['anatomy', 'circuit', 'connectivity'] as const).map((view) => (
                <button
                  key={view}
                  className={atlasView === view ? 'selected' : ''}
                  onClick={() => setAtlasView(view)}
                >
                  {view === 'anatomy'
                    ? 'Male & female anatomy'
                    : view === 'circuit'
                      ? 'Live circuit'
                      : 'Imported connectivity'}
                </button>
              ))}
            </div>
            {atlasView === 'anatomy' ? (
              <AnatomyPanel />
            ) : atlasView === 'circuit' ? (
              <CircuitPanel state={state} command={command} disabled={disabled} />
            ) : (
              <ConnectivityPanel command={command} disabled={disabled} />
            )}
          </>
        )}
        {page === 'experiments' && (
          <Experiments
            state={state}
            command={command}
            disabled={disabled}
            onLoaded={() => setPage('workbench')}
          />
        )}
        {page === 'workbench' && (
          <>
            {state?.config.protocol && (
              <div className="protocol-banner">
                <span>
                  <FlaskConical size={15} />
                  <strong>{state.config.protocol.name}</strong> · stops at{' '}
                  {n(state.config.protocol.duration_steps / 100)} s
                </span>
                <button onClick={() => setPage('experiments')}>
                  {batchActive
                    ? `Comparison trial ${state.batch?.current}/${state.batch?.total}`
                    : 'Edit protocol'}{' '}
                  <ArrowRight size={13} />
                </button>
              </div>
            )}
            <div className="workspace-grid">
              <div className="main-column">
                <section className="world-panel panel">
                  <div className="panel-heading">
                    <div>
                      <span className="section-no">01</span>
                      <h2>The world</h2>
                    </div>
                    <div className="segmented" aria-label="World view">
                      <button
                        className={effectiveView === 'specimen' ? 'selected' : ''}
                        disabled={!state?.rendering}
                        onClick={() => setView('specimen')}
                      >
                        Specimen
                      </button>
                      <button
                        className={effectiveView === 'arena' ? 'selected' : ''}
                        onClick={() => setView('arena')}
                      >
                        Arena
                      </button>
                    </div>
                  </div>
                  <div className={`world-canvas ${effectiveView}`} ref={viewportRef}>
                    {effectiveView === 'specimen' ? (
                      <img
                        className="physics-frame"
                        src={`/api/frame?v=${state?.frame_revision}`}
                        alt="Live MuJoCo rendering of the simulated NeuroMechFly body"
                      />
                    ) : (
                      <Arena state={state} disabled={editDisabled} onTarget={moveTarget} />
                    )}
                    <div className="viewport-top">
                      <span className="viewport-label">
                        <i className={running ? 'running-dot' : ''} />
                        {!state ? 'INITIALIZING' : state.status.toUpperCase()}
                      </span>
                      <span className="viewport-label">
                        {effectiveView === 'specimen'
                          ? 'MUJOCO / TRACKING CAMERA'
                          : 'POSE SCHEMATIC / TOP VIEW'}
                      </span>
                    </div>
                    {!state?.sample && (
                      <div className="viewport-loading">
                        <LoaderCircle className="spin" size={22} />
                        <span>
                          {state?.error
                            ? 'Body unavailable · see the error above'
                            : 'Preparing the specimen'}
                        </span>
                      </div>
                    )}
                    <div className="viewport-bottom">
                      <div className="specimen-caption">
                        <span>
                          {state?.config.engine === 'toy'
                            ? 'Kinematic demonstration'
                            : 'Drosophila melanogaster'}
                        </span>
                        <small>
                          {effectiveView === 'specimen'
                            ? 'NeuroMechFly body · actual physics render'
                            : 'Measured position · click the map to place a target'}
                        </small>
                      </div>
                      <button
                        className="viewport-expand"
                        title="Expand world view"
                        aria-label="Expand world view"
                        onClick={() => {
                          if (!document.fullscreenElement)
                            void viewportRef.current?.requestFullscreen();
                          else void document.exitFullscreen();
                        }}
                      >
                        <Expand size={16} />
                      </button>
                    </div>
                  </div>
                  {state?.render_error && (
                    <div className="render-note" role="status">
                      {state.render_error}
                    </div>
                  )}
                  <div className="transport">
                    <div className="playback">
                      <button
                        className="primary-button run-button"
                        disabled={disabled || !valid || !!state?.metrics.protocol_complete}
                        onClick={() => void command(running ? 'pause' : 'run')}
                      >
                        {busy ? (
                          <LoaderCircle size={16} className="spin" />
                        ) : running ? (
                          <Pause size={15} fill="currentColor" />
                        ) : (
                          <Play size={15} fill="currentColor" />
                        )}
                        {running ? 'Pause' : 'Run simulation'}
                        <kbd>␣</kbd>
                      </button>
                      <button
                        className="secondary-button step-button"
                        disabled={
                          editDisabled || !valid || running || !!state?.metrics.protocol_complete
                        }
                        title="Advance one 10 ms control interval"
                        onClick={() => void command('step')}
                      >
                        <SkipForward size={16} />
                        Step
                      </button>
                      <button
                        className="icon-button reset-button"
                        disabled={editDisabled}
                        title="Reset body, clock, circuit, and target to defaults"
                        aria-label="Reset experiment"
                        onClick={() => reset()}
                      >
                        <RotateCcw size={16} />
                      </button>
                    </div>
                    <div className="transport-options">
                      <label className="seed-label">
                        Seed
                        <input
                          aria-label="Random seed"
                          type="number"
                          min="0"
                          max="2147483647"
                          value={seed}
                          disabled={editDisabled || running}
                          onChange={(e) => {
                            const v = Number(e.target.value);
                            if (Number.isInteger(v) && v >= 0 && v <= 2147483647) setSeed(v);
                          }}
                          title="Applied on Reset"
                        />
                      </label>
                      <div className="select-wrap speed-select">
                        <select
                          aria-label="Requested simulation speed"
                          disabled={editDisabled}
                          value={state?.config.speed ?? 0.25}
                          onChange={(e) => void command('speed', {speed: Number(e.target.value)})}
                        >
                          {[0.05, 0.1, 0.25, 0.5, 1, 2].map((speed) => (
                            <option key={speed} value={speed}>
                              {speed}× speed
                            </option>
                          ))}
                        </select>
                        <ChevronDown size={12} />
                      </div>
                    </div>
                  </div>
                  <div className="telemetry-strip">
                    <div>
                      <span>Simulated time</span>
                      <strong>
                        {n(sample?.t)}
                        <small>s</small>
                      </strong>
                    </div>
                    <div>
                      <span>Body speed</span>
                      <strong>
                        {n(sample?.pose.velocity)}
                        <small>mm/s</small>
                      </strong>
                    </div>
                    <div>
                      <span>Real-time factor</span>
                      <strong>
                        {n(state?.real_time_factor)}
                        <small>×</small>
                      </strong>
                    </div>
                    <div>
                      <span>Active wall time</span>
                      <strong>
                        {n(state?.wall_s, 1)}
                        <small>s</small>
                      </strong>
                    </div>
                  </div>
                </section>
                <Signals state={state} />
                <EyePanel state={state} />
                <BodyMeasurements state={state} />
                <section className="loop-strip" aria-label="Model provenance">
                  <div>
                    <Layers3 size={16} />
                    <strong>One continuous loop</strong>
                  </div>
                  <span>World</span>
                  <ArrowRight size={13} />
                  <span>
                    {state?.config.sensor_model === 'vision'
                      ? 'Compound eyes'
                      : 'Geometric sensors'}
                  </span>
                  <ArrowRight size={13} />
                  <span>6 rate units</span>
                  <ArrowRight size={13} />
                  <span>{state?.config.engine === 'toy' ? 'Kinematics' : 'FlyGym body'}</span>
                  <button onClick={() => setModelNotes(true)} aria-label="Inspect model provenance">
                    <ArrowUpRight size={17} />
                  </button>
                </section>
              </div>
              <aside className="inspector">
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
                          onChange={(e) =>
                            reset({sensor_model: e.target.value as Config['sensor_model']})
                          }
                        >
                          <option value="geometric">Geometric bearing</option>
                          <option value="vision" disabled={state?.config.engine !== 'flygym'}>
                            Rendered compound eyes
                          </option>
                        </select>
                        <ChevronDown size={14} />
                      </div>
                    </label>
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
                        {n(stimulus?.intensity, 1)}
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
                        <b>{n(sample?.sensors.left, 3)}</b>
                      </div>
                      <div>
                        <span>
                          <i className="legend-dot right" />
                          Right sensor
                        </span>
                        <b>{n(sample?.sensors.right, 3)}</b>
                      </div>
                    </div>
                    <p className="microcopy">
                      {state?.config.sensor_model === 'vision'
                        ? 'Green contrast from rendered eye images. Sensor selection starts a fresh run.'
                        : 'Bearing + distance approximation. Select compound eyes for rendered visual input.'}
                    </p>
                  </div>
                </section>
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
                          onChange={(e) =>
                            intervene({silence: e.target.value as Intervention['silence']})
                          }
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
                        {n(sample?.motor[0])}
                        <span>/</span>
                        {n(sample?.motor[1])}
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
                <button
                  className="export-button"
                  disabled={disabled || !state?.sample}
                  onClick={() => void exportRun()}
                >
                  <ArrowDownToLine size={16} />
                  <span>
                    Export this run<small>Telemetry, configuration & events</small>
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              </aside>
            </div>
            <section className="session-section" id="session-log">
              <div className="session-heading">
                <div>
                  <span className="eyebrow">EXPERIMENT RECORD</span>
                  <h2>Session log</h2>
                </div>
                <span>
                  {state?.recording_samples ?? 0} / {state?.recording_limit ?? 30000} samples
                  retained
                </span>
              </div>
              <div className="session-grid">
                <div className="event-list" aria-label="Session events">
                  {state?.events.length ? (
                    [...state.events]
                      .reverse()
                      .slice(0, 6)
                      .map((event) => (
                        <div className="event-row" key={`${state.run_id}-${event.seq}`}>
                          <time>{n(event.t, 3)} s</time>
                          <span className={`event-dot ${event.kind === 'error' ? 'error' : ''}`} />
                          <span>{event.message}</span>
                          <small>STEP {String(event.step).padStart(4, '0')}</small>
                        </div>
                      ))
                  ) : (
                    <p className="microcopy">
                      Events appear here when the local experiment is ready.
                    </p>
                  )}
                </div>
                <div className="configuration">
                  <label className="field-label">
                    Body engine
                    <div className="select-wrap">
                      <select
                        aria-label="Body engine"
                        disabled={editDisabled || running}
                        value={state?.config.engine ?? 'flygym'}
                        onChange={(e) =>
                          reset({
                            engine: e.target.value as Config['engine'],
                            sensor_model:
                              e.target.value === 'toy'
                                ? 'geometric'
                                : (state?.config.sensor_model ?? 'geometric'),
                          })
                        }
                      >
                        <option value="flygym">FlyGym · real physics</option>
                        <option value="toy">Toy demo · kinematic</option>
                      </select>
                      <ChevronDown size={14} />
                    </div>
                  </label>
                  <label className="field-label">
                    Control mode
                    <div className="select-wrap">
                      <select
                        aria-label="Control mode"
                        disabled={editDisabled || running}
                        value={state?.config.controller ?? 'neural'}
                        onChange={(e) =>
                          reset({controller: e.target.value as Config['controller']})
                        }
                      >
                        <option value="neural">Engineered neural loop</option>
                        <option value="baseline">Controller-only baseline</option>
                      </select>
                      <ChevronDown size={14} />
                    </div>
                  </label>
                  <p className="microcopy">Changing either starts a fresh experiment.</p>
                </div>
              </div>
            </section>
          </>
        )}
        <footer>
          <div>
            <FlyMark small />
            <span>No biological connectome loaded into the walking controller</span>
            <button onClick={() => setModelNotes(true)}>
              Model & sources <MoveUpRight size={12} />
            </button>
          </div>
          <span>
            Local by design<span className="footer-dot">·</span>
            {n(state?.memory_mb, 0)} MB<span className="footer-dot">·</span>All calculations in
            Python
          </span>
        </footer>
      </main>
      {modelNotes && <ModelDialog state={state} close={() => setModelNotes(false)} />}
      {quitOpen && (
        <QuitDialog
          close={() => setQuitOpen(false)}
          quit={quit}
          busy={busy}
          hasSample={!!state?.sample}
        />
      )}
    </>
  );
}

function QuitDialog({
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
