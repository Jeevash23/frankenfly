import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {AA_SMALL_TEXT, contrastRatio, luminance, rootTokens} from '../src/contrast.ts';

const read = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const sheets = ['style.css', 'research.css', 'connectome/connectome.css', 'responsive.css'];
const style = read('style.css');
const tokens = rootTokens(style);

test('the contrast helper follows WCAG 2', () => {
  assert.equal(luminance('#000'), 0);
  assert.equal(luminance('#ffffff'), 1);
  assert.equal(contrastRatio('#000000', '#fff').toFixed(1), '21.0');
  assert.equal(contrastRatio('#777', '#777'), 1);
  assert.equal(contrastRatio('#767676', '#ffffff').toFixed(2), '4.54'); // the familiar AA grey
  assert.equal(contrastRatio('#a2a993', '#fbfbf7') < AA_SMALL_TEXT, true); // v0.5 microcopy
  assert.throws(() => luminance('green'), /Not a #rgb/);
});

test('microcopy, footnote, eyebrow and label inks reach 4.5:1 on paper and canvas', () => {
  for (const name of [
    '--ink-micro',
    '--ink-footnote',
    '--ink-eyebrow',
    '--ink-label',
    '--ink-warning',
    '--ink-error',
  ])
    for (const background of ['--paper', '--canvas']) {
      const ratio = contrastRatio(tokens[name], tokens[background]);
      assert.ok(ratio >= AA_SMALL_TEXT, `${name} on ${background}: ${ratio.toFixed(2)}:1`);
    }
  // Warnings and errors also sit on their tinted notes.
  assert.ok(contrastRatio(tokens['--ink-warning'], '#fbf6ea') >= AA_SMALL_TEXT);
  assert.ok(contrastRatio(tokens['--ink-error'], '#f4e9df') >= AA_SMALL_TEXT);
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
  for (const sheet of ['style.css', 'research.css', 'connectome/connectome.css'])
    assert.doesNotMatch(read(sheet), /@media[^{]*width/, `${sheet} has a width media query`);
  assert.match(read('../src/main.tsx'), /import App from '.\/App';\nimport '.\/responsive.css';/);
  // Leg force and phase readouts stay visible at every width.
  assert.doesNotMatch(read('responsive.css'), /\.leg-readouts \{\s*display: none/);
});
