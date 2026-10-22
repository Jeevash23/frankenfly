import type {BatchSummary, MetricSummary} from './types.ts';

// A finished comparison's statistics (GET /api/batches/{batch_id}/summary), for display. The server
// computes every number; these helpers only label and format them.

// Fewer trials than this per condition (or pairs per difference) are marked as a small sample.
export const SMALL_N = 5;

// The metrics the server summarizes, in display order, and how to show them.
export const METRICS: Record<string, {label: string; unit: string; digits: number}> = {
  target_distance_mm: {label: 'Final distance to target', unit: 'mm', digits: 2},
  path_length_mm: {label: 'Path length', unit: 'mm', digits: 2},
  net_turn_deg: {label: 'Net turn', unit: '°', digits: 1},
  mean_speed_mm_s: {label: 'Mean speed', unit: 'mm/s', digits: 2},
  // A fraction of trials (closest approach within reach_mm), shown as a percentage.
  reached: {label: 'Reached the target', unit: '%', digits: 0},
};

// The summary's metrics: the known ones in display order, then any others the server adds.
export function metricOrder(summary: Pick<BatchSummary, 'conditions'>): string[] {
  const present = new Set(summary.conditions.flatMap((c) => Object.keys(c.metrics)));
  return [
    ...Object.keys(METRICS).filter((m) => present.has(m)),
    ...[...present].filter((m) => !Object.hasOwn(METRICS, m)),
  ];
}

export const metricLabel = (metric: string) => {
  const spec = METRICS[metric];
  return spec ? `${spec.label} (${spec.unit})` : metric.replaceAll('_', ' ');
};

// A value in the metric's display unit and precision; a dash when there is none.
export function formatValue(metric: string, value: number | null | undefined, signed = false) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const spec = METRICS[metric] ?? {digits: 2};
  const shown = metric === 'reached' ? value * 100 : value;
  const text = shown.toFixed(spec.digits);
  return signed && shown > 0 ? `+${text}` : text.replace(/^-(0\.?0*)$/, '$1');
}

// An axis tick: already a round number, so no trailing zeros ("5", "0.25", "-100").
export const formatTick = (metric: string, value: number) =>
  String(Number((metric === 'reached' ? value * 100 : value).toPrecision(6)));

// "1.19 ± 0.03": the mean and sample SD (no SD below two trials, and none for the share of
// trials that reached the target, which is a proportion).
export function formatEstimate(metric: string, summary: MetricSummary): string {
  const mean = formatValue(metric, summary.mean);
  return summary.sd === null || metric === 'reached'
    ? mean
    : `${mean} ± ${formatValue(metric, summary.sd)}`;
}

// "1.17 to 1.22"; null when the server gives no interval (fewer than two trials).
export function formatInterval(
  metric: string,
  ci: [number, number] | null,
  signed = false,
): string | null {
  if (!ci) return null;
  return `${formatValue(metric, ci[0], signed)} to ${formatValue(metric, ci[1], signed)}`;
}

// An interval is called wide when it is wider than the estimate itself (|estimate|): an
// uncertainty of more than about ±50%. Estimates near zero always have wide intervals.
export function wideInterval(estimate: number | null, ci: [number, number] | null): boolean {
  if (estimate === null || !ci) return false;
  return ci[1] - ci[0] > Math.abs(estimate);
}

// The smallest number of trials per condition, or null without conditions.
export function smallestN(summary: Pick<BatchSummary, 'conditions'>): number | null {
  return summary.conditions.length ? Math.min(...summary.conditions.map((c) => c.n)) : null;
}

// The sentence above the table when samples are small, or null.
export function sampleNote(summary: Pick<BatchSummary, 'conditions'>): string | null {
  const n = smallestN(summary);
  if (n === null || n >= SMALL_N) return null;
  const per = n === 1 ? '1 trial' : `${n} trials`;
  return `Small samples: as few as ${per} per condition. With so few trials the SD is unstable and the intervals are approximate (a bootstrap interval of a mean from a handful of trials tends to be too narrow), so read the differences as descriptive. More seeds narrow them.`;
}

// "1 partial and 2 duplicate trials left out.": trials the statistics do not count (unfinished
// ones, and repeats of a condition and seed), or null when every trial counts. Servers before
// v0.6 do not count duplicates.
export function leftOutNote(
  summary: Pick<BatchSummary, 'partial_trials'> & {duplicate_trials?: number},
): string | null {
  const partial = summary.partial_trials,
    duplicate = summary.duplicate_trials ?? 0;
  const parts = [
    partial ? `${partial} partial` : '',
    duplicate ? `${duplicate} duplicate` : '',
  ].filter(Boolean);
  if (!parts.length) return null;
  return `${parts.join(' and ')} ${partial + duplicate === 1 ? 'trial' : 'trials'} left out: only complete trials count, once per condition and seed.`;
}

export const summaryCsvUrl = (batchId: string) =>
  `/api/batches/${encodeURIComponent(batchId)}/summary?format=csv`;
