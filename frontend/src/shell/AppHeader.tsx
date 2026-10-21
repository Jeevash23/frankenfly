import {CircleHelp, Power} from 'lucide-react';
import {FlyMark} from './FlyMark';
import {tabKeys} from '../keys';

export type Page = 'workbench' | 'atlas' | 'experiments';
const PAGES: readonly Page[] = ['workbench', 'atlas', 'experiments'];

export function AppHeader({
  page,
  setPage,
  connected,
  serverClosed,
  disabled,
  version,
  openModelNotes,
  openQuit,
}: {
  page: Page;
  setPage: (page: Page) => void;
  connected: boolean;
  serverClosed: boolean;
  disabled: boolean;
  version: string | null;
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
      <nav aria-label="Main navigation" role="tablist" onKeyDown={tabKeys(PAGES, page, setPage)}>
        {PAGES.map((p) => (
          <button
            key={p}
            id={`page-tab-${p}`}
            role="tab"
            data-tab={p}
            aria-selected={page === p}
            aria-controls="page-panel"
            tabIndex={page === p ? 0 : -1}
            className={page === p ? 'nav-active' : ''}
            onClick={() => setPage(p)}
          >
            {p === 'atlas' ? 'Neural atlas' : p === 'experiments' ? 'Experiments' : 'Workbench'}
          </button>
        ))}
      </nav>
      <div className="header-right">
        <span className={`connection-dot ${connected && !serverClosed ? 'online' : ''}`} />
        <span>
          {serverClosed ? 'Server stopped' : connected ? 'Local connection' : 'Connecting locally'}
        </span>
        {version && <span className="version">v{version}</span>}
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
