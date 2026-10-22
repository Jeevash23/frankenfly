import test from 'node:test';
import assert from 'node:assert/strict';
import {intervalChart, niceTicks, trace, targetFromPoint} from '../src/plot.ts';

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

test('axis ticks are round numbers that cover the data', () => {
  assert.deepEqual(niceTicks(0, 16.15), [0, 5, 10, 15, 20]);
  assert.deepEqual(niceTicks(-123.7, 0), [-150, -100, -50, 0]);
  assert.deepEqual(niceTicks(-88.2, 36.5), [-100, -50, 0, 50]);
  assert.deepEqual(niceTicks(0, 1), [0, 0.5, 1]);
  assert.deepEqual(niceTicks(0, 0.0003), [0, 0.0001, 0.0002, 0.0003]);
  assert.deepEqual(niceTicks(3, 3), [3]);
});

test('interval charts share one axis that includes zero', () => {
  const chart = intervalChart(
    [
      {estimate: 1.19, ci: [1.17, 1.22]},
      {estimate: 16.15, ci: [16.14, 16.16]},
      {estimate: 2, ci: null}, // one trial: no interval
      {estimate: null, ci: null}, // no value
    ],
    100,
    400,
  );
  assert.deepEqual(
    chart.ticks.map((t) => t.value),
    [0, 5, 10, 15, 20],
  );
  assert.equal(chart.zero, 100);
  assert.deepEqual(chart.rows[0], {x: 117.85, low: 117.55, high: 118.3});
  assert.deepEqual(chart.rows[2], {x: 130, low: 130, high: 130});
  assert.equal(chart.rows[3], null);
  // Negative estimates put zero inside the axis; all-zero data gets a unit axis.
  const turns = intervalChart([{estimate: -87.7, ci: [-88.2, -87.1]}], 0, 300);
  assert.equal(turns.zero, 300);
  assert.equal(turns.ticks[0].value, -100);
  const flat = intervalChart([{estimate: 0, ci: [0, 0]}], 0, 100);
  assert.deepEqual(
    flat.ticks.map((t) => t.value),
    [0, 0.5, 1],
  );
});
