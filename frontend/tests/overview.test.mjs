import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MODEL_CAVEAT,
  otherScores,
  recentJobs,
  runTitle,
  scoreChips,
  timeAgo,
} from '../src/overview/summary.ts';

const job = (id, status) => ({id, status, kind: 'build', label: id});

test('running and waiting jobs come first, then the newest finished ones', () => {
  const jobs = [job('a', 'done'), job('b', 'running'), job('c', 'failed'), job('d', 'queued')];
  assert.deepEqual(
    recentJobs(jobs, 3).map((j) => j.id),
    ['b', 'd', 'a'],
  );
  assert.deepEqual(recentJobs([], 5), []);
});

test('a saved run is named by its comparison condition, its tags, or as a Workbench run', () => {
  assert.equal(
    runTitle({condition: 'left_sensor_off', trial: {condition: 'x', seed: 43}, tags: []}),
    'left_sensor_off · seed 43',
  );
  assert.equal(runTitle({condition: null, trial: null, tags: ['pilot', 'dark']}), 'pilot, dark');
  assert.equal(runTitle({condition: null, trial: null, tags: []}), 'Workbench run');
});

test('a scorecard shows pass, partial and fail counts, in that order', () => {
  const card = {summary: {pass: 4, partial: 1, fail: 0, inconclusive: 2, scored: 7, text: ''}};
  assert.deepEqual(scoreChips(card), [
    {status: 'pass', count: 4},
    {status: 'partial', count: 1},
    {status: 'fail', count: 0},
  ]);
  // The rest are counted together.
  assert.equal(otherScores(card), 2);
  assert.equal(otherScores({summary: {...card.summary, not_testable: 3, blocked: 1, error: 1}}), 7);
});

test('times read as how long ago they were', () => {
  const now = Date.parse('2026-11-13T12:00:00Z');
  assert.equal(timeAgo('2026-11-13T11:59:30Z', now), 'just now');
  assert.equal(timeAgo('2026-11-13T11:15:00Z', now), '45 min ago');
  assert.equal(timeAgo('2026-11-13T09:00:00Z', now), '3 h ago');
  assert.equal(timeAgo('2026-11-12T09:00:00Z', now), '1 day ago');
  assert.equal(timeAgo('2026-11-08T12:00:00Z', now), '5 days ago');
  assert.equal(timeAgo('not a date', now), '—');
});

test('the model caveat says results belong to the models', () => {
  assert.match(MODEL_CAVEAT, /properties of these models, not fly biology/);
});
