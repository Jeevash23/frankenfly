import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clearDraft,
  DRAFT_KEYS,
  loadDraft,
  readBuildDraft,
  readConnectivityDraft,
  readExperimentsDraft,
  saveDraft,
} from '../src/localDrafts.ts';
import {parseHash, routeHash} from '../src/route.ts';

const memory = () => {
  const items = new Map();
  return {
    getItem: (k) => (items.has(k) ? items.get(k) : null),
    setItem: (k, v) => items.set(k, String(v)),
    removeItem: (k) => items.delete(k),
    items,
  };
};
const broken = {
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('QuotaExceededError');
  },
  removeItem: () => {
    throw new Error('SecurityError');
  },
};

const draft = {
  protocol: {
    name: 'Custom sequence',
    duration_steps: 300,
    events: [{step: 50, stimulus: {x: 1, y: 2, intensity: 1}}],
  },
  seeds: '1, 2',
  conditions: ['control', 'dna02_both_off'],
  cellType: 'DNa03',
  custom: [
    {
      label: 'gain 3',
      interventions: {
        zero_left: true,
        cell_types: [{name: 'DNa03', side: 'left', mode: 'scale', value: 0.5}],
      },
      connectome_parameters: {output_gain: 3, circuit: 'other'},
    },
  ],
  maxSpeed: true,
};

test('drafts round-trip under versioned keys and survive blocked storage', () => {
  const store = memory();
  assert.match(DRAFT_KEYS.experiments, /\.v\d+$/);
  saveDraft(DRAFT_KEYS.experiments, draft, store);
  const back = loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft, store);
  // Events come back as the server writes them, with interventions: null.
  assert.deepEqual(back.protocol, {
    ...draft.protocol,
    events: [{step: 50, stimulus: {x: 1, y: 2, intensity: 1}, interventions: null}],
  });
  assert.equal(back.seeds, '1, 2');
  assert.deepEqual(back.conditions, ['control', 'dna02_both_off']);
  assert.equal(back.maxSpeed, true);
  // Only the parameters a custom condition can change are kept.
  assert.deepEqual(back.custom[0].connectome_parameters, {output_gain: 3});
  assert.equal(back.custom[0].interventions.zero_left, true);
  assert.equal(back.custom[0].interventions.silence, 'none');
  assert.deepEqual(
    back.custom[0].interventions.cell_types,
    draft.custom[0].interventions.cell_types,
  );
  clearDraft(DRAFT_KEYS.experiments, store);
  assert.equal(loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft, store), null);
  // Storage that throws (private windows, blocked site data) is the same as no draft.
  saveDraft(DRAFT_KEYS.experiments, draft, broken);
  clearDraft(DRAFT_KEYS.experiments, broken);
  assert.equal(loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft, broken), null);
  assert.equal(loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft, null), null);
});

test('a damaged draft is ignored field by field, never trusted', () => {
  const store = memory();
  store.setItem(DRAFT_KEYS.experiments, '{not json');
  assert.equal(loadDraft(DRAFT_KEYS.experiments, readExperimentsDraft, store), null);
  const read = readExperimentsDraft({
    protocol: {name: 'x', duration_steps: 0, events: []},
    seeds: 42,
    conditions: ['control', 'not_a_condition', 'toString'],
    custom: [
      {
        label: 'ok',
        interventions: {cell_types: [{name: 'A', side: 'up', mode: 'scale', value: 1}]},
      },
      'junk',
    ],
    maxSpeed: 'yes',
  });
  assert.equal(read.protocol, undefined);
  assert.equal(read.seeds, undefined);
  assert.deepEqual(read.conditions, ['control']);
  assert.deepEqual(read.custom.length, 1);
  assert.deepEqual(read.custom[0].interventions.cell_types, []);
  assert.equal(read.maxSpeed, undefined);
  assert.equal(readExperimentsDraft([1, 2]), null);
});

test('build and connectivity drafts', () => {
  const build = {
    request: {name: 'lc10', seeds: ['LC10', 7], hops: 2, threshold: 5, cap: 3000, whole_brain: 1},
    seedDraft: 'DNa',
  };
  assert.deepEqual(readBuildDraft(build), {
    request: {
      name: 'lc10',
      seeds: ['LC10'],
      hops: 2,
      threshold: 5,
      cap: 3000,
      whole_brain: false,
      balance_sides: false,
    },
    seedDraft: 'DNa',
  });
  // Drafts from before v0.6 have no balance_sides; a saved true is kept.
  const balanced = {...build, request: {...build.request, whole_brain: false, balance_sides: true}};
  assert.equal(readBuildDraft(balanced).request.balance_sides, true);
  assert.equal(readBuildDraft({request: {name: 'x'}}), null);
  assert.deepEqual(readConnectivityDraft({key: 'abc', threshold: 0, search: 'DN'}), {
    key: 'abc',
    threshold: 1,
    search: 'DN',
  });
  assert.equal(readConnectivityDraft({key: 'abc'}), null);
});

test('every page lives in the hash and survives a round trip', () => {
  assert.equal(parseHash('#/workbench').route, 'workbench');
  assert.equal(parseHash('#/connectome/build').route, 'build');
  for (const id of ['overview', 'protocols', 'library', 'explorer', 'atlas', 'agents'])
    assert.equal(parseHash(routeHash(id)).route, id);
});
