import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatEstimate,
  formatInterval,
  formatTick,
  formatValue,
  metricLabel,
  metricOrder,
  sampleNote,
  smallestN,
  summaryCsvUrl,
  wideInterval,
} from '../src/summary.ts';

// The shape of GET /api/batches/{batch_id}/summary (a toy comparison, two seeds).
const metric = (mean, sd, ci95) => ({mean, sd, ci95});
const summary = {
  batch_id: '3c0cb86dee80',
  n_trials: 4,
  partial_trials: 0,
  reach_mm: 2,
  conditions: [
    {
      condition: 'control',
      n: 2,
      metrics: {
        reached: metric(1, 0, [0.342, 1]),
        target_distance_mm: metric(1.195, 0.03, [1.1737, 1.2162]),
        net_turn_deg: metric(36.04, 0.7, [35.55, 36.54]),
        made_up: metric(1, null, null),
      },
    },
    {condition: 'left_sensor_off', n: 3, metrics: {}},
  ],
  paired: [],
  methods: {},
};

test('metrics come in display order, unknown ones last, with their units', () => {
  assert.deepEqual(metricOrder(summary), [
    'target_distance_mm',
    'net_turn_deg',
    'reached',
    'made_up',
  ]);
  assert.equal(metricLabel('target_distance_mm'), 'Final distance to target (mm)');
  assert.equal(metricLabel('reached'), 'Reached the target (%)');
  assert.equal(metricLabel('made_up'), 'made up');
});

test('estimates read as mean ± SD over a 95% interval', () => {
  const [control] = summary.conditions;
  assert.equal(
    formatEstimate('target_distance_mm', control.metrics.target_distance_mm),
    '1.20 ± 0.03',
  );
  assert.equal(formatEstimate('net_turn_deg', control.metrics.net_turn_deg), '36.0 ± 0.7');
  // A proportion has no SD to show; it reads as a percentage.
  assert.equal(formatEstimate('reached', control.metrics.reached), '100');
  assert.equal(formatInterval('reached', [0.342, 1]), '34 to 100');
  // One trial: no SD and no interval.
  assert.equal(formatEstimate('target_distance_mm', metric(1.5, null, null)), '1.50');
  assert.equal(formatInterval('target_distance_mm', null), null);
  // Differences carry their sign; a rounded zero has none.
  assert.equal(formatValue('path_length_mm', 7.499, true), '+7.50');
  assert.equal(formatValue('path_length_mm', -7.499, true), '-7.50');
  assert.equal(formatValue('path_length_mm', -0.001), '0.00');
  assert.equal(formatInterval('net_turn_deg', [-123.74, -123.66], true), '-123.7 to -123.7');
  assert.equal(formatValue('net_turn_deg', null), '—');
  assert.equal(formatTick('net_turn_deg', -100), '-100');
  assert.equal(formatTick('reached', 0.5), '50');
  assert.equal(formatTick('mean_speed_mm_s', 0.25), '0.25');
});

test('intervals wider than their estimate are marked wide, small samples are named', () => {
  assert.equal(wideInterval(13.66, [13.64, 13.67]), false);
  assert.equal(wideInterval(0.5, [-0.2, 1.4]), true);
  assert.equal(wideInterval(0, [0, 0.66]), true); // estimates at zero always are
  assert.equal(wideInterval(0, [0, 0]), false);
  assert.equal(wideInterval(1, null), false);
  assert.equal(smallestN(summary), 2);
  assert.match(sampleNote(summary), /^Small samples: as few as 2 trials per condition/);
  const large = {conditions: summary.conditions.map((c) => ({...c, n: 8}))};
  assert.equal(sampleNote(large), null);
  assert.equal(sampleNote({conditions: []}), null);
  assert.equal(summaryCsvUrl('3c0cb86dee80'), '/api/batches/3c0cb86dee80/summary?format=csv');
});
