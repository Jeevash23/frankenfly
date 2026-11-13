import {CircleHelp, LoaderCircle, Menu, Moon, Power, Search, Sun} from 'lucide-react';
import {FlyMark} from './FlyMark';
import {routeHash} from '../route';
import type {Theme} from '../theme';

const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
export const PALETTE_KEYS = MAC ? '⌘K' : 'Ctrl K';

// The compact header: brand, search, connection, running jobs, theme, help and Quit.
export function AppHeader({
  connected,
  serverClosed,
  disabled,
  version,
  activeJobs,
  theme,
  toggleTheme,
  drawer,
  drawerOpen,
  openDrawer,
  openPalette,
  openModelNotes,
  openQuit,
}: {
  connected: boolean;
  serverClosed: boolean;
  disabled: boolean;
  version: string | null;
  activeJobs: number;
  theme: Theme;
  toggleTheme: () => void;
  drawer: boolean;
  drawerOpen: boolean;
  openDrawer: () => void;
  openPalette: () => void;
  openModelNotes: () => void;
  openQuit: () => void;
}) {
  const online = connected && !serverClosed;
  return (
    <header className="app-header">
      {drawer && (
        <button
          type="button"
          className="icon-button menu-button"
          aria-label="Open navigation"
          aria-controls="sidebar"
          aria-expanded={drawerOpen}
          onClick={openDrawer}
        >
          <Menu size={18} />
        </button>
      )}
      <a href={routeHash('overview')} className="brand" aria-label="DigitalFly overview">
        <span className="brand-mark">
          <FlyMark />
        </span>
        <span className="brand-name">
          DigitalFly<span className="brand-period">.</span>
        </span>
      </a>
      <button
        type="button"
        className="palette-trigger"
        onClick={openPalette}
        aria-label="Search pages, actions and cell types"
        aria-keyshortcuts="Control+K Meta+K"
      >
        <Search size={14} />
        <span>Search or jump to…</span>
        <kbd>{PALETTE_KEYS}</kbd>
      </button>
      <div className="header-right">
        <span className="connection">
          <span className={`connection-dot ${online ? 'online' : ''}`} />
          <span className="connection-text">
            {serverClosed
              ? 'Server stopped'
              : connected
                ? 'Local connection'
                : 'Connecting locally'}
          </span>
        </span>
        {activeJobs > 0 && (
          <a
            className="jobs-indicator"
            href={routeHash('jobs')}
            aria-label={`${activeJobs} background ${activeJobs === 1 ? 'job' : 'jobs'} running`}
          >
            <LoaderCircle size={13} className="spin" />
            <span>{activeJobs}</span>
            <span className="jobs-indicator-text">running</span>
          </a>
        )}
        {version && <span className="version">v{version}</span>}
        <button
          type="button"
          className="icon-button"
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
          title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={openModelNotes}
          aria-label="Open model notes"
          title="Model & sources"
        >
          <CircleHelp size={16} />
        </button>
        <button type="button" className="quit-button" disabled={disabled} onClick={openQuit}>
          <Power size={14} />
          <span>Quit</span>
        </button>
      </div>
    </header>
  );
}
