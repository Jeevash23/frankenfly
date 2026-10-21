import {useEffect, useRef, useState} from 'react';
import {MoveUpRight} from 'lucide-react';
import type {Config, Intervention, InterventionChange, Stimulus, StimulusChange} from './types';
import {useServerVersion, useSimulation} from './useSimulation';
import {fmt} from './format';
import {tabKeys} from './keys';
import {AnatomyPanel, ConnectivityPanel} from './Atlas';
import {CircuitPanel} from './ResearchPanels';
import Experiments from './experiments/Experiments';
import {ConnectomeCircuitView} from './connectome/CircuitView';
import {BuildPanel} from './connectome/BuildPanel';
import {modelPhrases, noInterventions} from './models';
import {AppHeader} from './shell/AppHeader';
import {ATLAS_VIEWS, parseHash, routeHash, type AtlasView, type Page} from './route';
import {Alerts, type Exported} from './shell/Alerts';
import {ModelDialog, QuitDialog} from './shell/Dialogs';
import {ErrorBoundary} from './shell/ErrorBoundary';
import {FlyMark} from './shell/FlyMark';
import {Workbench} from './workbench/Workbench';
import type {WorldView} from './workbench/WorldPanel';
import './research.css';

const atlasNames: Record<AtlasView, string> = {
  anatomy: 'Male & female anatomy',
  circuit: 'Live circuit',
  build: 'Build a circuit',
  connectivity: 'Imported connectivity',
};
const pageNames: Record<Page, string> = {
  workbench: 'Workbench',
  atlas: 'Neural atlas',
  experiments: 'Experiments',
};

