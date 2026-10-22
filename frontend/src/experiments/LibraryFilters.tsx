import {ChevronDown, X} from 'lucide-react';
import type {CircuitInfo} from '../types';
import type {RunFilters} from '../library';

// The run library's filters (GET /api/runs model, circuit, batch, tag and q), combined with AND.
// Text fields apply after a short pause; the selects at once.
export function LibraryFilters({
  filters,
  change,
  circuits,
  problem,
  clear,
}: {
  filters: RunFilters;
  // `now` applies the change without waiting for typing to pause.
  change: (next: Partial<RunFilters>, now?: boolean) => void;
  circuits: CircuitInfo[];
  // Why the typed filters cannot be sent, or null.
  problem: string | null;
  // Shown while any filter is set.
  clear: (() => void) | null;
}) {
  const names = circuits.filter((c) => !c.error).map((c) => c.name);
  if (filters.circuit && !names.includes(filters.circuit)) names.unshift(filters.circuit);
  return (
    <form
      className="library-filters"
      role="search"
      aria-label="Filter saved runs"
      onSubmit={(e) => {
        e.preventDefault();
        change({}, true);
      }}
    >
      <label className="field-label">
        Model
        <div className="select-wrap">
          <select
            aria-label="Filter by model"
            value={filters.model}
            onChange={(e) => change({model: e.target.value as RunFilters['model']}, true)}
          >
            <option value="">Any model</option>
            <option value="engineered">Engineered</option>
            <option value="connectome">Connectome</option>
          </select>
          <ChevronDown size={13} />
        </div>
      </label>
      <label className="field-label">
        Circuit
        <div className="select-wrap">
          <select
            aria-label="Filter by circuit"
            value={filters.circuit}
            disabled={filters.model === 'engineered'}
            title="Connectome runs only"
            onChange={(e) => change({circuit: e.target.value}, true)}
          >
            <option value="">Any circuit</option>
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <ChevronDown size={13} />
        </div>
      </label>
      <label className="field-label">
        Comparison ID
        <input
          aria-label="Filter by comparison ID"
          value={filters.batch}
          placeholder="e.g. 3c0cb86dee80"
          onChange={(e) => change({batch: e.target.value})}
        />
      </label>
      <label className="field-label">
        Tag
        <input
          aria-label="Filter by tag"
          value={filters.tag}
          placeholder="e.g. pilot"
          onChange={(e) => change({tag: e.target.value})}
        />
      </label>
      <label className="field-label library-search">
        Search
        <input
          type="search"
          aria-label="Search runs"
          value={filters.q}
          placeholder="Run ID, notes or condition"
          onChange={(e) => change({q: e.target.value})}
        />
      </label>
      {clear && (
        <button type="button" className="text-button" onClick={clear}>
          <X size={12} />
          Clear filters
        </button>
      )}
      {problem && (
        <p className="microcopy library-filter-problem" role="status">
          {problem}
        </p>
      )}
    </form>
  );
}
