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
