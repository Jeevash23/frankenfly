import {CircleHelp, Power} from 'lucide-react';
import {FlyMark} from './FlyMark';

export type Page = 'workbench' | 'atlas' | 'experiments';

export function AppHeader({
  page,
  setPage,
  connected,
  serverClosed,
  disabled,
  openModelNotes,
  openQuit,
}: {
  page: Page;
  setPage: (page: Page) => void;
  connected: boolean;
  serverClosed: boolean;
  disabled: boolean;
  openModelNotes: () => void;
  openQuit: () => void;
}) {
  return (
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
          {serverClosed ? 'Server stopped' : connected ? 'Local connection' : 'Connecting locally'}
        </span>
        <span className="version">v0.2</span>
        <button className="icon-button" onClick={openModelNotes} aria-label="Open model notes">
          <CircleHelp size={16} />
        </button>
        <button className="quit-button" disabled={disabled} onClick={openQuit}>
          <Power size={14} />
          Quit
        </button>
      </div>
    </header>
  );
}
