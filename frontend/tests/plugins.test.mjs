import test from 'node:test';
import assert from 'node:assert/strict';
import {contributionNames, contributionSummary} from '../src/plugins.ts';

const example = {
  name: 'example',
  status: 'ok',
  contributions: {
    sensors: [{name: 'crossed', title: 'Crossed eyes'}],
    stimuli: [],
    scorecard_tests: [{name: 'target_side', title: 'Target to one side'}],
    metrics: [
      {name: 'straightness', title: 'Path straightness', unit: 'ratio'},
      {name: 'speed', title: 'Speed'},
    ],
    commands: [],
  },
};

test('a plugin is summarised by what it adds, kinds in order and plurals counted', () => {
  assert.equal(contributionSummary(example), '1 sensor, 1 scorecard test, 2 metrics');
  assert.equal(contributionSummary({...example, contributions: {metrics: []}}), 'nothing');
});

test('contributions are named plugin:name, as runs and commands use them', () => {
  assert.deepEqual(contributionNames(example), [
    'example:crossed',
    'example:target_side',
    'example:straightness',
    'example:speed',
  ]);
});
