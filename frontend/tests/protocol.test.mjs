import test from 'node:test';
import assert from 'node:assert/strict';
import {
  edited,
  freeStep,
  preset,
  scheduleProblem,
  sortedEvents,
  withDuration,
} from '../src/protocol.ts';

const change = (step) => ({step, stimulus: {x: 12, y: -8, intensity: 1}});

test('changing the duration keeps custom stimulus changes', () => {
  const custom = edited(preset('Target reversal', 2), [change(100), change(150)]);
  const longer = withDuration(custom, 3);
  assert.equal(longer.duration_steps, 300);
  assert.deepEqual(longer.events, custom.events);
  assert.equal(longer.name, 'Custom sequence');
});

test('changing the duration still rescales an untouched preset', () => {
  const rescaled = withDuration(preset('Target reversal', 2), 4);
  assert.deepEqual(
    rescaled.events.map((e) => e.step),
    [200],
  );
});

test('repeatedly adding changes never reuses a step or passes the end', () => {
  let protocol = preset('Target reversal', 2);
  for (let i = 0; i < 7; i++)
    protocol = edited(protocol, [...protocol.events, change(freeStep(protocol))]);
  const steps = protocol.events.map((e) => e.step);
  assert.equal(new Set(steps).size, steps.length);
  assert.ok(steps.every((s) => s >= 0 && s < protocol.duration_steps));
  assert.equal(scheduleProblem(protocol), null);
});

test('schedule problems are explained in plain sentences', () => {
  const base = preset('Steady target', 1);
  assert.match(scheduleProblem(edited(base, [change(40), change(40)])), /same time/);
  assert.match(scheduleProblem(edited(base, [change(100)])), /not before the end \(1\.0 s\)/);
  assert.equal(scheduleProblem(base), null);
});

test('events are sent to the server in time order', () => {
  const sorted = sortedEvents(edited(preset('Steady target', 2), [change(150), change(20)]));
  assert.deepEqual(
    sorted.events.map((e) => e.step),
    [20, 150],
  );
});
