import test from 'node:test';
import assert from 'node:assert/strict';
import {
  customProblem,
  customRequest,
  customSummary,
  newCustomCondition,
  parseSeeds,
  sizeProblem,
} from '../src/comparison.ts';
import {clippingNote, conditionName, conditionProblem, MAX_CONDITIONS} from '../src/models.ts';

const none = {
  zero_left: false,
  zero_right: false,
  silence: 'none',
  silence_dna02: 'none',
  silence_types: [],
  cell_types: [],
};
const custom = (label, extra = {}) => ({
  label,
  interventions: null,
  connectome_parameters: null,
  ...extra,
});

test('built-in and custom conditions share the limit of six', () => {
  assert.equal(MAX_CONDITIONS, 6);
  const four = ['control', 'left_sensor_off', 'dna02_left_off', 'dna02_both_off'];
  assert.equal(conditionProblem(four, 'connectome', '', true, 'geometric', 2), null);
  assert.match(
    conditionProblem(four, 'connectome', '', true, 'geometric', 3),
    /at most 6 conditions/,
  );
  assert.match(
    conditionProblem([...four, 'baseline'], 'connectome', '', true, 'geometric', 0),
    /at most four built-in/,
  );
  // Custom conditions may stand alone.
  assert.equal(conditionProblem([], 'connectome', '', true, 'geometric', 1), null);
  assert.match(conditionProblem([], 'connectome', '', true, 'geometric', 0), /at least one/);
});

test('custom labels must be present, short, distinct and not a built-in name', () => {
  assert.equal(customProblem([custom('gain 3'), custom('DNa03 off')], 'connectome'), null);
  assert.match(customProblem([custom('  ')], 'connectome'), /Give custom condition 1 a label/);
  assert.match(customProblem([custom('x'.repeat(41))], 'connectome'), /at most 40/);
  assert.match(customProblem([custom('a'), custom(' a ')], 'connectome'), /used twice/);
  assert.match(
    customProblem([custom('control')], 'engineered'),
    /built-in condition \(Neural control\)/,
  );
  assert.equal(customProblem([custom('toString')], 'engineered'), null);
  assert.match(customProblem([custom('tab\there')], 'engineered'), /letters, digits/);
});

test('custom conditions must fit the selected model', () => {
  const cells = custom('DNa03 off', {
    interventions: {
      ...none,
      cell_types: [{name: 'DNa03', side: 'both', mode: 'silence', value: 0}],
    },
  });
  assert.match(customProblem([cells], 'engineered'), /needs the connectome model/);
  assert.equal(customProblem([cells], 'connectome'), null);
  const group = custom('steering off', {interventions: {...none, silence: 'steering'}});
  assert.match(customProblem([group], 'connectome'), /engineered model/);
  const gain = custom('gain 3', {connectome_parameters: {output_gain: 3}});
  assert.match(customProblem([gain], 'engineered'), /select the connectome model/);
  assert.match(
    customProblem([custom('slow', {connectome_parameters: {motor_delay_ms: 900}})], 'connectome'),
    /motor delay \(ms\) takes 0 to 500/,
  );
});

test('requests send null for nothing changed and trimmed labels', () => {
  assert.deepEqual(
    customRequest(custom(' plain ', {interventions: none, connectome_parameters: {}})),
    {
      label: 'plain',
      interventions: null,
      connectome_parameters: null,
    },
  );
  const left = customRequest(custom('left off', {interventions: {zero_left: true}}));
  assert.equal(left.interventions.zero_left, true);
  assert.deepEqual(left.interventions.cell_types, []);
  assert.equal(
    customSummary(custom('g', {connectome_parameters: {output_gain: 3}})),
    'output gain 3',
  );
  assert.equal(customSummary(custom('n')), 'the configuration unchanged');
  assert.equal(newCustomCondition([custom('Condition 1')]).label, 'Condition 2');
  assert.equal(conditionName('gain_3'), 'gain_3'); // custom labels are shown as typed
  assert.equal(conditionName('dna02_both_off'), 'Both DNa02 off');
});

test('seeds and the 300-second bound read as sentences', () => {
  assert.deepEqual(parseSeeds('42, 43'), {seeds: [42, 43]});
  assert.match(parseSeeds('42,,43').problem, /whole-number/);
  assert.match(parseSeeds('1.5').problem, /whole-number/);
  assert.match(parseSeeds('1,2,3,4,5,6').problem, /one to five/);
  assert.match(parseSeeds('7, 7').problem, /only once/);
  assert.equal(sizeProblem(1500, 5, 4), null);
  assert.match(sizeProblem(1500, 5, 5), /375 simulated seconds; a comparison is limited to 300/);
});

test('a high clipped share is explained, a low one is not', () => {
  assert.equal(clippingNote(undefined), null);
  assert.equal(clippingNote(0.5), null);
  assert.match(clippingNote(0.67), /67% of control intervals.*saturated/);
});
