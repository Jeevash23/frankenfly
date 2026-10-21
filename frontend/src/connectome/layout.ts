// Pure helpers for the connectome circuit view. Positions encode hop distance to the
// circuit's seeds and laterality, not anatomy.

export type CircuitType = {
  // The type's index in the circuit; large circuits send only a subset of types.
  index: number;
  name: string;
  count: number;
  layer: number;
  super_class: string;
  transmitters: Record<string, number>;
  transmitter: string;
  sign: number;
  left: number;
  right: number;
  input: boolean;
};
export type TypeEdges = {
  pre: number[];
  post: number[];
  sign: number[];
  synapses: number[];
  connections: number[];
};
export type SideEdges = {pre: number[]; sign: number[]; synapses: number[]};
// A cell type read out as the steering signal: its left and right neurons and their inputs.
export type Readout = {
  cell_type: string;
  type_index: number;
  left: string[];
  right: string[];
  inputs: {left: SideEdges; right: SideEdges};
};
export type CircuitSummary = {
  name: string;
  title: string;
  sha256: string;
  neurons: number;
  connections_active: number;
  types_total: number;
  types_shown: number;
  parameters: Record<string, unknown>;
  readouts: Readout[];
  provenance: Record<string, string>;
  citations: string[];
  types: CircuitType[];
  edges: TypeEdges;
};
export type Node = {x: number; y: number; r: number};

export const VIEW = {width: 1000, height: 560, top: 58, bottom: 512};
const BANDS: Record<number, [number, number]> = {2: [36, 486], 1: [532, 812]};
export const READOUT_X = 912;

// Hop 1 and closer share the right band; hop 2, deeper and unreached types (-1) the left one.
export function band(layer: number): 1 | 2 {
  return layer >= 0 && layer <= 1 ? 1 : 2;
}

// Left-dominant types first, so they sit above right-dominant ones, like a readout's L above R.
export function laterality(type: CircuitType): number {
  const sided = type.left + type.right;
  return sided ? type.right / sided : 0.5;
}

// Vertical centres of the readout neurons: each type's left neuron above its right one.
export function readoutRows(count: number): {left: number; right: number}[] {
  const span = VIEW.bottom - 70 - VIEW.top;
  const slot = span / Math.max(1, count);
  return Array.from({length: count}, (_, k) => {
    const middle = VIEW.top + slot * (k + 0.5);
    const gap = Math.min(90, slot * 0.3);
    return {left: middle - gap, right: middle + gap};
  });
}

// Positions keyed by each type's circuit index. Readout types are drawn separately.
export function layoutTypes(types: CircuitType[], excluded: Set<number>): Map<number, Node> {
  const positions = new Map<number, Node>();
  const largest = Math.max(1, ...types.map((t) => t.count));
  for (const layer of [1, 2]) {
    const members = types
      .map((type) => ({type, index: type.index}))
      .filter(({type, index}) => !excluded.has(index) && band(type.layer) === layer)
      .sort(
        (a, b) =>
          laterality(a.type) - laterality(b.type) ||
          b.type.count - a.type.count ||
          a.type.name.localeCompare(b.type.name),
      );
    if (!members.length) continue;
    const [x0, x1] = BANDS[layer];
    const width = x1 - x0,
      height = VIEW.bottom - VIEW.top;
    const cell = Math.max(9, Math.min(46, Math.sqrt((width * height) / members.length)));
    const rows = Math.max(1, Math.floor(height / cell));
    const columns = Math.ceil(members.length / rows);
    const dx = columns > 1 ? width / (columns - 1 || 1) : 0;
    const dy = height / Math.max(1, Math.min(rows, members.length) - 1 || 1);
    members.forEach(({type, index}, i) => {
      const column = Math.floor(i / rows),
        row = i % rows;
      positions.set(index, {
        x: columns > 1 ? x0 + column * dx : (x0 + x1) / 2,
        y: members.length > 1 ? VIEW.top + row * dy : (VIEW.top + VIEW.bottom) / 2,
        r: Math.max(2.2, Math.min(cell * 0.42, 2.2 + 11 * Math.sqrt(type.count / largest))),
      });
    });
  }
  return positions;
}

