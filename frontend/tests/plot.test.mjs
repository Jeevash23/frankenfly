import test from 'node:test';
import assert from 'node:assert/strict';
import {trace, targetFromPoint} from '../src/plot.ts';

test('target mapping uses world units and clamps input to the safe arena', () => {
  const rect = {left: 10, top: 20, width: 200, height: 200};
  assert.deepEqual(targetFromPoint(110, 120, rect, 40), {x: 0, y: 0});
  assert.deepEqual(targetFromPoint(210, 20, rect, 40), {x: 40, y: 40});
  assert.deepEqual(targetFromPoint(-100, 999, rect, 40), {x: -40, y: -40});
});

test('charts contain only received samples and remain unchanged while paused', () => {
  const data = [
    {t: 0, rates: [0]},
    {t: 1, rates: [0.7]},
  ];
  assert.equal(
    trace([], (s) => s.rates[0]),
    '',
  );
  assert.equal(
    trace(data, (s) => s.rates[0]),
    'M0.00,110.00 L300.00,55.00',
  );
  assert.equal(
    trace(data, (s) => s.rates[0]),
    trace(structuredClone(data), (s) => s.rates[0]),
  );
});

test('history coordinates use simulation time and a bounded window', () => {
  const data = [
    {t: 1, rates: [0.7]},
    {t: 6, rates: [1.4]},
    {t: 10, rates: [0]},
  ];
  assert.equal(
    trace(data, (s) => s.rates[0]),
    'M0.00,0.00 L600.00,110.00',
  );
});
