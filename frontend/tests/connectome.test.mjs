import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activityColor,
  band,
  glowColor,
  edgesToDraw,
  laterality,
  layoutTypes,
  neighbour,
  readoutRows,
  topPartners,
  VIEW,
} from '../src/connectome/layout.ts';
import {
  buildProblem,
  defaultBuild,
  parseTypes,
  sideBalanced,
  suggestTypes,
} from '../src/connectome/build.ts';

const type = (index, name, layer, left, right, count = left + right) => ({
  index,
  name,
  count,
  layer,
  super_class: 'central',
  transmitters: {acetylcholine: count},
  transmitter: 'acetylcholine',
  sign: 1,
  left,
  right,
  input: false,
});
const types = [
  type(0, 'DNa02', 0, 1, 1),
  type(1, 'rightish', 1, 0, 4),
  type(2, 'leftish', 1, 4, 0),
  type(3, 'far', 2, 3, 3),
  type(4, 'farther', 3, 1, 0),
];

test('layout places cell types by hop distance and laterality, never anatomy', () => {
  const nodes = layoutTypes(types, new Set([0]));
  assert.equal(nodes.has(0), false); // readout types are drawn separately as sided nodes
  assert.equal(nodes.size, 4);
  assert.ok(nodes.get(3).x < nodes.get(1).x); // hop 2 sits left of hop 1
  assert.equal(nodes.get(4).x < nodes.get(1).x, true); // deeper hops share the hop-2 band
  assert.ok(nodes.get(2).y < nodes.get(1).y); // left-dominant above right-dominant
  for (const node of nodes.values()) {
    assert.ok(node.y >= VIEW.top && node.y <= VIEW.bottom && node.r > 0);
  }
  assert.equal(laterality(types[1]), 1);
  assert.equal(laterality(type(9, 'unsided', 1, 0, 0)), 0.5);
});

test('large circuits send a subset of types, keyed by their circuit index', () => {
  const subset = [
    type(40, 'seed-side', 0, 2, 0),
    type(7, 'deep', 5, 1, 1),
    type(12, 'unreached', -1, 0, 3),
  ];
  const nodes = layoutTypes(subset, new Set([99]));
  assert.deepEqual(
    [...nodes.keys()].sort((a, b) => a - b),
    [7, 12, 40],
  );
  assert.equal(band(0), 1);
  assert.equal(band(1), 1);
  assert.equal(band(4), 2);
  assert.equal(band(-1), 2); // not connected to the seeds: drawn with the deepest inputs
  assert.ok(nodes.get(40).x > nodes.get(7).x);
});

test('readout neurons stack left above right, inside the drawing', () => {
  for (const count of [1, 3, 8]) {
    const rows = readoutRows(count);
    assert.equal(rows.length, count);
    rows.forEach((row, k) => {
      assert.ok(row.left < row.right && row.left >= VIEW.top && row.right <= VIEW.bottom);
      if (k) assert.ok(row.left > rows[k - 1].right);
    });
  }
});

test('the builder form explains problems in plain words', () => {
  const ok = {...defaultBuild, name: 'my-circuit', seeds: ['DNa01', '720575940629327659']};
  const known = new Set(['DNa01', 'DNa02']);
  assert.equal(buildProblem(ok, ['fafb783-dna02'], known), null);
  assert.match(buildProblem({...ok, name: 'My Circuit'}, [], known), /lower-case/);
  assert.match(buildProblem({...ok, name: 'fafb783-dna02'}, ['fafb783-dna02'], known), /built-in/);
  assert.match(buildProblem({...ok, seeds: []}, [], known), /at least one seed/);
  assert.match(buildProblem({...ok, seeds: ['dna01']}, [], known), /case-sensitive/);
  assert.match(buildProblem({...ok, hops: 0}, [], known), /1 to 6 hops/);
  assert.match(buildProblem({...ok, cap: 5}, [], known), /10 to 200,000/);
  assert.equal(buildProblem({...ok, seeds: ['anything']}, [], null), null); // catalog not loaded
  // Side balance is sent as balance_sides; it needs the cap a whole-brain build does not have.
  assert.equal(defaultBuild.balance_sides, false);
  assert.equal(buildProblem({...ok, balance_sides: true}, [], known), null);
  assert.match(buildProblem({...ok, balance_sides: true, whole_brain: true}, [], known), /no cap/);
});

