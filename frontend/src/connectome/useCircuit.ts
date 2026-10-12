import {useEffect, useState} from 'react';
import type {State} from '../types';
import type {CircuitSummary} from './layout';

const cache = new Map<string, CircuitSummary>();

// The cell-type view of the connectome circuit for the current parameters, fetched once
// per parameter set. Null while the engineered model is selected.
export function useCircuit(state: State | null): {circuit: CircuitSummary | null; error: string} {
  const active = state?.config.neural_model === 'connectome_dna02';
  const key = active ? JSON.stringify(state?.config.connectome_parameters) : '';
  const [circuit, setCircuit] = useState<CircuitSummary | null>(cache.get(key) ?? null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!active) return;
    const known = cache.get(key);
    if (known) {
      setCircuit(known);
      return;
    }
    let cancelled = false;
    fetch('/api/connectome/circuit')
      .then((r) => {
        if (!r.ok)
          throw Error(
            'The connectome circuit could not be loaded. Rebuild data/circuits with scripts/build_circuit.py.',
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
  return {circuit: active ? circuit : null, error};
}
