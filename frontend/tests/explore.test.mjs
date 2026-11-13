import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildDraft,
  circuitName,
  compact,
  defaultForm,
  formProblem,
  manipulationBlocker,
  pathGroups,
  percent,
  queryUrl,
  rowGroups,
  rowManipulation,
  rowSide,
  signText,
} from '../src/connectome/explore.ts';
import {parseHash, routeHash} from '../src/route.ts';

const connectome = (circuit = 'fafb783-dna02', dynamics = 'rate') => ({
  config: {neural_model: 'connectome', connectome_parameters: {circuit, dynamics}},
});

test('each query asks the explorer API with the form', () => {
  const partners = new URL(queryUrl('partners', defaultForm), 'http://x');
  assert.equal(partners.pathname, '/api/explore/partners');
  assert.equal(partners.searchParams.get('query'), 'DNa02');
  assert.equal(partners.searchParams.get('direction'), 'upstream');
  assert.equal(partners.searchParams.get('graph'), 'brain');
  const paths = new URL(
    queryUrl('paths', {...defaultForm, limit: 200, level: 'neuron'}),
    'http://x',
  );
  assert.equal(paths.searchParams.get('limit'), '50'); // the paths endpoint takes at most 50
  assert.equal(paths.searchParams.get('level'), 'neuron');
  assert.equal(paths.searchParams.get('max_hops'), '10');
  const influence = new URL(queryUrl('influence', {...defaultForm, signed: false}), 'http://x');
  assert.equal(influence.searchParams.get('direction'), 'onto');
  assert.equal(influence.searchParams.get('signed'), 'false');
});

test('form problems are explained before anything is sent', () => {
  assert.equal(formProblem('partners', defaultForm), null);
  assert.match(formProblem('partners', {...defaultForm, query: ' '}), /cell type/);
  assert.match(formProblem('paths', {...defaultForm, target: 'LC10a'}), /same/);
  assert.match(formProblem('paths', {...defaultForm, maxHops: 0}), /1 to 20/);
  assert.match(formProblem('influence', {...defaultForm, threshold: 0}), /threshold/);
  assert.match(formProblem('influence', {...defaultForm, limit: 1.5}), /rows/);
});

test('a row can be manipulated only where the running circuit has it', () => {
  const inCircuit = {neurons: 2, left: 1, right: 1};
  assert.equal(manipulationBlocker(connectome(), 'DNa02', 'both', inCircuit), null);
  assert.match(manipulationBlocker(null, 'DNa02', 'both', inCircuit), /Not connected/);
  assert.match(
    manipulationBlocker(
      {config: {...connectome().config, neural_model: 'engineered'}},
      'DNa02',
      'both',
      inCircuit,
    ),
    /engineered model/,
  );
  assert.match(
    manipulationBlocker(connectome(), 'MDN', 'both', null),
    /not in the running circuit \(fafb783-dna02\)/,
  );
  assert.match(
    manipulationBlocker(connectome(), 'Solo', 'right', {neurons: 1, left: 1, right: 0}),
    /no right Solo neurons/,
  );
});

test('rows silence or activate their type on their own side, at the Workbench default', () => {
  assert.equal(rowSide({side: 'left'}), 'left');
  assert.equal(rowSide({side: 'center'}), 'both');
  assert.equal(rowSide({}), 'both');
  assert.deepEqual(rowManipulation('PS049', 'both', 'silence', 'rate'), {
    name: 'PS049',
    side: 'both',
    mode: 'silence',
    value: 0,
  });
  assert.equal(rowManipulation('PS049', 'left', 'activate', 'rate').value, 0.6);
  assert.equal(rowManipulation('PS049', 'left', 'activate', 'spiking').value, 80);
});

test('building around a row fills the builder and keeps an unsent draft’s settings', () => {
  assert.equal(circuitName(['LC10a', 'DNa02']), 'lc10a-dna02-circuit');
  assert.equal(circuitName(['(PS023,PS024)a']), 'ps023-ps024-a-circuit');
  assert.equal(circuitName(['---']), 'explorer-circuit');
  assert.match(circuitName(['x'.repeat(80)]), /^[a-z0-9][a-z0-9._-]{0,63}$/);
  const draft = buildDraft(['LC10a', 'LC10a', ' DNa02 '], {
    name: 'old',
    seeds: ['MDN'],
    hops: 3,
    threshold: 10,
    cap: 500,
    whole_brain: false,
    balance_sides: true,
  });
  assert.deepEqual(draft.request.seeds, ['LC10a', 'DNa02']);
  assert.equal(draft.request.name, 'lc10a-dna02-circuit');
  assert.equal(draft.request.hops, 3);
  assert.equal(draft.request.balance_sides, true);
  assert.equal(buildDraft(['DNa02'], null).request.cap, 3000);
});

test('Neuroglancer groups for rows and paths', () => {
  assert.deepEqual(rowGroups([{cell_type: 'A'}, {cell_type: 'B'}], 1), [
    {label: 'A', cell_type: 'A'},
  ]);
  assert.deepEqual(
    rowGroups([
      {id: '7', cell_type: 'A'},
      {id: '8', cell_type: 'B'},
    ]),
    [{label: 'neurons', ids: ['7', '8']}],
  );
  assert.deepEqual(pathGroups({cell_types: ['A', 'B']}), [
    {label: '1. A', cell_type: 'A'},
    {label: '2. B', cell_type: 'B'},
  ]);
  assert.deepEqual(pathGroups({cell_types: ['A'], neurons: [{id: '9', cell_type: 'A'}]}), [
    {label: '1. A', ids: ['9']},
  ]);
});

test('numbers and signs for the tables', () => {
  assert.equal(signText(1), '+');
  assert.equal(signText(-1), '−');
  assert.equal(signText(0), '0');
  assert.equal(percent(0.0305), '3.0%');
  assert.equal(percent(0.00012), '0.012%');
  assert.equal(compact(1086.4), '1.09e+3');
  assert.equal(compact(0.5), '0.500');
  assert.equal(compact(0), '0');
  assert.equal(compact(Number.NaN), '—');
});

test('the explorer has its own address, and the old one redirects to it', () => {
  assert.equal(routeHash('explorer'), '#/connectome/explorer');
  assert.equal(parseHash('#/connectome/explorer').redirect, null);
  const old = parseHash('#/atlas/explore');
  assert.equal(old.route, 'explorer');
  assert.equal(old.redirect, '#/connectome/explorer');
  // A cell type to open travels as a parameter.
  assert.equal(routeHash('explorer', {type: 'DNa02'}), '#/connectome/explorer?type=DNa02');
  assert.equal(parseHash('#/connectome/explorer?type=DNa02').params.get('type'), 'DNa02');
});
