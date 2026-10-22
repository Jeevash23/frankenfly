import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activeInterventions,
  entryProblem,
  manipulationLabel,
  manipulationOn,
  manipulations,
  neuronCounts,
  overlapProblem,
  replaced,
  valueProblem,
  valueRange,
  withCellType,
  withoutCellType,
  withoutManipulation,
} from '../src/interventions.ts';

const none = {
  zero_left: false,
  zero_right: false,
  silence: 'none',
  silence_dna02: 'none',
  silence_types: [],
  cell_types: [],
};
const apply = (current, change) => ({...current, ...change});
const entry = (name, side, mode, value = 0) => ({name, side, mode, value});

test('setting a manipulation replaces what acts on the same side instead of overlapping', () => {
  let i = apply(none, withCellType(none, entry('DNa03', 'left', 'scale', 0.5)));
  i = apply(i, withCellType(i, entry('DNa03', 'left', 'activate', 0.6)));
  assert.deepEqual(i.cell_types, [entry('DNa03', 'left', 'activate', 0.6)]);
  // "both" replaces each one-sided entry of the type; other types are kept.
  i = apply(i, withCellType(i, entry('DNp09', 'right', 'silence')));
  i = apply(i, withCellType(i, entry('DNa03', 'both', 'silence')));
  assert.deepEqual(i.cell_types, [
    entry('DNp09', 'right', 'silence'),
    entry('DNa03', 'both', 'silence'),
  ]);
  assert.equal(overlapProblem(i), null);
});

test('one side of a two-sided manipulation keeps the other side', () => {
  let i = apply(none, withCellType(none, entry('DNa03', 'both', 'scale', 1.5)));
  i = apply(i, withCellType(i, entry('DNa03', 'right', 'silence')));
  assert.deepEqual(i.cell_types, [
    entry('DNa03', 'left', 'scale', 1.5),
    entry('DNa03', 'right', 'silence'),
  ]);
  assert.equal(manipulationOn(i, 'DNa03', 'left').mode, 'scale');
  assert.equal(manipulationOn(i, 'DNa03', 'right').mode, 'silence');
  assert.equal(overlapProblem(i), null);
});

test('the older silencing fields count as manipulations and give way like any other', () => {
  const older = {...none, silence_types: ['LC10'], silence_dna02: 'both'};
  assert.deepEqual(
    manipulations(older).map((m) => [m.name, m.side, m.source]),
    [
      ['LC10', 'both', 'silence_types'],
      ['DNa02', 'both', 'silence_dna02'],
    ],
  );
  // Activating the left LC10 keeps its right side silenced, as a cell_types entry.
  let i = apply(older, withCellType(older, entry('LC10', 'left', 'activate', 80)));
  assert.deepEqual(i.silence_types, []);
  assert.deepEqual(i.cell_types, [
    entry('LC10', 'right', 'silence'),
    entry('LC10', 'left', 'activate', 80),
  ]);
  // Scaling the left DNa02 leaves silence_dna02 on the right only.
  i = apply(i, withCellType(i, entry('DNa02', 'left', 'scale', 0.2)));
  assert.equal(i.silence_dna02, 'right');
  i = apply(i, withCellType(i, entry('DNa02', 'both', 'silence')));
  assert.equal(i.silence_dna02, 'none');
  assert.equal(overlapProblem(i), null);
  assert.equal(activeInterventions(i), 3);
});

test('silencing stores no value, and replaced entries are named before they go', () => {
  const i = apply(none, withCellType(none, entry('DNa03', 'both', 'silence', 7)));
  assert.equal(i.cell_types[0].value, 0);
  assert.deepEqual(
    replaced(i, 'DNa03', 'left').map((m) => m.side),
    ['both'],
  );
  assert.deepEqual(replaced(i, 'DNa02', 'left'), []);
});