test('circuits built with balanced sides are recognised from the circuit list', () => {
  assert.equal(sideBalanced({name: 'a', build: {balance_sides: true}}), true);
  assert.equal(sideBalanced({name: 'b', build: {balance_sides: false}}), false);
  assert.equal(sideBalanced({name: 'c'}), false); // servers before v0.6
  assert.equal(sideBalanced(undefined), false);
});

test('seed suggestions rank prefix matches first and population lists split on semicolons', () => {
  const names = ['LC10a', 'DNa02', 'DNa01', 'aDNa1', 'DNa10'];
  assert.deepEqual(suggestTypes(names, 'dna0'), ['DNa01', 'DNa02']);
  assert.deepEqual(suggestTypes(names, 'na1'), ['aDNa1', 'DNa10']); // contained, not a prefix
  assert.deepEqual(suggestTypes(names, 'DNa', 2), ['DNa01', 'DNa02']);
  assert.deepEqual(suggestTypes(names, ' '), []);
  assert.deepEqual(parseTypes('DNa01; DNa02;; DNa01 '), ['DNa01', 'DNa02']);
  assert.deepEqual(parseTypes('VES051,VES052'), ['VES051,VES052']);
  assert.equal(parseTypes('  '), null);
});

const edges = {
  pre: [1, 2, 3, 3, 4],
  post: [2, 1, 1, 2, 3],
  sign: [1, -1, 1, -1, 1],
  synapses: [50, 40, 30, 20, 10],
  connections: [5, 4, 3, 2, 1],
};

test('only the strongest connections are drawn, plus every one of a selected type', () => {
  assert.deepEqual(edgesToDraw(edges, 2, null), [0, 1]);
  assert.deepEqual(edgesToDraw(edges, 2, 4), [0, 1, 4]);
  assert.deepEqual(edgesToDraw(edges, 0, 3), [2, 3, 4]);
});

test('top partners are ranked by synapse count with their sign', () => {
  assert.deepEqual(
    topPartners(edges, 1, 'in').map((p) => [p.type, p.sign, p.synapses]),
    [
      [2, -1, 40],
      [3, 1, 30],
    ],
  );
  assert.deepEqual(
    topPartners(edges, 3, 'out', 1).map((p) => p.type),
    [1],
  );
});

test('activity colours run from pale at rest to deep green and clamp', () => {
  assert.equal(activityColor(0), 'rgb(238,240,232)');
  assert.equal(activityColor(1), 'rgb(43,86,63)');
  assert.equal(activityColor(5), activityColor(1));
  assert.equal(activityColor(-1), activityColor(0));
});

test('the anatomy tint brightens with activity on the dark canvas', () => {
  assert.equal(glowColor(0), 'rgb(70,92,76)');
  assert.equal(glowColor(1), 'rgb(236,255,181)');
  assert.equal(glowColor(2), glowColor(1));
});

test('arrow keys move between diagram nodes by column and row', () => {
  // Two columns of a hop band and one readout column to their right.
  const spots = [
    {key: 'a', x: 100, y: 60},
    {key: 'b', x: 100, y: 120},
    {key: 'c', x: 100, y: 180},
    {key: 'd', x: 200, y: 70},
    {key: 'e', x: 200, y: 170},
    {key: 'r', x: 912, y: 150},
  ];
  assert.equal(neighbour(spots, 'a', 'ArrowDown'), 'b');
  assert.equal(neighbour(spots, 'b', 'ArrowUp'), 'a');
  assert.equal(neighbour(spots, 'c', 'ArrowDown'), null); // bottom of its column
  assert.equal(neighbour(spots, 'c', 'ArrowRight'), 'e'); // nearest row in the next column
  assert.equal(neighbour(spots, 'a', 'ArrowRight'), 'd');
  assert.equal(neighbour(spots, 'e', 'ArrowRight'), 'r');
  assert.equal(neighbour(spots, 'r', 'ArrowLeft'), 'e');
  assert.equal(neighbour(spots, 'a', 'ArrowLeft'), null);
  assert.equal(neighbour(spots, 'e', 'Home'), 'a');
  assert.equal(neighbour(spots, 'a', 'End'), 'r');
  assert.equal(neighbour(spots, 'a', 'Enter'), null);
  assert.equal(neighbour(spots, 'missing', 'ArrowDown'), null);
});
