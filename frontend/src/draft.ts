// Sends at most one value per `interval` ms while values keep arriving, and the last held-back value
// on `flush` (on release), so dragging a control stays live without a request per pixel.
export function throttled<T>(
  send: (value: T) => void,
  interval: number,
  now: () => number = () => Date.now(),
): {push: (value: T) => void; flush: () => boolean} {
  let last = -Infinity;
  let held: {value: T} | null = null;
  const emit = (value: T) => {
    last = now();
    held = null;
    send(value);
  };
  return {
    push: (value) => {
      if (now() - last >= interval) emit(value);
      else held = {value};
    },
    // True when a held-back value was sent.
    flush: () => {
      if (!held) return false;
      emit(held.value);
      return true;
    },
  };
}
