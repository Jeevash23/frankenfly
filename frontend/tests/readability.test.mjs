import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {AA_SMALL_TEXT, contrastRatio, luminance, themeTokens} from '../src/contrast.ts';

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const sheets = [
  'style.css',
  'research.css',
  'connectome/connectome.css',
  'shell.css',
  'responsive.css',
];
const style = read('style.css');
const themes = themeTokens(style);
const tokens = themes.light;

test('the contrast helper follows WCAG 2', () => {
  assert.equal(luminance('#000'), 0);
  assert.equal(luminance('#ffffff'), 1);
  assert.equal(contrastRatio('#000000', '#fff').toFixed(1), '21.0');
  assert.equal(contrastRatio('#777', '#777'), 1);
  assert.equal(contrastRatio('#767676', '#ffffff').toFixed(2), '4.54'); // the familiar AA grey
  assert.equal(contrastRatio('#a2a993', '#fbfbf7') < AA_SMALL_TEXT, true); // v0.5 microcopy
  assert.throws(() => luminance('green'), /Not a #rgb/);
});

// Small text inks, and the surfaces they sit on, in each theme.
const INKS = [
  '--ink-strong',
  '--ink-heading',
  '--ink-green',
  '--ink-muted',
  '--ink-micro',
  '--ink-footnote',
  '--ink-eyebrow',
  '--ink-label',
  '--ink-warning',
  '--ink-error',
];
const SURFACES = ['--paper', '--canvas', '--surface', '--surface-2', '--field', '--accent-wash'];

for (const theme of ['light', 'dark'])
  test(`small-text inks reach 4.5:1 on every surface in the ${theme} theme`, () => {
    const t = themes[theme];
    for (const name of INKS)
      for (const background of SURFACES) {
        const ratio = contrastRatio(t[name], t[background]);
        assert.ok(
          ratio >= AA_SMALL_TEXT,
          `${theme}: ${name} on ${background}: ${ratio.toFixed(2)}:1`,
        );
      }
    // Warnings and errors also sit on their tinted notes, and buttons carry text on the accent.
    assert.ok(contrastRatio(t['--ink-warning'], t['--note-warn-bg']) >= AA_SMALL_TEXT);
    assert.ok(contrastRatio(t['--ink-error'], t['--note-error-bg']) >= AA_SMALL_TEXT);
    assert.ok(contrastRatio(t['--on-accent'], t['--green']) >= AA_SMALL_TEXT);
    // Chips and status pills put muted ink on the deeper surfaces.
    for (const background of ['--surface-3'])
      assert.ok(contrastRatio(t['--ink-muted'], t[background]) >= AA_SMALL_TEXT);
  });

test('the light theme keeps the notes it always had', () => {
  assert.equal(tokens['--note-warn-bg'], '#fbf6ea');
  assert.equal(tokens['--note-error-bg'], '#f4e9df');
  for (const [rule, token] of [
    ['.microcopy', '--ink-micro'],
    ['.panel-footnote', '--ink-footnote'],
    ['.eyebrow', '--ink-eyebrow'],
  ])
    assert.match(
      style,
      new RegExp(`\\n\\${rule} \\{[^}]*color: var\\(${token}\\)`),
      `${rule} uses ${token}`,
    );
});

test('the dark theme is declared twice, identically, and covers every colour token', () => {
  assert.ok(Object.keys(themes.dark).length > 40);
  assert.deepEqual(themes.darkMedia, themes.dark);
  const colours = Object.entries(tokens).filter(([, v]) => /^#|^url\(/.test(v));
  for (const [name] of colours) assert.ok(name in themes.dark, `${name} has a dark value`);
  for (const name of Object.keys(themes.dark))
    assert.ok(name in tokens, `${name} is a light token`);
  assert.match(style, /:root \{[^}]*color-scheme: light/);
  assert.match(themes.dark['--canvas'], /^#/);
  assert.ok(luminance(themes.dark['--canvas']) < 0.02, 'the dark canvas is dark');
});

test('stylesheets use theme tokens, not light-only colours, for surfaces, lines and text', () => {
  // Light colours (luminance above 0.6) written directly would stay light in the dark theme. Only
  // the token blocks may hold them; everything else refers to a token.
  const problems = [];
  for (const sheet of sheets) {
    const css = read(sheet)
      .replace(/:root[^{]*\{[^}]*\}/g, '')
      .replace(/@media \(prefers-color-scheme: dark\)\s*\{\s*:root[^{]*\{[^}]*\}\s*\}/g, '');
    for (const [, prop, value] of css.matchAll(/\n\s*([\w-]+):\s*([^;{}]*);/g))
      for (const hex of value.match(/#[0-9a-f]{6}\b|#[0-9a-f]{3}\b/gi) ?? [])
        if (luminance(hex) > 0.6) problems.push(`${sheet}: ${prop}: ${value}`);
  }
  assert.deepEqual(problems, []);
});

// Running text is at least --text-min (11 px); only these decorations may be smaller, and never
// below --text-deco (10 px).
const DECORATIONS =
  /\.eyebrow|\.mini-badge|\.section-no|\.viewport-label|\.version|\.map-axis|\.y-labels|\.x-labels|\.timeline-start|\.timeline-end|\.timeline-marker span|\.run-button kbd|\.connectome-labels span|\.brain-view-label|\.retina-side|\.gait-grid svg text|\.type-label|\.intervention-count|\.event-row small|\.trace-legend \.unit|\.run-tag/;

function fontSizes(css) {
  const found = [];
  const context = [];
  let start = 0;
  for (const match of css.matchAll(/[{};]/g)) {
    const chunk = css.slice(start, match.index);
    if (match[0] === '{') context.push(chunk.trim().replace(/\s+/g, ' '));
    else if (match[0] === '}') context.pop();
    else {
      const size = chunk.match(/^\s*font(?:-size)?:\s*(?:\d{3}\s+)?(var\(--[\w-]+\)|[\d.]+px)/);
      if (size) found.push({selector: context.at(-1) ?? '', size: size[1]});
    }
    start = match.index + 1;
  }
  return found;
}
const px = (size) => parseFloat(size.startsWith('var(') ? tokens[size.slice(4, -1)] : size);

test('text has an 11 px floor; only decorations go down to 10 px', () => {
  assert.equal(px('var(--text-min)'), 11);
  assert.equal(px('var(--text-deco)'), 10);
  const problems = [];
  for (const sheet of sheets)
    for (const {selector, size} of fontSizes(read(sheet))) {
      const value = px(size);
      if (value < 10 || (value < 11 && !DECORATIONS.test(selector)))
        problems.push(`${sheet}: ${selector} ${size}`);
    }
  assert.deepEqual(problems, []);
});

test('every width-dependent rule lives in responsive.css', () => {
  for (const sheet of ['style.css', 'research.css', 'connectome/connectome.css', 'shell.css']) {
    assert.doesNotMatch(read(sheet), /@media[^{]*width/, `${sheet} has a width media query`);
    assert.doesNotMatch(read(sheet), /@container/, `${sheet} has a container query`);
  }
  // Page content follows the page column (container queries); the shell follows the window.
  assert.match(read('shell.css'), /main \{[^}]*container: page \/ inline-size/);
  assert.match(read('responsive.css'), /@container page \(max-width/);
  assert.match(read('responsive.css'), /@media \(max-width: 820px\)/);
  assert.match(read('../src/main.tsx'), /import App from '.\/App';\nimport '.\/responsive.css';/);
  // Leg force and phase readouts stay visible at every width.
  assert.doesNotMatch(read('responsive.css'), /\.leg-readouts \{\s*display: none/);
});
