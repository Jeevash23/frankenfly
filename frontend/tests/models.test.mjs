import test from 'node:test';
import assert from 'node:assert/strict';
import {
  conditionProblem,
  conditionsFor,
  configForModel,
  firstExperiment,
  modelDrivers,
  modelNames,
  slowdownNote,
} from '../src/models.ts';

const config = {
  engine: 'toy',
  neural_model: 'engineered',
  initial_interventions: {
    zero_left: true,
    zero_right: false,
    silence: 'descending',
    silence_dna02: 'none',
    silence_types: [],
  },
};

test('switching models starts clean and keeps the rest of the configuration', () => {
  const switched = configForModel(config, 'connectome_dna02');
  assert.equal(switched.neural_model, 'connectome_dna02');
  assert.equal(switched.engine, 'toy');
  assert.deepEqual(switched.initial_interventions, {
    zero_left: false,
    zero_right: false,
    silence: 'none',
    silence_dna02: 'none',
    silence_types: [],
  });
  assert.match(modelDrivers.connectome_dna02, /data-derived.*assumed.*engineered/);
  assert.match(modelNames.engineered, /Engineered/);
});

test('each model offers only the comparison conditions it supports', () => {
  assert.ok(conditionsFor('engineered').includes('descending_off'));
  assert.ok(!conditionsFor('engineered').some((c) => c.startsWith('dna02')));
  assert.ok(conditionsFor('engineered').includes('connectome_model'));
  const connectome = conditionsFor('connectome_dna02');
  for (const c of ['dna02_left_off', 'dna02_right_off', 'dna02_both_off', 'cell_type_off'])
    assert.ok(connectome.includes(c));
  assert.ok(!connectome.includes('descending_off') && connectome.includes('engineered_model'));
});

test('comparison problems mirror the server rules in plain sentences', () => {
  assert.equal(conditionProblem(['control', 'dna02_both_off'], 'connectome_dna02', ''), null);
  assert.match(conditionProblem([], 'engineered', ''), /at least one/);
  assert.match(
    conditionProblem(['control', 'dna02_left_off'], 'engineered', ''),
    /not available with the engineered/,
  );
  assert.match(
    conditionProblem(['control', 'descending_off'], 'connectome_dna02', ''),
    /not available with the connectome/,
  );
  assert.match(conditionProblem(['cell_type_off'], 'connectome_dna02', '  '), /cell type/);
  assert.equal(conditionProblem(['cell_type_off'], 'connectome_dna02', 'DNa03'), null);
  assert.match(
    conditionProblem(
      ['control', 'baseline', 'dna02_left_off', 'dna02_right_off', 'dna02_both_off'],
      'connectome_dna02',
      '',
    ),
    /at most four/,
  );
});

test('the first experiment follows the research walkthrough for either model', () => {
  const engineered = firstExperiment('engineered');
  assert.equal(engineered.protocol.name, 'Target reversal');
  assert.equal(engineered.protocol.duration_steps, 200);
  assert.deepEqual(
    engineered.protocol.events.map((e) => e.step),
    [100],
  );
  assert.equal(engineered.seeds, '42, 43');
  assert.deepEqual(engineered.conditions, ['control', 'descending_off']);
  assert.deepEqual(firstExperiment('connectome_dna02').conditions, ['control', 'dna02_both_off']);
  assert.equal(conditionProblem(engineered.conditions, 'engineered', ''), null);
});

test('a real-time factor below 1x is explained plainly, and only while running', () => {
  assert.equal(slowdownNote(0.4, 1, false), null);
  assert.equal(slowdownNote(1.2, 2, true), null);
  assert.match(
    slowdownNote(0.4, 1, true),
    /1 simulated second takes 2\.5 s\. The requested 1× is more than this computer can keep up with/,
  );
  assert.match(slowdownNote(0.25, 0.25, true), /requested 0\.25× speed/);
});
