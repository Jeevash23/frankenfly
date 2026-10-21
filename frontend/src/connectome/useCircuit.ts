import {useCallback, useEffect, useState, useSyncExternalStore} from 'react';
import type {CircuitInfo, State} from '../types';
import {summaryKey} from '../models';
import type {CircuitSummary} from './layout';

const cache = new Map<string, CircuitSummary>();
let generation = 0;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

// Forget every cached summary and refetch the ones on screen: a build may have rewritten a circuit
// file under a name already in use.
export function invalidateCircuits() {
  cache.clear();
  generation += 1;
  listeners.forEach((listener) => listener());
}

// The cell-type view of the active connectome circuit, fetched once per circuit file and structural
// parameters (summaryKey). Null while the engineered model is selected, and while another circuit
// loads: type indices differ between circuits. While a new summary of the same circuit file loads
// (another threshold or population), the previous one stays on screen.
export function useCircuit(state: State | null): {
  circuit: CircuitSummary | null;
  error: string;
  loading: boolean;
} {
  const active = state?.config.neural_model === 'connectome';
  const parameters = state?.config.connectome_parameters;
  const sha256 = state?.connectome?.circuit_sha256;
  const key = active && parameters ? summaryKey(parameters, sha256) : '';
  // The first snapshot, before the body is ready, has no circuit block yet.
  const starting = state?.status === 'initializing';
  const version = useSyncExternalStore(subscribe, () => generation);
  const [shown, setShown] = useState<CircuitSummary | null>(cache.get(key) ?? null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!active || !parameters || starting) return;
    const known = cache.get(key);
    if (known) {
      setShown(known);
      setError('');
      return;
    }
    let cancelled = false;
    fetch('/api/connectome/circuit')
      .then((r) => {
        if (!r.ok)
          throw Error(
            'The connectome circuit could not be loaded. Rebuild it with scripts/build_circuit.py.',
          );
        return r.json();
      })
      .then((data: CircuitSummary) => {
        // The server answers for the circuit running now; drop an answer for one we moved away from.
        if (data.name !== parameters.circuit || (sha256 && data.sha256 !== sha256)) {
          if (!cancelled) setError('The circuit changed while it was loading. Reopen this tab.');
          return;
        }
        cache.set(key, data);
        if (!cancelled) {
          setShown(data);
          setError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [active, key, starting, version]);
  const cached = cache.get(key);
  const sameFile =
    !!shown && shown.name === parameters?.circuit && (!sha256 || shown.sha256 === sha256);
  return {
    circuit: active ? (cached ?? (sameFile ? shown : null)) : null,
    error,
    loading: active && !cached,
  };
}

// Every circuit the app can load, committed and locally built. `refresh` reloads the list.
export function useCircuitList(): {circuits: CircuitInfo[]; refresh: () => void; error: string} {
  const [circuits, setCircuits] = useState<CircuitInfo[]>([]);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/connectome/circuits')
      .then((r) => {
        if (!r.ok) throw Error('The circuit list could not be loaded.');
        return r.json();
      })
      .then((data: {circuits: CircuitInfo[]}) => {
        if (!cancelled) {
          setCircuits(data.circuits);
          setError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  return {circuits, refresh, error};
}
