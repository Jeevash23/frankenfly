import test from 'node:test';
import assert from 'node:assert/strict';
import {libraryCaption, mergeRuns, PAGE, readRunPage, runsQuery} from '../src/library.ts';

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

test('a page is read from a list with X-Total-Count, or from an older server without one', () => {
  assert.deepEqual(readRunPage([run('a'), run('b')], '240'), {
    runs: [run('a'), run('b')],
    total: 240,
  });
  // Servers before v0.6: {runs: [...]} and no header.
  assert.deepEqual(readRunPage({runs: [run('a')]}, null), {runs: [run('a')], total: null});
  assert.deepEqual(readRunPage({detail: 'x'}, 'many'), {runs: [], total: null});
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