// Indices of the connections worth drawing: every connection of the selected type, and
// otherwise the strongest ones by synapse count.
export function edgesToDraw(edges: TypeEdges, limit: number, selected: number | null): number[] {
  const all = edges.synapses.map((_, i) => i);
  const chosen = new Set(
    [...all].sort((a, b) => edges.synapses[b] - edges.synapses[a] || a - b).slice(0, limit),
  );
  if (selected !== null)
    all.forEach((i) => {
      if (edges.pre[i] === selected || edges.post[i] === selected) chosen.add(i);
    });
  return [...chosen].sort((a, b) => a - b);
}

export type Partner = {type: number; sign: number; synapses: number; connections: number};

// Strongest partners of one type: inputs (direction 'in') or outputs ('out').
export function topPartners(
  edges: TypeEdges,
  type: number,
  direction: 'in' | 'out',
  limit = 6,
): Partner[] {
  const result: Partner[] = [];
  edges.synapses.forEach((synapses, i) => {
    if ((direction === 'in' ? edges.post[i] : edges.pre[i]) !== type) return;
    result.push({
      type: direction === 'in' ? edges.pre[i] : edges.post[i],
      sign: edges.sign[i],
      synapses,
      connections: edges.connections[i],
    });
  });
  return result.sort((a, b) => b.synapses - a.synapses || a.type - b.type).slice(0, limit);
}

// Pale paper at rest to deep green at full activity.
export function activityColor(rate: number): string {
  const t = Math.max(0, Math.min(1, rate));
  const from = [238, 240, 232],
    to = [43, 86, 63];
  return `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * t)).join(',')})`;
}

// A focusable spot in the diagram, for keyboard movement between nodes.
export type Spot = {key: string; x: number; y: number};

// Arrow-key movement between diagram nodes: Up and Down to the nearest node above or below in the
// same column, Left and Right to the nearest node in the next column over, Home and End to the first
// and last node (columns left to right, top to bottom). Null for other keys or past an edge.
export function neighbour(spots: Spot[], current: string, key: string): string | null {
  if (!spots.length) return null;
  if (key === 'Home' || key === 'End') {
    const ordered = [...spots].sort((a, b) => a.x - b.x || a.y - b.y);
    return ordered[key === 'Home' ? 0 : ordered.length - 1].key;
  }
  const here = spots.find((s) => s.key === current);
  if (!here) return null;
  const column = (s: Spot) => Math.abs(s.x - here.x) < 1;
  let candidates: Spot[];
  if (key === 'ArrowUp' || key === 'ArrowDown') {
    const sign = key === 'ArrowUp' ? -1 : 1;
    candidates = spots.filter((s) => column(s) && (s.y - here.y) * sign > 0);
  } else if (key === 'ArrowLeft' || key === 'ArrowRight') {
    const sign = key === 'ArrowLeft' ? -1 : 1;
    const beyond = spots.filter((s) => !column(s) && (s.x - here.x) * sign > 0);
    if (!beyond.length) return null;
    const nearest = Math.min(...beyond.map((s) => Math.abs(s.x - here.x)));
    candidates = beyond.filter((s) => Math.abs(s.x - here.x) - nearest < 1);
  } else return null;
  if (!candidates.length) return null;
  return candidates.reduce((best, s) =>
    Math.abs(s.y - here.y) < Math.abs(best.y - here.y) ? s : best,
  ).key;
}

// For the dark anatomy canvas: dim green at rest, bright lime-white at full activity.
export function glowColor(rate: number): string {
  const t = Math.max(0, Math.min(1, rate));
  const from = [70, 92, 76],
    to = [236, 255, 181];
  return `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * t)).join(',')})`;
}
