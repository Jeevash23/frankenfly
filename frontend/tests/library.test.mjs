import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activeFilters,
  annotationProblem,
  deleteBlock,
  filterProblem,
  libraryCaption,
  mergeRuns,
  noFilters,
  PAGE,
  parseTags,
  readRunPage,
  replaceRun,
  runsQuery,
} from '../src/library.ts';

const run = (key) => ({key, samples: 10});

test('library pages ask the server for an offset, a capped limit and the empty-run filter', () => {
  const query = new URL(runsQuery(200, false), 'http://localhost').searchParams;
  assert.equal(query.get('offset'), '200');
  assert.equal(query.get('limit'), String(PAGE));
  assert.equal(query.get('include_empty'), 'false');
  assert.equal(
    new URL(runsQuery(0, true, 2000), 'http://localhost').searchParams.get('limit'),
    '500',
  );
});

test('a page is read with X-Total-Count, or without it from an older server', () => {
  assert.deepEqual(readRunPage({runs: [run('a'), run('b')]}, '240'), {
    runs: [run('a'), run('b')],
    total: 240,
  });
  // Servers before v0.6 send no header.
  assert.deepEqual(readRunPage({runs: [run('a')]}, null), {runs: [run('a')], total: null});
  assert.deepEqual(readRunPage({detail: 'x'}, 'many'), {runs: [], total: null});
});

test('runs of the live run and of a running comparison cannot be deleted', () => {
  const live = {key: '20261021T084700-abcdef12-1a2b3c', trial: null};
  assert.match(deleteBlock(live, '20261021T084700-abcdef12', null), /current run/);
  assert.equal(deleteBlock(live, '20261021T090000-00000000', null), null);
  const trial = {key: 'k', trial: {condition: 'control', batch_id: 'b1', seed: 42}};
  assert.match(deleteBlock(trial, 'other', 'b1'), /comparison/);
  assert.equal(deleteBlock(trial, 'other', null), null); // finished comparisons can be pruned
  assert.equal(deleteBlock(trial, undefined, 'b2'), null);
});

test('loading more skips runs already listed and the caption says how many are shown', () => {
  assert.deepEqual(
    mergeRuns([run('c'), run('b')], [run('b'), run('a')]).map((r) => r.key),
    ['c', 'b', 'a'],
  );
  assert.equal(libraryCaption(100, 240), 'Showing 100 of 240 runs');
  assert.equal(libraryCaption(1, 1), 'Showing 1 of 1 run');
  assert.equal(libraryCaption(100, null), 'Showing newest 100 runs');
});

test('filters go to the server trimmed, and empty ones are left out', () => {
  const filters = {...noFilters, model: 'connectome', circuit: 'fafb783-dna02', tag: ' pilot '};
  assert.deepEqual(activeFilters(filters), {
    model: 'connectome',
    circuit: 'fafb783-dna02',
    tag: 'pilot',
  });
  const query = new URL(runsQuery(100, false, PAGE, filters), 'http://localhost').searchParams;
  assert.equal(query.get('offset'), '100'); // paging still applies, after the filters
  assert.equal(query.get('model'), 'connectome');
  assert.equal(query.get('circuit'), 'fafb783-dna02');
  assert.equal(query.get('tag'), 'pilot');
  assert.equal(query.has('q'), false);
  assert.equal(query.has('batch'), false);
  assert.equal(
    new URL(runsQuery(0, true), 'http://localhost').searchParams.toString(),
    'offset=0&limit=100&include_empty=true',
  );
  assert.equal(libraryCaption(3, 3, true), 'Showing 3 of 3 matching runs');
  assert.equal(libraryCaption(1, 1, true), 'Showing 1 of 1 matching run');
});

test('filters the server would refuse are explained instead of sent', () => {
  assert.equal(filterProblem(noFilters), null);
  assert.equal(filterProblem({...noFilters, tag: 'LC10 sweep', batch: '3c0cb86dee80'}), null);
  assert.match(filterProblem({...noFilters, tag: 'a/b'}), /tag/);
  assert.match(filterProblem({...noFilters, tag: 'x'.repeat(25)}), /up to 24/);
  assert.match(filterProblem({...noFilters, batch: 'not a batch'}), /comparison ID/);
  assert.match(filterProblem({...noFilters, q: 'x'.repeat(201)}), /200 characters/);
});

test('tags and notes follow the server rules, as sentences', () => {
  assert.deepEqual(parseTags(' pilot, LC10 sweep ,, '), ['pilot', 'LC10 sweep']);
  assert.deepEqual(parseTags(''), []);
  assert.equal(annotationProblem(['pilot', 'LC10 sweep', 'a_b-c'], 'notes'), null);
  assert.equal(annotationProblem([], ''), null); // clearing both is allowed
  assert.match(annotationProblem(['ok', 'not/ok'], ''), /“not\/ok” is not a tag/);
  assert.match(annotationProblem(['x'.repeat(25)], ''), /up to 24/);
  const eleven = Array.from({length: 11}, (_, i) => 't' + i);
  assert.match(annotationProblem(eleven, ''), /at most 10/);
  assert.match(annotationProblem(['Pilot', 'pilot'], ''), /once: “pilot”/);
  assert.equal(annotationProblem([], 'x'.repeat(2000)), null);
  assert.match(annotationProblem([], 'x'.repeat(2001)), /2,000 characters \(now 2,001\)/);
});

test('a saved annotation replaces its run in place', () => {
  const shown = [
    {key: 'b', tags: [], notes: '', trajectory: [[0, 0, 0, 0]]},
    {key: 'a', tags: [], notes: ''},
  ];
  const updated = replaceRun(shown, {key: 'b', tags: ['pilot'], notes: 'n'});
  assert.deepEqual(
    updated.map((r) => r.key),
    ['b', 'a'],
  );
  assert.deepEqual(updated[0], {key: 'b', tags: ['pilot'], notes: 'n', trajectory: [[0, 0, 0, 0]]});
  assert.equal(updated[1], shown[1]);
});
