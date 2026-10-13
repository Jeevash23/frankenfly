// Fixed-decimal readouts; a dash stands in for a value that has not arrived yet.
export const fmt = (value: number | undefined, digits = 2) =>
  value === undefined ? '—' : value.toFixed(digits);
