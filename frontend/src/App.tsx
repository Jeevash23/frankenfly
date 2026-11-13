import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {MoveUpRight} from 'lucide-react';
import type {Config, Intervention, InterventionChange, Stimulus, StimulusChange} from './types';
import {useServerVersion, useSimulation} from './useSimulation';
import {fmt} from './format';
import {AnatomyPanel, ConnectivityPanel} from './Atlas';
import {CircuitPanel} from './ResearchPanels';
import Experiments from './experiments/Experiments';
import {JobsPanel} from './experiments/JobsPanel';
import {PluginsPanel} from './experiments/PluginsPanel';
import {RunLibrary} from './experiments/RunLibrary';
import {ScorecardPanel} from './experiments/Scorecard';
import {AgentsPage} from './extend/AgentsPage';
import {Overview, type QuickAction} from './overview/Overview';
import {ConnectomeCircuitView} from './connectome/CircuitView';
import {BuildPanel} from './connectome/BuildPanel';
import {ExplorePanel} from './connectome/ExplorePanel';
import {modelPhrases, noInterventions} from './models';
import {jobActive} from './jobs';
import {useJobs, useReplayReload} from './useJobs';
import {useMedia, useStoredFlag} from './useShell';
import {ROUTES, parseHash, routeHash, routeInfo, type Route, type RouteId} from './route';
import {
  applyTheme,
  effectiveTheme,
  readTheme,
  systemTheme,
  toggledTheme,
  writeTheme,
  type Theme,
  type ThemeChoice,
} from './theme';
import {AppHeader} from './shell/AppHeader';
import {Alerts, type Exported} from './shell/Alerts';
import {CommandPalette, type PaletteCommand} from './shell/CommandPalette';
import {ModelDialog, QuitDialog} from './shell/Dialogs';
import {ErrorBoundary} from './shell/ErrorBoundary';
import {FlyMark} from './shell/FlyMark';
import {PageActions, PageActionsSlot, PageHeader} from './shell/PageHeader';
import {Sidebar} from './shell/Sidebar';
import {Workbench} from './workbench/Workbench';
import type {WorldView} from './workbench/WorldPanel';
import './research.css';
import './shell.css';

// Below this width the sidebar becomes a drawer (responsive.css uses the same breakpoint).
const DRAWER_QUERY = '(max-width: 820px)';

// The current page, after replacing an old or partial address with the canonical one, so Back
// never returns to an address that only redirects.
function resolve(hash: string): Route {
  const route = parseHash(hash);
  if (route.redirect) history.replaceState(history.state, '', route.redirect);
  return route;
}

