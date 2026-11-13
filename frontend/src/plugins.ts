// GET /api/plugins (digitalfly/plugins.py): installed plugins and what each contributes.
export interface PluginContribution {
  name: string;
  title: string;
  unit?: string;
  parameters?: Record<string, unknown>;
}
export interface InstalledPlugin {
  name: string;
  distribution: string | null;
  version: string | null;
  api_version: number | null;
  status: 'ok' | 'error' | 'incompatible';
  error: string | null;
  title: string;
  description: string;
  url: string;
  license: string;
  entry_point: string;
  contributions: Record<string, PluginContribution[]>;
}
export interface PluginListing {
  api_version: number;
  enabled: boolean;
  group: string;
  plugins: InstalledPlugin[];
}

const KIND_NAMES: Record<string, string> = {
  sensors: 'sensor',
  stimuli: 'stimulus program',
  scorecard_tests: 'scorecard test',
  metrics: 'metric',
  commands: 'toolkit command',
};

// "2 metrics, 1 sensor": what a plugin adds, by kind.
export function contributionSummary(plugin: InstalledPlugin): string {
  const parts = Object.entries(plugin.contributions)
    .filter(([, items]) => items.length > 0)
    .map(([kind, items]) => {
      const name = KIND_NAMES[kind] ?? kind;
      return `${items.length} ${name}${items.length === 1 ? '' : 's'}`;
    });
  return parts.join(', ') || 'nothing';
}

// Every contribution as it is named in runs and commands: "plugin:name".
export function contributionNames(plugin: InstalledPlugin): string[] {
  return Object.values(plugin.contributions).flatMap((items) =>
    items.map((c) => `${plugin.name}:${c.name}`),
  );
}
