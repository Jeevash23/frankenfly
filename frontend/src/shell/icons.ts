import {
  Activity,
  Bot,
  Brain,
  ClipboardCheck,
  FlaskConical,
  Hammer,
  LayoutDashboard,
  Library,
  ListChecks,
  MonitorPlay,
  Network,
  Puzzle,
  Waypoints,
  type LucideIcon,
} from 'lucide-react';
import type {RouteId} from '../route';

// One icon per page, in the sidebar and the command palette.
export const ROUTE_ICONS: Record<RouteId, LucideIcon> = {
  overview: LayoutDashboard,
  workbench: MonitorPlay,
  protocols: FlaskConical,
  library: Library,
  jobs: ListChecks,
  scorecard: ClipboardCheck,
  explorer: Network,
  build: Hammer,
  circuit: Activity,
  atlas: Brain,
  connectivity: Waypoints,
  plugins: Puzzle,
  agents: Bot,
};