export default function App() {
  const [serverClosed, setServerClosed] = useState(false);
  const {state, connected, pending, error, command, inFlight, clearError} =
    useSimulation(!serverClosed);
  const version = useServerVersion(state?.instance_id);
  // The page and atlas tab follow the URL hash, so Back, Forward and reload keep your place.
  const [route, setRoute] = useState(() => parseHash(location.hash));
  const [lastAtlas, setLastAtlas] = useState<AtlasView>(route.atlas ?? 'anatomy');
  const page = route.page;
  const atlasView = route.atlas ?? lastAtlas;
  useEffect(() => {
    const changed = () => setRoute(parseHash(location.hash));
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  useEffect(() => {
    if (route.atlas) setLastAtlas(route.atlas);
  }, [route.atlas]);
  const go = (next: Page, atlas: AtlasView = atlasView) => {
    const hash = routeHash(next, atlas);
    if (location.hash !== hash) location.hash = hash;
    setRoute({page: next, atlas: next === 'atlas' ? atlas : null});
  };
  const setPage = (next: Page) => go(next);
  const setAtlasView = (atlas: AtlasView) => go('atlas', atlas);
  const [quitOpen, setQuitOpen] = useState(false);
  const [quitting, setQuitting] = useState(false);
  const [quitFailed, setQuitFailed] = useState(false);
  const [view, setView] = useState<WorldView>('specimen');
  const [modelNotes, setModelNotes] = useState(false);
  const [seed, setSeed] = useState(42);
  const [draft, setDraft] = useState({x: '12', y: '8'});
  const [exported, setExported] = useState<Exported | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  // Commands no longer disable every control while they run: each control shows its own pending
  // state, and edits made while one is in flight build on what was sent (see inFlight).
  const disabled = !connected || serverClosed || state?.status === 'initializing';
  const batchActive = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const editDisabled = disabled || batchActive;
  const valid = !!state?.sample && state?.status !== 'error';
  const running = state?.status === 'running';
  const transportPending = !!(pending.run || pending.pause);
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
      if (!disabled && valid && !transportPending) void command(running ? 'pause' : 'run');
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [disabled, running, valid, transportPending, command, modelNotes, quitOpen, page]);

  const moveTarget = (change: StimulusChange) => {
    const base = (inFlight('stimulus') as Stimulus | undefined) ?? stimulus;
    if (!base) return Promise.resolve(null);
    return command('stimulus', {
      ...base,
      ...(typeof change === 'function' ? change(base) : change),
    });
  };
  const intervene = (change: InterventionChange) => {
    const base = (inFlight('interventions') as Intervention | undefined) ?? interventions;
    if (!base) return Promise.resolve(null);
    return command('interventions', {
      ...base,
      ...(typeof change === 'function' ? change(base) : change),
    });
  };
  const reset = (override: Partial<Config> = {}) => {
    if (!state) return Promise.resolve(null);
    setExported(null);
    return command('reset', {
      ...((inFlight('reset') as Config | undefined) ?? state.config),
      seed,
      initial_interventions: noInterventions,
      stimulus: {x: 12, y: 8, intensity: 1},
      ...override,
    });
  };
  const exportRun = async (shareSafe: boolean) => {
    const data = await command('export', shareSafe ? {share_safe: true} : {});
    if (data) setExported({...data, share_safe: shareSafe});
  };

  const quit = async (save: boolean) => {
    if (!state || quitting) return;
    setQuitting(true);
    setQuitFailed(false);
    const done =
      (!running || !!(await command('pause'))) &&
      (!save || !!(await command('export'))) &&
      !!(await command('shutdown', {instance_id: state.instance_id}));
    setQuitting(false);
    if (done) {
      setServerClosed(true);
      setQuitOpen(false);
    } else setQuitFailed(true);
  };

  return (
    <>
      <AppHeader
        page={page}
        setPage={setPage}
        connected={connected}
        serverClosed={serverClosed}
        disabled={disabled}
        version={version}
        openModelNotes={() => setModelNotes(true)}
        openQuit={() => {
          setQuitFailed(false);
          setQuitOpen(true);
        }}
      />
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
              {
                {vision: 'Compound-eye input', flyvis: 'FlyVis eyes', geometric: 'Geometric input'}[
                  state?.config.sensor_model ?? 'geometric'
                ]
              }{' '}
              · {modelPhrases[state?.config.neural_model ?? 'engineered']}
            </small>
          </div>
        </section>
        <Alerts
          state={state}
          connected={connected}
          serverClosed={serverClosed}
          error={error}
          clearError={clearError}
          exported={exported}
          dismissExport={() => setExported(null)}
        />
        <div role="tabpanel" id="page-panel" aria-labelledby={`page-tab-${page}`}>
          {page === 'atlas' && (
            <>
              <div
                className="research-tabs"
                role="tablist"
                aria-label="Neural explorer view"
                onKeyDown={tabKeys(ATLAS_VIEWS, atlasView, setAtlasView)}
              >
                {ATLAS_VIEWS.map((v) => (
                  <button
                    key={v}
                    id={`atlas-tab-${v}`}
                    role="tab"
                    data-tab={v}
                    aria-selected={atlasView === v}
                    aria-controls="atlas-panel"
                    tabIndex={atlasView === v ? 0 : -1}
                    className={atlasView === v ? 'selected' : ''}
                    onClick={() => setAtlasView(v)}
                  >
                    {atlasNames[v]}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id="atlas-panel" aria-labelledby={`atlas-tab-${atlasView}`}>
                <ErrorBoundary key={atlasView} name={atlasNames[atlasView]}>
                  {atlasView === 'anatomy' ? (
                    <AnatomyPanel state={state} />
                  ) : atlasView === 'circuit' ? (
                    state?.config.neural_model === 'connectome' ? (
                      <ConnectomeCircuitView
                        state={state}
                        command={command}
                        intervene={intervene}
                        reset={reset}
                        disabled={disabled}
                      />
                    ) : (
                      <CircuitPanel
                        state={state}
                        command={command}
                        intervene={intervene}
                        disabled={disabled}
                      />
                    )
                  ) : atlasView === 'build' ? (
                    <BuildPanel
                      state={state}
                      command={command}
                      pending={pending}
                      reset={reset}
                      disabled={editDisabled}
                    />
                  ) : (
                    <ConnectivityPanel command={command} disabled={disabled} />
                  )}
                </ErrorBoundary>
              </div>
            </>
          )}
          {page === 'experiments' && (
            <ErrorBoundary key="experiments" name={pageNames.experiments}>
              <Experiments
                state={state}
                command={command}
                pending={pending}
                disabled={disabled}
                onLoaded={() => setPage('workbench')}
              />
            </ErrorBoundary>
          )}
          {page === 'workbench' && (
            <ErrorBoundary key="workbench" name={pageNames.workbench}>
              <Workbench
                state={state}
                command={command}
                transportPending={transportPending}
                exportPending={!!pending.export}
                disabled={disabled}
                editDisabled={editDisabled}
                valid={valid}
                running={running}
                batchActive={batchActive}
                effectiveView={effectiveView}
                setView={setView}
                viewportRef={viewportRef}
                seed={seed}
                setSeed={setSeed}
                draft={draft}
                setDraft={setDraft}
                moveTarget={moveTarget}
                intervene={intervene}
                reset={reset}
                exportRun={exportRun}
                openModelNotes={() => setModelNotes(true)}
                openExperiments={() => setPage('experiments')}
              />
            </ErrorBoundary>
          )}
        </div>
        <footer>
          <div>
            <FlyMark small />
            <span>
              {state?.config.neural_model === 'connectome'
                ? `Walking controller: FlyWire circuit ${state.config.connectome_parameters.circuit} · data-derived wiring, assumed signs, ${state.config.connectome_parameters.dynamics === 'spiking' ? 'spiking neurons after Shiu et al. 2024' : 'engineered rate dynamics'}`
                : 'No biological connectome loaded into the walking controller'}
            </span>
            <button onClick={() => setModelNotes(true)}>
              Model & sources <MoveUpRight size={12} />
            </button>
          </div>
          <span>
            Local by design<span className="footer-dot">·</span>
            {fmt(state?.memory_mb, 0)} MB<span className="footer-dot">·</span>All calculations in
            Python
          </span>
        </footer>
      </main>
      {modelNotes && (
        <ModelDialog state={state} version={version} close={() => setModelNotes(false)} />
      )}
      {quitOpen && (
        <QuitDialog
          close={() => setQuitOpen(false)}
          quit={quit}
          quitting={quitting}
          error={quitFailed ? (error ?? 'Quitting failed. Try again.') : null}
          hasSample={!!state?.sample}
        />
      )}
    </>
  );
}
