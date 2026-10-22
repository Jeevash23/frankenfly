// Any time-stamped series: telemetry samples or derived traces. Values are clamped to 0..top.
export function trace<T extends {t: number}>(
  samples: T[],
  pick: (sample: T) => number,
  width = 600,
  height = 110,
  top = 1.4,
): string {
  if (!samples.length) return '';
  const end = Math.max(2, samples[samples.length - 1].t);
  const start = Math.max(0, end - 4);
  return samples
    .filter((s) => s.t >= start)
    .map(
      (s, i) =>
        `${i ? 'L' : 'M'}${(((s.t - start) / (end - start)) * width).toFixed(2)},${(height - (Math.max(0, Math.min(top, pick(s))) / top) * height).toFixed(2)}`,
    )
    .join(' ');
}

// Arrow keys move the target 1 mm (5 mm with Shift) inside the ±40 mm arena; null for other keys.
export function nudgeTarget(
  target: {x: number; y: number},
  key: string,
  shift: boolean,
): {x: number; y: number} | null {
  const directions: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, 1],
    ArrowDown: [0, -1],
  };
  if (!Object.hasOwn(directions, key)) return null;
  const [dx, dy] = directions[key];
  const step = shift ? 5 : 1;
  const move = (value: number, d: number) =>
    Math.round(Math.max(-40, Math.min(40, value + d * step)) * 10) / 10;
  return {x: move(target.x, dx), y: move(target.y, dy)};
}

export function targetFromPoint(
  clientX: number,
  clientY: number,
  rect: {left: number; top: number; width: number; height: number},
  extent: number,
) {
  return {
    x:
      Math.round(
        Math.max(-40, Math.min(40, (((clientX - rect.left) / rect.width) * 2 - 1) * extent)) * 10,
      ) / 10,
    y:
      Math.round(
        Math.max(-40, Math.min(40, (1 - ((clientY - rect.top) / rect.height) * 2) * extent)) * 10,
      ) / 10,
  };
}

// "Nice" axis ticks, 1, 2 or 5 × 10^k apart, from at or below `low` to at or above `high`.
export function niceTicks(low: number, high: number, count = 4): number[] {
  if (!(high > low)) return [low];
  const raw = (high - low) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw * (1 - 1e-9)) ?? raw;
  const first = Math.floor(low / step + 1e-9),
    last = Math.ceil(high / step - 1e-9);
  const digits = Math.max(0, -Math.floor(Math.log10(step)));
  return Array.from({length: last - first + 1}, (_, i) =>
    Number(((first + i) * step).toFixed(digits)),
  );
}

// A dot-and-interval chart on one horizontal axis from `left` to `right` (SVG units): each row's
// estimate and 95% interval. The axis always includes zero, so sizes and signs compare honestly.
// Rows without an estimate are null; rows without an interval have low = high = the estimate.
export function intervalChart(
  rows: {estimate: number | null; ci: [number, number] | null}[],
  left: number,
  right: number,
): {
  ticks: {value: number; x: number}[];
  zero: number;
  rows: ({x: number; low: number; high: number} | null)[];
} {
  const values = [0];
  for (const row of rows)
    if (row.estimate !== null && Number.isFinite(row.estimate))
      values.push(row.estimate, ...(row.ci ?? []).filter(Number.isFinite));
  const lowest = Math.min(...values),
    highest = Math.max(...values);
  // Every value zero: a unit axis.
  const ticks = niceTicks(lowest, highest > lowest ? highest : lowest + 1);
  const low = ticks[0],
    high = ticks[ticks.length - 1];
  const x = (value: number) =>
    Number((left + ((value - low) / (high - low)) * (right - left)).toFixed(2));
  return {
    ticks: ticks.map((value) => ({value, x: x(value)})),
    zero: x(0),
    rows: rows.map((row) =>
      row.estimate === null || !Number.isFinite(row.estimate)
        ? null
        : {
            x: x(row.estimate),
            low: x(row.ci?.[0] ?? row.estimate),
            high: x(row.ci?.[1] ?? row.estimate),
          },
    ),
  };
}
