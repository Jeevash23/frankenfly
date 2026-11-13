import test from 'node:test';
import assert from 'node:assert/strict';
import {cellQuery, matchScore, moveSelection, rankEntries} from '../src/palette.ts';
import {ROUTES} from '../src/route.ts';

const pages = ROUTES.map((r) => ({
  id: `page:${r.id}`,
  kind: 'page',
  label: r.label,
  hint: r.group,
  keywords: `${r.title} ${r.description} ${r.keywords}`,
}));
const actions = [
  {id: 'action:run', kind: 'action', label: 'Run the simulation', hint: 'Workbench · Space'},
  {
    id: 'action:theme',
    kind: 'action',
    label: 'Switch to the dark theme',
    hint: 'Appearance',
    keywords: 'theme dark light mode',
  },
  {
    id: 'action:score',
    kind: 'action',
    label: 'Score the Workbench model',
    hint: 'Validation scorecard',
  },
];
const entries = [...pages, ...actions];
const ids = (query) => rankEntries(entries, query).map((e) => e.id);

test('an empty query lists every page, then the actions, in their order', () => {
  assert.deepEqual(
    ids(''),
    entries.map((e) => e.id),
  );
});

test('pages are found by name, section and what they hold', () => {
  assert.equal(ids('library')[0], 'page:library');
  assert.equal(ids('run lib')[0], 'page:library');
  assert.equal(ids('explorer')[0], 'page:explorer');
  assert.equal(ids('nwb')[0], 'page:library');
  assert.equal(ids('mcp')[0], 'page:agents');
  assert.ok(ids('scorecard').slice(0, 2).includes('page:scorecard'));
  assert.ok(ids('jobs').includes('page:jobs'));
});

test('actions are found by their words; a missing word rules an entry out', () => {
  assert.equal(ids('dark')[0], 'action:theme');
  assert.equal(ids('run sim')[0], 'action:run');
  assert.deepEqual(ids('zzz'), []);
  assert.equal(matchScore(actions[0], 'run nonsense'), null);
  // A whole-word match beats a prefix, which beats a match in the hint.
  assert.ok(matchScore(actions[0], 'run') > matchScore(actions[0], 'ru'));
  assert.ok(matchScore(actions[0], 'simulation') > matchScore(actions[0], 'space'));
});

test('cell types are looked up for names that look like FlyWire types', () => {
  assert.equal(cellQuery('DNa02'), 'DNa02');
  assert.equal(cellQuery('  cell LC10a '), 'LC10a');
  assert.equal(cellQuery('type DNp09'), 'DNp09');
  assert.equal(cellQuery('D'), null);
  assert.equal(cellQuery('run the simulation'), null);
  assert.equal(cellQuery(''), null);
});

test('the highlighted row moves with the arrows and wraps', () => {
  assert.equal(moveSelection(0, 3, 'ArrowDown'), 1);
  assert.equal(moveSelection(2, 3, 'ArrowDown'), 0);
  assert.equal(moveSelection(0, 3, 'ArrowUp'), 2);
  assert.equal(moveSelection(1, 3, 'Home'), 0);
  assert.equal(moveSelection(1, 3, 'End'), 2);
  assert.equal(moveSelection(5, 3, 'x'), 2);
  assert.equal(moveSelection(4, 0, 'ArrowDown'), 0);
});
