// Light and dark themes. Without a stored choice the page follows the system (prefers-color-scheme);
// choosing one stores it in this browser and sets data-theme on <html>, which the tokens in
// style.css follow. public/theme-init.js applies the stored choice before the first paint.

export type ThemeChoice = 'light' | 'dark' | 'system';
export type Theme = 'light' | 'dark';
export const THEME_KEY = 'digitalfly.theme';

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const storage = (): StorageLike | null => {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
};

// The stored choice; 'system' when none is stored or storage is unavailable.
export function readTheme(store: StorageLike | null = storage()): ThemeChoice {
  try {
    const value = store?.getItem(THEME_KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

// Stores the choice; 'system' forgets it. Storage that throws (private windows, blocked site data)
// leaves the choice for this page only.
export function writeTheme(choice: ThemeChoice, store: StorageLike | null = storage()): void {
  try {
    if (choice === 'system') store?.removeItem(THEME_KEY);
    else store?.setItem(THEME_KEY, choice);
  } catch {
    // Not stored; the page still switches.
  }
}

export function systemTheme(): Theme {
  try {
    return globalThis.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export const effectiveTheme = (choice: ThemeChoice, system: Theme): Theme =>
  choice === 'system' ? system : choice;

// The header toggle flips what is on screen, and stores that as an explicit choice.
export const toggledTheme = (choice: ThemeChoice, system: Theme): Theme =>
  effectiveTheme(choice, system) === 'dark' ? 'light' : 'dark';

// data-theme on <html>: set for an explicit choice, absent when following the system.
export function applyTheme(
  choice: ThemeChoice,
  root: HTMLElement | null = globalThis.document?.documentElement ?? null,
) {
  if (!root) return;
  if (choice === 'system') delete root.dataset.theme;
  else root.dataset.theme = choice;
}
