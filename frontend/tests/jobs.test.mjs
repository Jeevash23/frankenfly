import test from 'node:test';
import assert from 'node:assert/strict';
import {
  errorText,
  finishedReplays,
  jobActive,
  jobStatus,
  replayJob,
  verificationBadge,
} from '../src/jobs.ts';
import {presetConfig, presetOption, presetProblem, runInProgress} from '../src/presets.ts';
import {nudgeTarget} from '../src/plot.ts';
import {describeError} from '../src/errors.ts';

const job = (id, status, extra = {}) => ({
  id,
  kind: 'replay',
  status,
  label: `Replay ${id}`,
  target: `run-${id}`,
  progress: null,
  error: null,
  ...extra,
});

test('replay jobs: newest per run, active states and finished checks', () => {
  const jobs = [
    job('b', 'running', {target: 'run-x', progress: 0.42}),
    job('a', 'done', {target: 'run-x'}),
  ];
  assert.equal(replayJob(jobs, 'run-x').id, 'b');
  assert.equal(replayJob(jobs, 'run-y'), null);
  assert.equal(replayJob([job('c', 'done', {kind: 'build', target: 'run-y'})], 'run-y'), null);
  assert.deepEqual(
    ['queued', 'running', 'done', 'failed', 'cancelled'].map((s) => jobActive({status: s})),
    [true, true, false, false, false],
  );
  assert.equal(jobStatus(jobs[0]), 'running · 42%');
  assert.equal(
    jobStatus(job('d', 'failed', {error: 'The circuit changed.'})),
    'failed: The circuit changed.',
  );
  // Finished since the last listing: was active, or was not listed yet (a quick check).
  const before = [job('a', 'running'), job('old', 'done')];
  const after = [job('new', 'done'), job('a', 'done'), job('old', 'done'), job('q', 'queued')];
  assert.deepEqual(finishedReplays(before, after), ['run-new', 'run-a']);
  assert.deepEqual(finishedReplays(after, after), []);
});

test('verified badges: match, mismatch with its error, software differences', () => {
  assert.equal(verificationBadge(null), null);
  const verdict = {
    ok: true,
    max_abs_error: 0,
    tolerance: 1e-8,
    checked: '2026-10-21T15:00:19+00:00',
    same_software: true,
    message: 'Replayed 31 samples.',
  };
  const ok = verificationBadge(verdict);
  assert.deepEqual([ok.ok, ok.text, ok.note], [true, '✓ verified', null]);
  assert.match(ok.title, /^Replayed 31 samples\. Checked /);
  const bad = verificationBadge({
    ...verdict,
    ok: false,
    max_abs_error: 3.2e-5,
    same_software: false,
  });
  assert.deepEqual(
    [bad.ok, bad.text, bad.note],
    [false, '✗ mismatch · max error 3.2e-5', 'software differs'],
  );
  assert.equal(errorText(Infinity), 'Infinity');
});

test('preset names are checked before saving; loading asks during a run', () => {
  const presets = [
    {name: 'default', source: 'shipped'},
    {name: 'mine', source: 'local'},
  ];
  assert.equal(presetProblem('steering-seed-7', '', presets), null);
  assert.equal(presetProblem('mine', '', presets), null); // replaces the local one
  assert.match(presetProblem('My Setup', '', presets), /lowercase/);
  assert.match(presetProblem('-x', '', presets), /starting with a letter/);
  assert.match(presetProblem('a'.repeat(49), '', presets), /48 characters/);
  assert.match(presetProblem('default', '', presets), /shipped/);
  assert.match(presetProblem('ok', 'x'.repeat(201), presets), /200 characters/);
  assert.equal(runInProgress(null), false);
  assert.equal(runInProgress({status: 'paused', sample: {step: 0}}), false);
  assert.equal(runInProgress({status: 'paused', sample: {step: 12}}), true);
  assert.equal(runInProgress({status: 'running', sample: null}), true);
  assert.equal(
    presetOption({name: 'flyvis-eyes', source: 'shipped', available: false}),
    'flyvis-eyes · unavailable',
  );
  assert.equal(presetOption({name: 'mine', source: 'local', available: true}), 'mine (saved here)');
});

test('current settings keep the interventions in force, unless a protocol schedules them', () => {
  const live = {zero_left: true};
  const config = {seed: 7, protocol: null, initial_interventions: {zero_left: false}};
  assert.equal(presetConfig({config, interventions: live}).initial_interventions, live);
  const scheduled = {...config, protocol: {name: 'p', duration_steps: 10, events: []}};
  assert.equal(presetConfig({config: scheduled, interventions: live}), scheduled);
});

test('arrow keys nudge the target 1 mm, 5 mm with Shift, inside the arena', () => {
  assert.deepEqual(nudgeTarget({x: 12, y: 8}, 'ArrowRight', false), {x: 13, y: 8});
  assert.deepEqual(nudgeTarget({x: 12, y: 8}, 'ArrowDown', true), {x: 12, y: 3});
  assert.deepEqual(nudgeTarget({x: 39.5, y: -38}, 'ArrowRight', true), {x: 40, y: -38});
  assert.deepEqual(nudgeTarget({x: 0.1, y: 0.2}, 'ArrowLeft', false), {x: -0.9, y: 0.2});
  assert.equal(nudgeTarget({x: 0, y: 0}, 'Enter', false), null);
  assert.equal(nudgeTarget({x: 0, y: 0}, 'toString', false), null);
});

test('nested validation locations read as words', () => {
  const detail = [
    {
      location: ['body', 'custom_conditions', 0, 'label'],
      message: 'String should have at most 40 characters',
    },
  ];
  assert.equal(
    describeError(detail, 422),
    'custom conditions 1 › label: String should have at most 40 characters',
  );
});
