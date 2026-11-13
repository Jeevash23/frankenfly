import {useEffect, useMemo, useRef, useState} from 'react';
import {CornerDownLeft, Network, Search, Zap} from 'lucide-react';
import {request} from '../api';
import {cellQuery, moveSelection, rankEntries, type PaletteEntry} from '../palette';
import type {RouteId} from '../route';
import {ROUTE_ICONS} from './icons';

export type PaletteCommand = PaletteEntry & {run: () => void; route?: RouteId};

type Graphs = {graphs: {key: string; available: boolean}[]; running: string | null};
type Lookup = {
  matches: {kind: string; cell_type: string; neurons?: number; left?: number; right?: number}[];
};

// The graph cell types are looked up in: the whole brain when prepared, else the running circuit.
function useLookupGraph(): string | null {
  const [graph, setGraph] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void request<Graphs>('GET', '/api/explore/graphs').then((r) => {
      if (cancelled || !r.ok) return;
      const usable = r.data.graphs.filter((g) => g.available);
      setGraph(
        (
          usable.find((g) => g.key === 'brain') ??
          usable.find((g) => g.key === r.data.running) ??
          usable[0]
        )?.key ?? null,
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return graph;
}

// Cell types whose names start like the query, as palette entries.
function useCellMatches(graph: string | null, query: string): PaletteEntry[] {
  const [cells, setCells] = useState<PaletteEntry[]>([]);
  const term = cellQuery(query);
  useEffect(() => {
    if (!graph || !term) return setCells([]);
    let cancelled = false;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({graph, q: term, limit: '8'});
      void request<Lookup>('GET', `/api/explore/lookup?${params}`).then((r) => {
        if (cancelled || !r.ok) return;
        setCells(
          r.data.matches
            .filter((m) => m.kind !== 'neuron')
            .slice(0, 6)
            .map((m) => ({
              id: `cell:${m.cell_type}`,
              kind: 'cell' as const,
              label: m.cell_type,
              hint:
                m.neurons !== undefined
                  ? `Cell type · ${m.neurons} neurons · ${m.left ?? 0} L / ${m.right ?? 0} R`
                  : 'Cell type',
              keywords: term,
            })),
        );
      });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [graph, term]);
  return cells;
}

// Ctrl/Cmd+K: jump to a page, run a common action, or open a cell type in the explorer.
export function CommandPalette({
  commands,
  openCell,
  close,
}: {
  commands: PaletteCommand[];
  openCell: (cellType: string) => void;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const graph = useLookupGraph();
  const cells = useCellMatches(graph, query);
  const results = useMemo((): PaletteCommand[] => {
    const ranked = rankEntries(commands, query).slice(0, 12);
    // Cell types the lookup found match by name already; they follow the pages and actions.
    return [...ranked, ...cells.map((c) => ({...c, run: () => openCell(c.label)}))];
  }, [commands, cells, query, openCell]);
  useEffect(() => {
    dialog.current?.showModal();
    input.current?.focus();
  }, []);
  useEffect(() => setIndex(0), [query]);
  useEffect(() => {
    document.getElementById(`palette-option-${index}`)?.scrollIntoView({block: 'nearest'});
  }, [index]);
  const choose = (i: number) => {
    const entry = results[i];
    if (!entry) return;
    close();
    entry.run();
  };
  return (
    <dialog
      ref={dialog}
      className="palette"
      aria-label="Command palette"
      onClose={close}
      onClick={(e) => {
        if (e.target === dialog.current) close();
      }}
    >
      <div className="palette-input">
        <Search size={16} aria-hidden />
        <input
          ref={input}
          role="combobox"
          aria-label="Search pages, actions and cell types"
          aria-expanded={results.length > 0}
          aria-controls="palette-list"
          aria-autocomplete="list"
          aria-activedescendant={results.length ? `palette-option-${index}` : undefined}
          placeholder="Search pages, actions and cell types…"
          spellCheck={false}
          autoComplete="off"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              choose(index);
            } else if (
              ['ArrowDown', 'ArrowUp'].includes(e.key) ||
              (e.ctrlKey && /^[np]$/.test(e.key))
            ) {
              e.preventDefault();
              const key = e.key === 'n' ? 'ArrowDown' : e.key === 'p' ? 'ArrowUp' : e.key;
              setIndex((i) => moveSelection(i, results.length, key));
            }
          }}
        />
        <kbd>Esc</kbd>
      </div>
      <ul id="palette-list" role="listbox" aria-label="Results" className="palette-list">
        {results.map((entry, i) => {
          const Icon = entry.route
            ? ROUTE_ICONS[entry.route]
            : entry.kind === 'cell'
              ? Network
              : Zap;
          return (
            <li
              key={entry.id}
              id={`palette-option-${i}`}
              role="option"
              aria-selected={i === index}
              className={`palette-option ${entry.kind}`}
              onMouseMove={() => i !== index && setIndex(i)}
              onClick={() => choose(i)}
            >
              <Icon size={15} aria-hidden />
              <span className="palette-label">{entry.label}</span>
              <span className="palette-hint">{entry.hint}</span>
              {i === index && <CornerDownLeft size={13} className="palette-enter" aria-hidden />}
            </li>
          );
        })}
        {!results.length && (
          <li className="palette-empty" role="presentation">
            {cellQuery(query) && !graph
              ? 'Nothing matches. Cell types are searched once the FlyWire graph is prepared.'
              : 'Nothing matches.'}
          </li>
        )}
      </ul>
      <div className="palette-footer" aria-hidden>
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> move
        </span>
        <span>
          <kbd>↵</kbd> open
        </span>
        <span>Type a cell type, such as DNa02, to open it in the explorer</span>
      </div>
    </dialog>
  );
}
