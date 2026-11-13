import {useCallback, useEffect, useState} from 'react';

// Whether a media query matches, following changes (false where matchMedia is unavailable).
export function useMedia(query: string): boolean {
  const read = () => {
    try {
      return matchMedia(query).matches;
    } catch {
      return false;
    }
  };
  const [matches, setMatches] = useState(read);
  useEffect(() => {
    let list: MediaQueryList;
    try {
      list = matchMedia(query);
    } catch {
      return;
    }
    const changed = () => setMatches(list.matches);
    changed();
    list.addEventListener?.('change', changed);
    return () => list.removeEventListener?.('change', changed);
  }, [query]);
  return matches;
}

// A true/false preference kept in this browser's storage (when storage is available).
export function useStoredFlag(key: string): [boolean, () => void] {
  const [value, setValue] = useState(() => {
    try {
      return localStorage.getItem(key) === 'true';
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setValue((previous) => {
      try {
        localStorage.setItem(key, String(!previous));
      } catch {
        // Not stored; the change holds for this page.
      }
      return !previous;
    });
  }, [key]);
  return [value, toggle];
}
