import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  THEME_KEY,
  applyTheme,
  effectiveTheme,
  readTheme,
  toggledTheme,
  writeTheme,
} from '../src/theme.ts';

const memory = () => {
  const items = new Map();
  return {
    getItem: (k) => (items.has(k) ? items.get(k) : null),
    setItem: (k, v) => items.set(k, String(v)),
    removeItem: (k) => items.delete(k),
    items,
  };
};
const broken = {
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('QuotaExceededError');
  },
  removeItem: () => {
    throw new Error('SecurityError');
  },
};

test('the theme follows the system until one is chosen', () => {
  const store = memory();
  assert.equal(readTheme(store), 'system');
  assert.equal(effectiveTheme('system', 'dark'), 'dark');
  assert.equal(effectiveTheme('system', 'light'), 'light');
  writeTheme('dark', store);
  assert.equal(store.items.get(THEME_KEY), 'dark');
  assert.equal(readTheme(store), 'dark');
  assert.equal(effectiveTheme('dark', 'light'), 'dark');
  // Following the system again forgets the choice.
  writeTheme('system', store);
  assert.equal(store.items.has(THEME_KEY), false);
  assert.equal(readTheme(store), 'system');
});

test('the toggle flips what is on screen', () => {
  assert.equal(toggledTheme('system', 'light'), 'dark');
  assert.equal(toggledTheme('system', 'dark'), 'light');
  assert.equal(toggledTheme('dark', 'dark'), 'light');
  assert.equal(toggledTheme('light', 'dark'), 'dark');
});

test('storage that throws or holds nonsense never breaks the theme', () => {
  assert.equal(readTheme(broken), 'system');
  assert.doesNotThrow(() => writeTheme('dark', broken));
  assert.doesNotThrow(() => writeTheme('system', broken));
  assert.equal(readTheme(null), 'system');
  const store = memory();
  store.setItem(THEME_KEY, 'sepia');
  assert.equal(readTheme(store), 'system');
});

test('an explicit choice sets data-theme on the root; following the system removes it', () => {
  const root = {dataset: {}};
  applyTheme('dark', root);
  assert.equal(root.dataset.theme, 'dark');
  applyTheme('light', root);
  assert.equal(root.dataset.theme, 'light');
  applyTheme('system', root);
  assert.equal('theme' in root.dataset, false);
  assert.doesNotThrow(() => applyTheme('dark', null));
});

test('the pre-paint script reads the same key and guards its storage access', () => {
  const script = readFileSync(new URL('../public/theme-init.js', import.meta.url), 'utf8');
  assert.match(script, new RegExp(`localStorage\\.getItem\\('${THEME_KEY}'\\)`));
  assert.match(script, /try \{[\s\S]*\} catch/);
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  // Loaded as a file (the CSP forbids inline scripts), before the app.
  assert.ok(html.indexOf('/theme-init.js') < html.indexOf('/src/main.tsx'));
  assert.doesNotMatch(html, /<script>(?!<\/script>)/);
});
