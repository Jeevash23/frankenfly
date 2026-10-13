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
