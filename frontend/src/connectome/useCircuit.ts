import {useCallback, useEffect, useState} from 'react';
import type {CircuitInfo, State} from '../types';
import type {CircuitSummary} from './layout';

const cache = new Map<string, CircuitSummary>();

// The cell-type view of the active connectome circuit for the current parameters, fetched
// once per parameter set. Null while the engineered model is selected.
export function useCircuit(state: State | null): {circuit: CircuitSummary | null; error: string} {
  const active = state?.config.neural_model === 'connectome';
  const key = active ? JSON.stringify(state?.config.connectome_parameters) : '';
  const [circuit, setCircuit] = useState<CircuitSummary | null>(cache.get(key) ?? null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!active) return;
    const known = cache.get(key);
    if (known) {
      setCircuit(known);
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
        cache.set(key, data);
        if (!cancelled) {
          setCircuit(data);
          setError('');
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [active, key]);
  // Only the summary for the current parameters: type indices differ between circuits.
  return {circuit: active && circuit ? (cache.get(key) ?? null) : null, error};
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
