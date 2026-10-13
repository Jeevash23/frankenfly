import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activityColor,
  glowColor,
  edgesToDraw,
  laterality,
  layoutTypes,
  topPartners,
  VIEW,
} from '../src/connectome/layout.ts';

const type = (name, layer, left, right, count = left + right) => ({
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
  type('DNa02', 0, 1, 1),
  type('rightish', 1, 0, 4),
  type('leftish', 1, 4, 0),
  type('far', 2, 3, 3),
  type('farther', 3, 1, 0),
];

test('layout places cell types by hop distance and laterality, never anatomy', () => {
  const nodes = layoutTypes(types, 0);
  assert.equal(nodes.has(0), false); // DNa02 is drawn separately as two sided nodes
  assert.equal(nodes.size, 4);
  assert.ok(nodes.get(3).x < nodes.get(1).x); // hop 2 sits left of hop 1
  assert.equal(nodes.get(4).x < nodes.get(1).x, true); // deeper hops share the hop-2 band
  assert.ok(nodes.get(2).y < nodes.get(1).y); // left-dominant above right-dominant
  for (const node of nodes.values()) {
    assert.ok(node.y >= VIEW.top && node.y <= VIEW.bottom && node.r > 0);
  }
  assert.equal(laterality(types[1]), 1);
  assert.equal(laterality(type('unsided', 1, 0, 0)), 0.5);
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
