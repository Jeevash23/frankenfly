import test from 'node:test';
import assert from 'node:assert/strict';
import {
  cardLabel,
  finishedScorecards,
  keyFor,
  pickCard,
  requestFor,
  resultDetail,
  STATUS_MARK,
  STATUS_TEXT,
} from '../src/scorecard.ts';

const connectome = {
  neural_model: 'connectome',
  connectome_parameters: {circuit: 'fafb783-steering', dynamics: 'spiking'},
};

test('the Workbench model becomes a scorecard request and its file name', () => {
  const r = requestFor(connectome, 'toy');
  assert.deepEqual(r, {
    model: 'connectome',
    circuit: 'fafb783-steering',
    dynamics: 'spiking',
    engine: 'toy',
  });
  assert.equal(keyFor(r), 'connectome-fafb783-steering-spiking-toy');
  const engineered = requestFor({neural_model: 'engineered', connectome_parameters: {}}, 'flygym');
  assert.deepEqual(engineered, {
    model: 'engineered',
    circuit: null,
    dynamics: 'rate',
    engine: 'flygym',
  });
  assert.equal(keyFor(engineered), 'engineered-flygym');
  assert.equal(keyFor(requestFor(undefined, 'toy')), 'engineered-toy');
});

test('the shown card is the requested one, or the newest', () => {
  const cards = [{key: 'b'}, {key: 'a'}];
  assert.equal(pickCard(cards, 'a').key, 'a');
  assert.equal(pickCard(cards, 'missing').key, 'b');
  assert.equal(pickCard([], 'a'), null);
});

test('finished scorecard jobs are counted once', () => {
  const job = (id, status, kind = 'scorecard') => ({id, status, kind});
  const before = [job('1', 'running'), job('2', 'done'), job('3', 'running', 'replay')];
  const after = [
    job('1', 'done'),
    job('2', 'done'),
    job('3', 'done', 'replay'),
    job('4', 'failed'),
  ];
  assert.equal(finishedScorecards(before, after), 2);
  assert.equal(finishedScorecards(after, after), 0);
});

test('every status has a word and a mark, and results say why there is no number', () => {
  assert.deepEqual(Object.keys(STATUS_TEXT).sort(), Object.keys(STATUS_MARK).sort());
  assert.equal(
    resultDetail({measured: {text: 'ratio 1.17', value: 1.17, unit: ''}, reasons: []}),
    'ratio 1.17',
  );
  assert.equal(resultDetail({measured: null, reasons: ['a', 'b']}), 'a; b');
  assert.equal(
    cardLabel({model: {label: 'fafb783-dna02 · rate'}, engine: 'flygym'}),
    'fafb783-dna02 · rate · FlyGym body',
  );
});