test('removing one manipulation, or every side of a type', () => {
  const i = {
    ...none,
    silence_types: ['LC10'],
    silence_dna02: 'left',
    cell_types: [entry('DNa03', 'left', 'scale', 0.5), entry('DNa03', 'right', 'silence')],
  };
  assert.deepEqual(withoutManipulation(i, {name: 'LC10', side: 'both', source: 'silence_types'}), {
    silence_types: [],
  });
  assert.deepEqual(withoutManipulation(i, {name: 'DNa02', side: 'left', source: 'silence_dna02'}), {
    silence_dna02: 'none',
  });
  assert.deepEqual(
    withoutManipulation(i, {name: 'DNa03', side: 'left', source: 'cell_types'}).cell_types,
    [entry('DNa03', 'right', 'silence')],
  );
  assert.deepEqual(withoutCellType(i, 'DNa03').cell_types, []);
  assert.equal(withoutCellType(i, 'DNa02').silence_dna02, 'none');
});

test('overlaps the server would refuse are reported', () => {
  const twice = {
    ...none,
    cell_types: [entry('DNa03', 'both', 'silence'), entry('DNa03', 'left', 'scale', 1)],
  };
  assert.match(overlapProblem(twice), /DNa03 \(left\) is manipulated twice/);
  const older = {
    ...none,
    silence_types: ['DNa03'],
    cell_types: [entry('DNa03', 'right', 'scale', 1)],
  };
  assert.match(overlapProblem(older), /twice/);
});

test('values and units follow the mode and the dynamics', () => {
  assert.equal(valueRange('silence', 'rate'), null);
  assert.deepEqual(
    [valueRange('scale', 'spiking').max, valueRange('scale', 'spiking').unit],
    [2, '×'],
  );
  assert.deepEqual(
    [valueRange('activate', 'spiking').max, valueRange('activate', 'spiking').unit],
    [500, 'Hz'],
  );
  assert.deepEqual(
    [valueRange('activate', 'rate').max, valueRange('activate', 'rate').unit],
    [1, 'rate'],
  );
  assert.match(valueProblem('scale', 2.5, 'rate'), /0 to 2/);
  assert.equal(valueProblem('scale', 0, 'rate'), null); // scaling to 0 is allowed
  assert.match(valueProblem('activate', 80, 'rate'), /above 0, up to 1/);
  assert.equal(valueProblem('activate', 80, 'spiking'), null);
  // Activation needs a value above 0, as the server requires; silencing holds a type at rest.
  for (const dynamics of ['rate', 'spiking']) {
    const range = valueRange('activate', dynamics);
    assert.ok(range.min > 0 && range.initial >= range.min && range.initial <= range.max);
    assert.equal(valueProblem('activate', range.min, dynamics), null);
    assert.equal(valueProblem('activate', range.initial, dynamics), null);
    assert.match(valueProblem('activate', 0, dynamics), /above 0.*silence it/);
    assert.match(valueProblem('activate', -1, dynamics), /above 0/);
  }
  assert.equal(valueProblem('activate', 0.5, 'spiking'), null); // below the slider, above 0
  assert.equal(valueProblem('activate', 0.001, 'rate'), null);
  assert.equal(
    manipulationLabel(entry('DNp09', 'both', 'activate', 80), 'spiking'),
    'DNp09 activated 80 Hz',
  );
  assert.equal(
    manipulationLabel(entry('DNp09', 'left', 'activate', 0.6), 'rate'),
    'DNp09 left activated (rate 0.6)',
  );
  assert.equal(
    manipulationLabel(entry('DNa03', 'right', 'scale', 0.5), 'rate'),
    'DNa03 right output ×0.5',
  );
});

test('a manipulation needs a known type with neurons on its side', () => {
  const type = {left: 2, right: 0};
  assert.match(entryProblem(entry('', 'both', 'silence'), 'rate', undefined, true), /Choose/);
  assert.match(
    entryProblem(entry('XYZ', 'both', 'silence'), 'rate', undefined, true),
    /Not a cell type/,
  );
  // Large circuits list only some types: the server checks the rest.
  assert.equal(entryProblem(entry('XYZ', 'both', 'silence'), 'rate', undefined, false), null);
  assert.match(
    entryProblem(entry('DNa03', 'right', 'silence'), 'rate', type, true),
    /no right neurons/,
  );
  assert.equal(entryProblem(entry('DNa03', 'left', 'scale', 1.2), 'rate', type, true), null);
});

test('the neurons reached are counted by kind', () => {
  assert.equal(neuronCounts(undefined), null);
  assert.equal(neuronCounts({silence: 0, scale: 0, activate: 0}), null);
  assert.equal(neuronCounts({silence: 12, scale: 0, activate: 2}), '12 silenced · 2 activated');
});
