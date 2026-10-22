import type {KeyboardEvent} from 'react';

// Arrow-key movement along a row of tabs: the tab to select for a key, or null for other keys.
export function tabTarget<T>(tabs: readonly T[], current: T, key: string): T | null {
  const n = tabs.length;
  const i = Math.max(0, tabs.indexOf(current));
  if (!n) return null;
  if (key === 'ArrowRight') return tabs[(i + 1) % n];
  if (key === 'ArrowLeft') return tabs[(i - 1 + n) % n];
  if (key === 'Home') return tabs[0];
  if (key === 'End') return tabs[n - 1];
  return null;
}

// Keyboard handler for a role="tablist" whose tabs carry data-tab: selects the target tab and moves
// focus to it (automatic activation).
export function tabKeys<T extends string>(
  tabs: readonly T[],
  current: T,
  select: (tab: T) => void,
) {
  return (e: KeyboardEvent<HTMLElement>) => {
    const next = tabTarget(tabs, current, e.key);
    if (next === null) return;
    e.preventDefault();
    select(next);
    e.currentTarget.querySelector<HTMLElement>(`[data-tab="${next}"]`)?.focus();
  };
}
