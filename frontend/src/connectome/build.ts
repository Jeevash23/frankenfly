// Pure helpers for the circuit builder form. The server validates again.
import type {BuildRequest as BuildRequestInput} from '../api.gen';

export const CIRCUIT_NAME = /^[a-z0-9][a-z0-9._-]{0,63}$/;

// The form's request: every field of POST /api/connectome/build, defaults filled in.
export type BuildRequest = Required<BuildRequestInput>;

export const defaultBuild: BuildRequest = {
  name: '',
  seeds: [],
  hops: 2,
  threshold: 5,
  cap: 3000,
  whole_brain: false,
  balance_sides: false,
};

// What "Balance left and right" does, in one line.
export const BALANCE_NOTE =
  'The cap keeps equal left and right counts per cell type where the data allow. It is a sampling assumption, not a correction.';

// Whether a listed circuit was built with the cap applied per cell type and side.
export const sideBalanced = (info: {build?: {balance_sides?: boolean}} | undefined) =>
  info?.build?.balance_sides === true;

// Plain-language problems with a build request, or null when it can be sent.
export function buildProblem(
  request: BuildRequest,
  builtIn: string[],
  known: Set<string> | null,
): string | null {
  if (!CIRCUIT_NAME.test(request.name))
    return 'Name the circuit with lower-case letters, digits, dots, dashes or underscores.';
  if (request.name === 'local' || builtIn.includes(request.name))
    return `${request.name} is taken by a built-in circuit. Choose another name.`;
  if (!request.seeds.length) return 'Add at least one seed cell type or FlyWire root ID.';
  if (request.seeds.length > 20) return 'Use at most 20 seeds.';
  if (known) {
    const unknown = request.seeds.filter((s) => !/^\d+$/.test(s) && !known.has(s));
    if (unknown.length)
      return `Not a FlyWire v783 cell type: ${unknown.join(', ')}. Names are case-sensitive.`;
  }
  if (!Number.isInteger(request.hops) || request.hops < 1 || request.hops > 6)
    return 'Choose 1 to 6 hops.';
  if (!Number.isInteger(request.threshold) || request.threshold < 1 || request.threshold > 1000)
    return 'Choose a synapse threshold of 1 to 1000.';
  if (!Number.isInteger(request.cap) || request.cap < 10 || request.cap > 200000)
    return 'Choose a cap of 10 to 200,000 neurons.';
  if (request.balance_sides && request.whole_brain)
    return 'Balancing left and right applies the cap per cell type and side; a whole-brain build has no cap. Choose one.';
  return null;
}

// Catalog matches for a typed prefix: exact match first, then names starting with it, then
// names containing it.
export function suggestTypes(names: string[], query: string, limit = 12): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const starts: string[] = [],
    contains: string[] = [];
  for (const name of names) {
    const lower = name.toLowerCase();
    if (lower.startsWith(q)) starts.push(name);
    else if (lower.includes(q)) contains.push(name);
  }
  const byLength = (a: string, b: string) => a.length - b.length || a.localeCompare(b);
  return [...starts.sort(byLength), ...contains.sort(byLength)].slice(0, limit);
}

// Cell-type lists are written "A; B; C" because FlyWire type names can contain commas.
// Returns null for an empty list (the circuit's default).
export function parseTypes(text: string): string[] | null {
  const names = text
    .split(';')
    .map((t) => t.trim())
    .filter(Boolean);
  return names.length ? [...new Set(names)] : null;
}
