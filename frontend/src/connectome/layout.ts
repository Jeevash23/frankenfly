// Pure helpers for the connectome circuit view. Positions encode hop distance to DNa02
// and laterality, not anatomy.

export type CircuitType = {
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
export type CircuitSummary = {
  name: string;
  sha256: string;
  neurons: number;
  connections_active: number;
  parameters: Record<string, number | string>;
  dna02: {left: string; right: string; type_index: number};
  provenance: Record<string, string>;
  citations: string[];
  types: CircuitType[];
  edges: TypeEdges;
  dna02_inputs: {left: SideEdges; right: SideEdges};
};
export type Node = {x: number; y: number; r: number};

export const VIEW = {width: 1000, height: 560, top: 58, bottom: 512};
const BANDS: Record<number, [number, number]> = {2: [36, 486], 1: [532, 812]};
export const DNA02_X = 912;

// Left-dominant types first, so they sit above right-dominant ones, like DNa02 L above R.
export function laterality(type: CircuitType): number {
  const sided = type.left + type.right;
  return sided ? type.right / sided : 0.5;
}

export function layoutTypes(types: CircuitType[], dna02Index: number): Map<number, Node> {
  const positions = new Map<number, Node>();
  const largest = Math.max(1, ...types.map((t) => t.count));
  for (const layer of [1, 2]) {
    const members = types
      .map((type, index) => ({type, index}))
      .filter(({type, index}) => index !== dna02Index && Math.min(type.layer, 2) === layer)
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

// For the dark anatomy canvas: dim green at rest, bright lime-white at full activity.
export function glowColor(rate: number): string {
  const t = Math.max(0, Math.min(1, rate));
  const from = [70, 92, 76],
    to = [236, 255, 181];
  return `rgb(${from.map((v, i) => Math.round(v + (to[i] - v) * t)).join(',')})`;
}
