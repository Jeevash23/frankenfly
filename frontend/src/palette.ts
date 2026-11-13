// Matching and ranking for the command palette (Ctrl/Cmd+K): pages, actions and cell types.

export type PaletteKind = 'page' | 'action' | 'cell';
export type PaletteEntry = {
  id: string;
  kind: PaletteKind;
  label: string;
  // Shown beside the label: the page's section, an action's effect, a cell type's counts.
  hint: string;
  // More words that match, not shown.
  keywords?: string;
};

const words = (text: string) =>
  text
    .toLowerCase()
    .split(/[^a-z0-9&]+/i)
    .filter(Boolean);

// How well an entry matches the query, higher is better, or null when a query word is missing.
// Every query word must start a word of the label, hint or keywords (or occur in the label).
export function matchScore(entry: PaletteEntry, query: string): number | null {
  const terms = words(query);
  if (!terms.length) return 0;
  const label = entry.label.toLowerCase();
  const labelWords = words(entry.label);
  const otherWords = words(`${entry.hint} ${entry.keywords ?? ''}`);
  let score = 0;
  for (const term of terms) {
    if (labelWords.some((w) => w === term)) score += 6;
    else if (labelWords.some((w) => w.startsWith(term))) score += 4;
    else if (label.includes(term)) score += 2;
    else if (otherWords.some((w) => w.startsWith(term))) score += 1;
    else return null;
  }
  if (label.startsWith(query.trim().toLowerCase())) score += 3;
  return score;
}

const KIND_ORDER: Record<PaletteKind, number> = {page: 0, action: 1, cell: 2};

// The matching entries, best first; with an empty query, pages then actions in their given order.
export function rankEntries<T extends PaletteEntry>(entries: readonly T[], query: string): T[] {
  return entries
    .map((entry, index) => ({entry, index, score: matchScore(entry, query)}))
    .filter((r): r is {entry: T; index: number; score: number} => r.score !== null)
    .sort(
      (a, b) =>
        b.score - a.score ||
        KIND_ORDER[a.entry.kind] - KIND_ORDER[b.entry.kind] ||
        a.index - b.index,
    )
    .map((r) => r.entry);
}

// The cell-type search term: what follows "cell", "type" or nothing, at least two characters.
// Only names that look like FlyWire cell types (letters, digits, _ , -) are looked up.
export function cellQuery(query: string): string | null {
  const term = query.trim().replace(/^(cell\s*type|cell|type)\s+/i, '');
  return /^[A-Za-z0-9_.-]{2,40}$/.test(term) ? term : null;
}

// Moving the highlighted row with the arrow keys, wrapping at the ends.
export function moveSelection(index: number, count: number, key: string): number {
  if (!count) return 0;
  if (key === 'ArrowDown') return (index + 1) % count;
  if (key === 'ArrowUp') return (index - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return Math.min(index, count - 1);
}