export default function App() {
  const [serverClosed, setServerClosed] = useState(false);
  const {state, connected, pending, error, command, inFlight, clearError} =
    useSimulation(!serverClosed);
  const version = useServerVersion(state?.instance_id);
  // Background jobs, for the header, the Overview and the pages that start or list them.
  const {
    jobs,
    loaded: jobsLoaded,
    error: jobsError,
    refresh: refreshJobs,
    cancel: cancelJob,
  } = useJobs();
  const activeJobs = jobs.filter(jobActive).length;
  const reload = useReplayReload(jobs, jobsLoaded);

  // The page follows the URL hash, so Back, Forward and reload keep your place.
  const [route, setRoute] = useState(() => resolve(location.hash));
  const page = route.route;
  const info = routeInfo(page);
  useEffect(() => {
    const changed = () => setRoute(resolve(location.hash));
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);
  const go = useCallback((next: RouteId, params?: Record<string, string>) => {
    const hash = routeHash(next, params);
    if (location.hash !== hash) location.hash = hash;
    else setRoute(parseHash(hash));
  }, []);
  // Replaces the address without a history entry (after a one-off parameter is used).
  const replace = useCallback((next: RouteId) => {
    history.replaceState(history.state, '', routeHash(next));
    setRoute(parseHash(routeHash(next)));
  }, []);

  // One-off requests from the Overview and the palette, cleared by the page that carries them out.
  const [intent, setIntent] = useState<'first-experiment' | 'score' | null>(null);
  const clearIntent = useCallback(() => setIntent(null), []);
  // The comparison whose trials the run library should list ("Show these trials in the library").
  const [showBatch, setShowBatch] = useState<{id: string; at: number} | null>(null);

  // Layout: a collapsible sidebar, a drawer on phones; light, dark or the system theme.
  const drawer = useMedia(DRAWER_QUERY);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, toggleCollapsed] = useStoredFlag('digitalfly.sidebar-collapsed');
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>(readTheme);
  const [system, setSystem] = useState<Theme>(systemTheme);
  const theme = effectiveTheme(themeChoice, system);
  useEffect(() => applyTheme(themeChoice), [themeChoice]);
  useEffect(() => {
    let query: MediaQueryList;
    try {
      query = matchMedia('(prefers-color-scheme: dark)');
    } catch {
      return;
    }
    const changed = () => setSystem(query.matches ? 'dark' : 'light');
    query.addEventListener?.('change', changed);
    return () => query.removeEventListener?.('change', changed);
  }, []);
  const chooseTheme = useCallback((choice: ThemeChoice) => {
    setThemeChoice(choice);
    writeTheme(choice);
  }, []);
  const toggleTheme = () => chooseTheme(toggledTheme(themeChoice, system));
  const [paletteOpen, setPaletteOpen] = useState(false);

  const [quitOpen, setQuitOpen] = useState(false);
  const [quitting, setQuitting] = useState(false);
  const [quitFailed, setQuitFailed] = useState(false);
  const [view, setView] = useState<WorldView>('specimen');
  const [modelNotes, setModelNotes] = useState(false);
  const [seed, setSeed] = useState(42);
  const [draft, setDraft] = useState({x: '12', y: '8'});
  const [exported, setExported] = useState<Exported | null>(null);
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null);
  const heading = useRef<HTMLDivElement>(null);
  const focusHeading = useRef(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  // Commands no longer disable every control while they run: each control shows its own pending
  // state, and edits made while one is in flight build on what was sent (see inFlight).
  const disabled = !connected || serverClosed || state?.status === 'initializing';
  const batchActive = !!state?.batch && ['running', 'paused'].includes(state.batch.status);
  const editDisabled = disabled || batchActive;
  const valid = !!state?.sample && state?.status !== 'error';
  const running = state?.status === 'running';
  const transportPending = !!(pending.run || pending.pause);
  const canToggleRun = !disabled && valid && !transportPending;
  const toggleRun = useCallback(() => {
    if (canToggleRun) void command(running ? 'pause' : 'run');
  }, [canToggleRun, running, command]);
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
  // A new page starts at the top, has its own title, and closes the drawer.
  const first = useRef(true);
  useEffect(() => {
    document.title = `${info.title} · DigitalFly`;
    if (first.current) {
      first.current = false;
      return;
    }
    window.scrollTo(0, 0);
    setDrawerOpen(false);
    if (focusHeading.current) {
      focusHeading.current = false;
      heading.current?.querySelector<HTMLElement>('h1')?.focus();
    }
    if (page !== 'library') setShowBatch(null);
  }, [page]);
  // A page chosen from the drawer takes the focus to its heading, as the drawer closes.
  const navigatedFromDrawer = (target: RouteId) => {
    if (target === page) {
      setDrawerOpen(false);
      heading.current?.querySelector<HTMLElement>('h1')?.focus();
    } else focusHeading.current = true;
  };
  // Space runs and pauses on the Workbench; Ctrl/Cmd+K opens the command palette anywhere.
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (!modelNotes && !quitOpen) setPaletteOpen((open) => !open);
        return;
      }
      if (e.key === 'Escape' && drawerOpen) {
        setDrawerOpen(false);
        document.querySelector<HTMLElement>('.menu-button')?.focus();
        return;
      }
      if (
        e.code !== 'Space' ||
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLSelectElement ||
        e.target instanceof HTMLButtonElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLAnchorElement ||
        (e.target instanceof Element && e.target.closest('[role="button"]')) ||
        modelNotes ||
        quitOpen ||
        paletteOpen ||
        page !== 'workbench'
      )
        return;
      e.preventDefault();
      toggleRun();
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [toggleRun, modelNotes, quitOpen, paletteOpen, drawerOpen, page]);

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
  const openQuit = () => {
    setQuitFailed(false);
    setQuitOpen(true);
  };

  const quick = (action: QuickAction) => {
    if (action === 'first-experiment') {
      setIntent('first-experiment');
      go('protocols');
    } else if (action === 'score') {
      setIntent('score');
      go('scorecard');
    } else if (action === 'explore-dna02') go('explorer', {type: 'DNa02'});
    else go('build');
  };
  const openCell = useCallback((cellType: string) => go('explorer', {type: cellType}), [go]);
  const commands = useMemo((): PaletteCommand[] => {
    const pages: PaletteCommand[] = ROUTES.map((r) => ({
      id: `page:${r.id}`,
      kind: 'page',
      label: r.label,
      hint: r.group === 'Overview' ? 'Page' : r.group,
      keywords: `${r.title} ${r.description} ${r.keywords}`,
      route: r.id,
      run: () => go(r.id),
    }));
    const actions: (PaletteCommand | false)[] = [
      canToggleRun && {
        id: 'action:run',
        kind: 'action',
        label: running ? 'Pause the simulation' : 'Run the simulation',
        hint: 'Workbench · Space',
        keywords: 'start stop play pause transport',
        run: toggleRun,
      },
      canToggleRun &&
        !running && {
          id: 'action:step',
          kind: 'action',
          label: 'Step the simulation',
          hint: 'One 10 ms control step',
          keywords: 'advance',
          run: () => void command('step'),
        },
      !disabled &&
        valid && {
          id: 'action:export',
          kind: 'action',
          label: 'Export the current run',
          hint: 'Saves it to the run library',
          keywords: 'save zip download',
          run: () => void exportRun(false),
        },
      {
        id: 'action:first',
        kind: 'action',
        label: 'Set up the first experiment',
        hint: 'Protocols & comparisons',
        keywords: 'tutorial start comparison',
        run: () => quick('first-experiment'),
      },
      {
        id: 'action:score',
        kind: 'action',
        label: 'Score the Workbench model',
        hint: 'Validation scorecard',
        keywords: 'run scorecard validate',
        run: () => quick('score'),
      },
      {
        id: 'action:dna02',
        kind: 'action',
        label: 'Explore DNa02',
        hint: 'Connectivity explorer',
        keywords: 'partners steering descending',
        run: () => quick('explore-dna02'),
      },
      {
        id: 'action:theme',
        kind: 'action',
        label: theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme',
        hint: 'Appearance',
        keywords: 'theme dark light mode colour color appearance',
        run: () => chooseTheme(theme === 'dark' ? 'light' : 'dark'),
      },
      themeChoice !== 'system' && {
        id: 'action:system-theme',
        kind: 'action',
        label: 'Follow the system theme',
        hint: 'Appearance',
        keywords: 'theme auto dark light mode',
        run: () => chooseTheme('system'),
      },
      !drawer && {
        id: 'action:sidebar',
        kind: 'action',
        label: collapsed ? 'Expand the sidebar' : 'Collapse the sidebar',
        hint: 'Layout',
        keywords: 'navigation menu rail',
        run: toggleCollapsed,
      },
      {
        id: 'action:notes',
        kind: 'action',
        label: 'Open model notes',
        hint: 'Model & sources',
        keywords: 'help about sources citation',
        run: () => setModelNotes(true),
      },
      !disabled && {
        id: 'action:quit',
        kind: 'action',
        label: 'Quit DigitalFly',
        hint: 'Stops the local server',
        keywords: 'exit shutdown close',
        run: openQuit,
      },
    ];
    return [...pages, ...actions.filter((a): a is PaletteCommand => !!a)];
  }, [
    canToggleRun,
    running,
    disabled,
    valid,
    theme,
    themeChoice,
    drawer,
    collapsed,
    go,
    toggleRun,
    chooseTheme,
    toggleCollapsed,
  ]);

  const runLabel =
    state?.run_id && state.run_id !== 'initializing'
      ? state.run_id.slice(-8).toUpperCase()
      : 'INITIALIZING';
  const sensorName = {
    vision: 'Compound-eye input',
    flyvis: 'FlyVis eyes',
    geometric: 'Geometric input',
  }[state?.config.sensor_model ?? 'geometric'];

  return (
    <div className="app-shell" data-sidebar={collapsed && !drawer ? 'collapsed' : 'expanded'}>
      <a className="skip-link" href="#page-content">
        Skip to content
      </a>
      <AppHeader
        connected={connected}
        serverClosed={serverClosed}
        disabled={disabled}
        version={version}
        activeJobs={activeJobs}
        theme={theme}
        toggleTheme={toggleTheme}
        drawer={drawer}
        drawerOpen={drawerOpen}
        openDrawer={() => setDrawerOpen(true)}
        openPalette={() => setPaletteOpen(true)}
        openModelNotes={() => setModelNotes(true)}
        openQuit={openQuit}
      />
      <Sidebar
        route={page}
        collapsed={collapsed}
        toggleCollapsed={toggleCollapsed}
        drawer={drawer}
        drawerOpen={drawerOpen}
        closeDrawer={() => setDrawerOpen(false)}
        navigated={navigatedFromDrawer}
        activeJobs={activeJobs}
      />
      <main id="page-content" tabIndex={-1}>
        <PageActionsSlot.Provider value={actionsSlot}>
          <div ref={heading}>
            <PageHeader
              route={info}
              actionsRef={setActionsSlot}
              meta={
                page === 'workbench' ? (
                  <div className="run-meta">
                    <span className="chip mono">RUN {runLabel}</span>
                    <span className="run-meta-text">
                      Female-derived body · {sensorName} ·{' '}
                      {modelPhrases[state?.config.neural_model ?? 'engineered']}
                    </span>
                  </div>
                ) : undefined
              }
            />
          </div>
          <Alerts
            state={state}
            connected={connected}
            serverClosed={serverClosed}
            error={error}
            clearError={clearError}
            exported={exported}
            dismissExport={() => setExported(null)}
          />
          {jobsError && ['jobs', 'overview', 'library', 'scorecard'].includes(page) && (
            <p className="microcopy">{jobsError}</p>
          )}
          <div className="page-body" data-page={page}>
            <ErrorBoundary key={page} name={info.title}>
              {page === 'overview' ? (
                <Overview
                  state={state}
                  connected={connected}
                  jobs={jobs}
                  quick={quick}
                  toggleRun={toggleRun}
                  canToggleRun={canToggleRun}
                />
              ) : page === 'workbench' ? (
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
                  openExperiments={() => go('protocols')}
                />
              ) : page === 'protocols' ? (
                <Experiments
                  state={state}
                  command={command}
                  pending={pending}
                  disabled={disabled}
                  onLoaded={() => go('workbench')}
                  reload={reload}
                  showTrials={(id) => {
                    setShowBatch({id, at: Date.now()});
                    go('library');
                  }}
                  setupFirst={intent === 'first-experiment'}
                  setupDone={clearIntent}
                />
              ) : page === 'library' ? (
                <RunLibrary
                  state={state}
                  command={command}
                  disabled={disabled}
                  batchActive={batchActive}
                  jobs={jobs}
                  refreshJobs={refreshJobs}
                  cancelJob={cancelJob}
                  reload={reload}
                  showBatch={showBatch}
                  onLoaded={() => go('workbench')}
                />
              ) : page === 'jobs' ? (
                <>
                  <PageActions>
                    <button type="button" className="secondary-button" onClick={refreshJobs}>
                      Refresh
                    </button>
                  </PageActions>
                  <JobsPanel jobs={jobs} cancel={(id) => void cancelJob(id)} />
                </>
              ) : page === 'scorecard' ? (
                <ScorecardPanel
                  state={state}
                  jobs={jobs}
                  refreshJobs={refreshJobs}
                  disabled={disabled}
                  autoScore={intent === 'score'}
                  autoScoreDone={clearIntent}
                />
              ) : page === 'explorer' ? (
                <ExplorePanel
                  state={state}
                  intervene={intervene}
                  disabled={disabled}
                  openBuild={() => go('build')}
                  openWorkbench={() => go('workbench')}
                  focus={route.params.get('type')}
                  focusDone={() => replace('explorer')}
                />
              ) : page === 'build' ? (
                <BuildPanel
                  state={state}
                  command={command}
                  pending={pending}
                  reset={reset}
                  disabled={editDisabled}
                />
              ) : page === 'circuit' ? (
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
              ) : page === 'atlas' ? (
                <AnatomyPanel state={state} />
              ) : page === 'connectivity' ? (
                <ConnectivityPanel command={command} disabled={disabled} />
              ) : page === 'plugins' ? (
                <PluginsPanel />
              ) : (
                <AgentsPage />
              )}
            </ErrorBoundary>
          </div>
        </PageActionsSlot.Provider>
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
      {paletteOpen && (
        <CommandPalette
          commands={commands}
          openCell={openCell}
          close={() => setPaletteOpen(false)}
        />
      )}
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
    </div>
  );
}
