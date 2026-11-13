// The page and the Neural atlas tab live in the URL hash (#/workbench, #/atlas/circuit,
// #/experiments), so Back, Forward and reloading keep your place.

export type Page = 'workbench' | 'atlas' | 'experiments';
export type AtlasView = 'anatomy' | 'circuit' | 'build' | 'explore' | 'connectivity';
export const PAGES: readonly Page[] = ['workbench', 'atlas', 'experiments'];
export const ATLAS_VIEWS: readonly AtlasView[] = [
  'anatomy',
  'circuit',
  'build',
  'explore',
  'connectivity',
];

// The page and, on the atlas page, its tab. An unknown or empty hash is the Workbench.
export function parseHash(hash: string): {page: Page; atlas: AtlasView | null} {
  const [page, tab] = hash.replace(/^#\/?/, '').split(/[/?]/);
  if (page === 'atlas')
    return {
      page,
      atlas: ATLAS_VIEWS.includes(tab as AtlasView) ? (tab as AtlasView) : null,
    };
  return {page: PAGES.includes(page as Page) ? (page as Page) : 'workbench', atlas: null};
}

export function routeHash(page: Page, atlas: AtlasView): string {
  return page === 'atlas' ? `#/atlas/${atlas}` : `#/${page}`;
}
