import {useEffect, useRef} from 'react';
import {saveDraft} from './localDrafts';

// Saves `value` under `key` whenever it changes after the first render (see localDrafts.ts).
export function useLocalDraft(key: string, value: unknown) {
  const mounted = useRef(false);
  const json = JSON.stringify(value);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    saveDraft(key, value);
  }, [key, json]);
}
