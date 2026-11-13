// Every page lives in the URL hash (#/experiments/library, #/connectome/explorer), so Back,
// Forward, bookmarks and reloading keep your place. Addresses from before the sidebar
// (#/experiments, #/atlas/circuit, ...) redirect to the page that now holds the same view.

export type RouteId =
  | 'overview'
  | 'workbench'
  | 'protocols'
  | 'library'
  | 'jobs'
  | 'scorecard'
  | 'explorer'
  | 'build'
  | 'circuit'
  | 'atlas'
  | 'connectivity'
  | 'plugins'
  | 'agents';

export type RouteGroup =
  'Overview' | 'Simulate' | 'Experiments' | 'Validate' | 'Connectome' | 'Anatomy' | 'Extend';

export type RouteInfo = {
  id: RouteId;
  // The hash, without the leading '#'.
  path: string;
  group: RouteGroup;
  // The name in the sidebar and the palette; `title` heads the page.
  label: string;
  title: string;
  // One line under the page title.
  description: string;
  // Extra words the command palette matches.
  keywords: string;
};

export const ROUTES: readonly RouteInfo[] = [
  {
    id: 'overview',
    path: '/overview',
    group: 'Overview',
    label: 'Overview',
    title: 'Overview',
    description: 'The live simulation, recent runs, scorecards and jobs at a glance.',
    keywords: 'home dashboard start',
  },
  {
    id: 'workbench',
    path: '/workbench',
    group: 'Simulate',
    label: 'Workbench',
    title: 'Workbench',
    description: 'Change the world, observe the response, follow the sensorimotor loop.',
    keywords: 'simulation live fly arena stimulus interventions signals run pause',
  },
  {
    id: 'protocols',
    path: '/experiments/protocols',
    group: 'Experiments',
    label: 'Protocols & comparisons',
    title: 'Protocols & comparisons',
    description: 'Design a stimulus protocol, vary one condition across seeds, compare outcomes.',
    keywords: 'experiment batch comparison seeds conditions statistics',
  },
  {
    id: 'library',
    path: '/experiments/library',
    group: 'Experiments',
    label: 'Run library',
    title: 'Run library',
    description:
      'Every saved run, with tags, replay checks and ZIP, NWB, manifest and methods export.',
    keywords: 'runs saved export nwb zip manifest methods replay tags',
  },
  {
    id: 'jobs',
    path: '/experiments/jobs',
    group: 'Experiments',
    label: 'Jobs',
    title: 'Background jobs',
    description: 'Circuit builds, replay checks and scorecards running in their own processes.',
    keywords: 'jobs queue background progress cancel',
  },
  {
    id: 'scorecard',
    path: '/validate/scorecard',
    group: 'Validate',
    label: 'Scorecard',
    title: 'Validation scorecard',
    description:
      'Published perturbation → behaviour results, scored for each model by fixed rules.',
    keywords: 'validation tests pass fail published',
  },
  {
    id: 'explorer',
    path: '/connectome/explorer',
    group: 'Connectome',
    label: 'Explorer',
    title: 'Connectivity explorer',
    description: 'Partners, routes and influence across the FlyWire v783 brain or any circuit.',
    keywords: 'flywire partners paths influence neuroglancer cell type wiring',
  },
  {
    id: 'build',
    path: '/connectome/build',
    group: 'Connectome',
    label: 'Build a circuit',
    title: 'Build a circuit',
    description: 'Cut a bounded circuit out of the FlyWire connectome around seed cell types.',
    keywords: 'builder seeds circuit flywire',
  },
  {
    id: 'circuit',
    path: '/connectome/circuit',
    group: 'Connectome',
    label: 'Live circuit',
    title: 'Live circuit',
    description:
      'The walking controller’s circuit as it runs, with its activity and manipulations.',
    keywords: 'activity rates silence activate manipulation network',
  },
  {
    id: 'atlas',
    path: '/anatomy/atlas',
    group: 'Anatomy',
    label: 'Atlas',
    title: 'Male & female anatomy',
    description:
      'Brain surfaces and selected descending neurons from published male and female data.',
    keywords: 'anatomy brain neurons female male fafb malecns',
  },
  {
    id: 'connectivity',
    path: '/anatomy/connectivity',
    group: 'Anatomy',
    label: 'Imported connectivity',
    title: 'Imported connectivity',
    description: 'Import a bounded graph, inspect its connections, keep every source identifier.',
    keywords: 'import json graph dataset',
  },
  {
    id: 'plugins',
    path: '/extend/plugins',
    group: 'Extend',
    label: 'Plugins',
    title: 'Plugins',
    description: 'Installed sensors, stimulus programs, scorecard tests, metrics and commands.',
    keywords: 'extensions plugin api',
  },
  {
    id: 'agents',
    path: '/extend/agents',
    group: 'Extend',
    label: 'Agents & MCP',
    title: 'Agents & MCP',
    description: 'Let an AI agent drive the running app through the local MCP server.',
    keywords: 'mcp claude agent ai tools automation',
  },
];

export const ROUTE_IDS: readonly RouteId[] = ROUTES.map((r) => r.id);
export const GROUPS: readonly RouteGroup[] = [
  'Overview',
  'Simulate',
  'Experiments',
  'Validate',
  'Connectome',
  'Anatomy',
  'Extend',
];

export const routeInfo = (id: RouteId): RouteInfo => ROUTES.find((r) => r.id === id)!;

// Addresses from before the sidebar, and section roots, mapped to the page they open now.
export const REDIRECTS: Readonly<Record<string, RouteId>> = {
  '': 'overview',
  '/': 'overview',
  '/experiments': 'protocols',
  '/atlas': 'atlas',
  '/atlas/anatomy': 'atlas',
  '/atlas/circuit': 'circuit',
  '/atlas/build': 'build',
  '/atlas/explore': 'explorer',
  '/atlas/connectivity': 'connectivity',
  '/simulate': 'workbench',
  '/validate': 'scorecard',
  '/connectome': 'explorer',
  '/anatomy': 'atlas',
  '/extend': 'plugins',
};

export type Route = {
  route: RouteId;
  // The parameters after '?', e.g. #/connectome/explorer?type=DNa02.
  params: URLSearchParams;
  // The canonical hash when the address was an old or partial one (replace it), else null.
  redirect: string | null;
};

// The page for a hash. Old addresses and section roots redirect; unknown ones open the Overview.
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '');
  const q = raw.indexOf('?');
  const written = q < 0 ? raw : raw.slice(0, q);
  const path = written.replace(/\/+$/, '');
  const params = new URLSearchParams(q < 0 ? '' : raw.slice(q + 1));
  const normalized = path.startsWith('/') || path === '' ? path : `/${path}`;
  const direct = ROUTES.find((r) => r.path === normalized);
  if (direct)
    return {
      route: direct.id,
      params,
      redirect: written === direct.path ? null : routeHash(direct.id, params),
    };
  const target = REDIRECTS[normalized] ?? 'overview';
  return {route: target, params, redirect: routeHash(target, params)};
}

export function routeHash(id: RouteId, params?: URLSearchParams | Record<string, string>): string {
  const query = new URLSearchParams(params as Record<string, string> | undefined).toString();
  return `#${routeInfo(id).path}${query ? `?${query}` : ''}`;
}
