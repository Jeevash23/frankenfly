import test from 'node:test';
import assert from 'node:assert/strict';
import {eyeImageUrl, isNewer} from '../src/snapshot.ts';
import {throttled} from '../src/draft.ts';
import {tabTarget} from '../src/keys.ts';

const snapshot = (revision, extra = {}) => ({
  instance_id: 'a',
  revision,
  status: 'paused',
  error: null,
  ...extra,
});

test('snapshots with an unchanged revision are skipped, unless their status changed', () => {
  assert.equal(isNewer(null, snapshot(3)), true);
  assert.equal(isNewer(snapshot(3), snapshot(4)), true);
  assert.equal(isNewer(snapshot(4), snapshot(3)), false);
  assert.equal(isNewer(snapshot(4), snapshot(4)), false); // paused: nothing to re-render
  assert.equal(isNewer(snapshot(4), snapshot(1, {instance_id: 'b'})), true); // server restart
  // A failed worker marks its last snapshot as an error without a new revision.
  assert.equal(isNewer(snapshot(4), snapshot(4, {status: 'error', error: 'Worker failed'})), true);
});

test('the eye image is refetched for a new sample, run or target, not for every snapshot', () => {
  const state = {
    run_id: 'r1',
    revision: 10,
    vision: {sample_time_s: 0.05},
    config: {stimulus: {x: 12, y: 8, intensity: 1}},
  };
  const url = eyeImageUrl(state);
  assert.match(url, /^\/api\/eyes\?v=/);
  assert.equal(eyeImageUrl({...state, revision: 11}), url);
  assert.notEqual(eyeImageUrl({...state, vision: {sample_time_s: 0.1}}), url);
  assert.notEqual(eyeImageUrl({...state, run_id: 'r2'}), url);
  assert.notEqual(eyeImageUrl({...state, config: {stimulus: {x: 12, y: -8, intensity: 1}}}), url);
});

test('a dragged control sends at most one value per interval and the last one on release', () => {
  let clock = 0;
  const sent = [];
  const sender = throttled(
    (v) => sent.push(v),
    200,
    () => clock,
  );
  sender.push(0.1); // first value goes out at once
  clock = 50;
  sender.push(0.2);
  clock = 120;
  sender.push(0.3); // held back
  assert.deepEqual(sent, [0.1]);
  clock = 210;
  sender.push(0.4); // the interval has passed
  assert.deepEqual(sent, [0.1, 0.4]);
  clock = 250;
  sender.push(0.5);
  assert.equal(sender.flush(), true); // release sends the held value
  assert.deepEqual(sent, [0.1, 0.4, 0.5]);
  assert.equal(sender.flush(), false); // nothing left
  assert.deepEqual(sent, [0.1, 0.4, 0.5]);
});

test('arrow keys move along a row of tabs and wrap around', () => {
  const tabs = ['workbench', 'atlas', 'experiments'];
  assert.equal(tabTarget(tabs, 'workbench', 'ArrowRight'), 'atlas');
  assert.equal(tabTarget(tabs, 'experiments', 'ArrowRight'), 'workbench');
  assert.equal(tabTarget(tabs, 'workbench', 'ArrowLeft'), 'experiments');
  assert.equal(tabTarget(tabs, 'atlas', 'Home'), 'workbench');
  assert.equal(tabTarget(tabs, 'atlas', 'End'), 'experiments');
  assert.equal(tabTarget(tabs, 'atlas', 'Enter'), null);
  assert.equal(tabTarget([], 'atlas', 'ArrowRight'), null);
});
