import {useEffect, useRef, type KeyboardEvent} from 'react';
import {PanelLeftClose, PanelLeftOpen} from 'lucide-react';
import {GROUPS, ROUTES, type RouteId} from '../route';
import {ROUTE_ICONS} from './icons';

// Arrow keys move between the links of the sidebar; Tab still walks through them in order.
function linkKeys(e: KeyboardEvent<HTMLElement>) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
  const links = [...e.currentTarget.querySelectorAll<HTMLAnchorElement>('a.nav-link')];
  const i = links.indexOf(document.activeElement as HTMLAnchorElement);
  if (i < 0) return;
  e.preventDefault();
  const next =
    e.key === 'Home'
      ? 0
      : e.key === 'End'
        ? links.length - 1
        : (i + (e.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length;
  links[next].focus();
}

// The grouped page navigation: a rail beside the page that collapses to icons, and on phones a
// drawer opened from the header.
export function Sidebar({
  route,
  collapsed,
  toggleCollapsed,
  drawer,
  drawerOpen,
  closeDrawer,
  navigated,
  activeJobs,
}: {
  route: RouteId;
  collapsed: boolean;
  toggleCollapsed: () => void;
  // True at phone widths, where the sidebar is a drawer.
  drawer: boolean;
  drawerOpen: boolean;
  closeDrawer: () => void;
  // A link in the drawer was followed (the app closes the drawer and focuses the page).
  navigated: (route: RouteId) => void;
  activeJobs: number;
}) {
  const hidden = drawer && !drawerOpen;
  const aside = useRef<HTMLElement>(null);
  // An opened drawer takes the focus to the current page's link.
  useEffect(() => {
    if (drawer && drawerOpen)
      requestAnimationFrame(() =>
        aside.current?.querySelector<HTMLElement>('[aria-current="page"]')?.focus(),
      );
  }, [drawer, drawerOpen]);
  return (
    <>
      {drawer && drawerOpen && <div className="sidebar-scrim" onClick={closeDrawer} />}
      <aside
        ref={aside}
        id="sidebar"
        className="sidebar"
        data-collapsed={!drawer && collapsed ? 'true' : undefined}
        data-open={drawer && drawerOpen ? 'true' : undefined}
        inert={hidden}
        aria-hidden={hidden || undefined}
      >
        <nav aria-label="Main navigation" onKeyDown={linkKeys}>
          {GROUPS.map((group) => {
            const items = ROUTES.filter((r) => r.group === group);
            const labelId = `nav-group-${group.toLowerCase()}`;
            return (
              <div className="nav-group" key={group}>
                {group !== 'Overview' && (
                  <div className="nav-group-label" id={labelId}>
                    {group}
                  </div>
                )}
                <ul aria-labelledby={group !== 'Overview' ? labelId : undefined}>
                  {items.map((r) => {
                    const Icon = ROUTE_ICONS[r.id];
                    const current = route === r.id;
                    return (
                      <li key={r.id}>
                        <a
                          href={`#${r.path}`}
                          className="nav-link"
                          aria-current={current ? 'page' : undefined}
                          title={!drawer && collapsed ? r.label : undefined}
                          onClick={() => drawer && navigated(r.id)}
                        >
                          <Icon size={16} strokeWidth={1.7} aria-hidden />
                          <span className="nav-label">{r.label}</span>
                          {r.id === 'jobs' && activeJobs > 0 && (
                            <span className="nav-badge" aria-label={`${activeJobs} running`}>
                              {activeJobs}
                            </span>
                          )}
                        </a>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </nav>
        {!drawer && (
          <button
            type="button"
            className="sidebar-collapse"
            onClick={toggleCollapsed}
            aria-label={collapsed ? 'Expand the sidebar' : 'Collapse the sidebar'}
            aria-expanded={!collapsed}
            aria-controls="sidebar"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            <span className="nav-label">Collapse</span>
          </button>
        )}
      </aside>
    </>
  );
}
