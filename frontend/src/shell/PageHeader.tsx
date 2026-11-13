import {createContext, useContext, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import type {RouteInfo} from '../route';

// The element that holds the page's actions, so a page can put its buttons into the header.
export const PageActionsSlot = createContext<HTMLElement | null>(null);

// Renders its children among the current page's header actions.
export function PageActions({children}: {children: ReactNode}) {
  const slot = useContext(PageActionsSlot);
  return slot ? createPortal(children, slot) : null;
}

// A compact page header: the section, the title, one line of description and the page's actions.
export function PageHeader({
  route,
  meta,
  actionsRef,
}: {
  route: RouteInfo;
  meta?: ReactNode;
  actionsRef: (element: HTMLElement | null) => void;
}) {
  return (
    <div className="page-header">
      <div className="page-heading">
        {route.group !== 'Overview' && <span className="page-section">{route.group}</span>}
        <h1 tabIndex={-1}>{route.title}</h1>
        <p>{route.description}</p>
      </div>
      <div className="page-actions">
        {meta}
        <div className="page-action-slot" ref={actionsRef} />
      </div>
    </div>
  );
}
