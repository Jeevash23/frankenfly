import {useEffect, useRef, useState} from 'react';
import {MoveUpRight} from 'lucide-react';
import type {Config, Intervention, Stimulus} from './types';
import {useSimulation} from './useSimulation';
import {fmt} from './format';
import {AnatomyPanel, ConnectivityPanel} from './Atlas';
import {CircuitPanel} from './ResearchPanels';
import Experiments from './Experiments';
import {AppHeader, type Page} from './shell/AppHeader';
import {Alerts, type Exported} from './shell/Alerts';
import {ModelDialog, QuitDialog} from './shell/Dialogs';
import {FlyMark} from './shell/FlyMark';
import {Workbench} from './workbench/Workbench';
import type {WorldView} from './workbench/WorldPanel';
import './research.css';

export default function App() {
  const [serverClosed, setServerClosed] = useState(false);
  const {state, connected, busy, error, command, clearError} = useSimulation(!serverClosed);
  const [page, setPage] = useState<Page>('workbench');
  const [atlasView, setAtlasView] = useState<'anatomy' | 'circuit' | 'connectivity'>('anatomy');
  const [quitOpen, setQuitOpen] = useState(false);
  const [view, setView] = useState<WorldView>('specimen');
  const [modelNotes, setModelNotes] = useState(false);
  const [seed, setSeed] = useState(42);
  const [draft, setDraft] = useState({x: '12', y: '8'});
  const [exported, setExported] = useState<Exported | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const disabled = !connected || busy || serverClosed || state?.status === 'initializing';
  const batchActive = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const editDisabled = disabled || batchActive;
  const valid = !!state?.sample && state?.status !== 'error';
  const running = state?.status === 'running';
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
      <AppHeader
        page={page}
        setPage={setPage}
        connected={connected}
        serverClosed={serverClosed}
        disabled={disabled}
        openModelNotes={() => setModelNotes(true)}
        openQuit={() => setQuitOpen(true)}
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
              {state?.config.sensor_model === 'vision' ? 'Compound-eye input' : 'Geometric input'} ·
              engineered neural controller
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
          <Workbench
            state={state}
            command={command}
            busy={busy}
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
            {fmt(state?.memory_mb, 0)} MB<span className="footer-dot">·</span>All calculations in
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
