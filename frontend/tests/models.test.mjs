import test from 'node:test';
import assert from 'node:assert/strict';
import {
  conditionProblem,
  conditionsFor,
  configForCircuit,
  configForModel,
  firstExperiment,
  groupIndex,
  modelDrivers,
  modelNames,
  modelSwitch,
  neuralStage,
  normalizeModel,
  readoutPairs,
  slowdownNote,
  summaryKey,
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
  const switched = configForModel(config, 'connectome');
  assert.equal(switched.neural_model, 'connectome');
  assert.equal(switched.engine, 'toy');
  assert.deepEqual(switched.initial_interventions, {
    zero_left: false,
    zero_right: false,
    silence: 'none',
    silence_dna02: 'none',
    silence_types: [],
  });
  assert.match(modelDrivers.connectome, /data-derived.*assumed.*engineered/);
  assert.equal(normalizeModel('connectome_dna02'), 'connectome'); // runs recorded with v0.3
  assert.equal(normalizeModel('connectome'), 'connectome');
  assert.equal(normalizeModel(undefined), 'engineered');
  assert.match(modelNames.engineered, /Engineered/);
});

test('each model offers only the comparison conditions it supports', () => {
  assert.ok(conditionsFor('engineered').includes('descending_off'));
  assert.ok(!conditionsFor('engineered').some((c) => c.startsWith('dna02')));
  assert.ok(conditionsFor('engineered').includes('connectome_model'));
  const connectome = conditionsFor('connectome');
  for (const c of ['dna02_left_off', 'dna02_right_off', 'dna02_both_off', 'cell_type_off'])
    assert.ok(connectome.includes(c));
  assert.ok(!connectome.includes('descending_off') && connectome.includes('engineered_model'));
});

test('comparison problems mirror the server rules in plain sentences', () => {
  assert.equal(conditionProblem(['control', 'dna02_both_off'], 'connectome', ''), null);
  assert.match(conditionProblem([], 'engineered', ''), /at least one/);
  assert.match(
    conditionProblem(['control', 'dna02_left_off'], 'engineered', ''),
    /not available with the engineered/,
  );
  assert.match(
    conditionProblem(['control', 'descending_off'], 'connectome', ''),
    /not available with the connectome/,
  );
  assert.match(conditionProblem(['cell_type_off'], 'connectome', '  '), /cell type/);
  assert.equal(conditionProblem(['cell_type_off'], 'connectome', 'DNa03'), null);
  assert.match(
    conditionProblem(
      ['control', 'baseline', 'dna02_left_off', 'dna02_right_off', 'dna02_both_off'],
      'connectome',
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
  assert.deepEqual(firstExperiment('connectome').conditions, ['control', 'dna02_both_off']);
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

test('a new circuit starts from its own default populations; new dynamics keep them', () => {
  const base = {
    ...config,
    neural_model: 'connectome',
    connectome_parameters: {
      circuit: 'fafb783-dna02',
      dynamics: 'rate',
      readout_types: ['DNa02'],
      input_types: ['LC10a'],
      speed_types: ['DNp09'],
      output_gain: 2,
    },
  };
  const spiking = configForCircuit(base, 'fafb783-dna02', 'spiking');
  assert.equal(spiking.connectome_parameters.dynamics, 'spiking');
  assert.deepEqual(spiking.connectome_parameters.readout_types, ['DNa02']);
  const other = configForCircuit(base, 'fafb783-steering', 'rate');
  assert.equal(other.connectome_parameters.circuit, 'fafb783-steering');
  assert.equal(other.connectome_parameters.readout_types, null);
  assert.equal(other.connectome_parameters.input_types, null);
  assert.deepEqual(other.connectome_parameters.speed_types, []);
  assert.equal(other.connectome_parameters.output_gain, 2);
  assert.equal(other.initial_interventions.silence, 'none');
});

test('DNa02 conditions disappear for circuits without DNa02', () => {
  const without = conditionsFor('connectome', false);
  assert.ok(!without.some((c) => c.startsWith('dna02')) && without.includes('cell_type_off'));
  assert.match(
    conditionProblem(['control', 'dna02_left_off'], 'connectome', '', false),
    /needs a circuit that contains DNa02/,
  );
  assert.deepEqual(firstExperiment('connectome', false).conditions, ['control', 'left_sensor_off']);
});

test('readout rates and trace groups follow the server order: L, R per readout type, then inputs', () => {
  assert.deepEqual(readoutPairs(['DNa01', 'DNa02']), [
    {name: 'DNa01', left: 0, right: 1},
    {name: 'DNa02', left: 2, right: 3},
  ]);
  assert.equal(groupIndex('readout:1', 3), 2);
  assert.equal(groupIndex('input', 3), 6);
  assert.equal(groupIndex('input', 1), 2); // the v0.3 layout: DNa02 L, R, then inputs
  assert.equal(groupIndex('descending', 0), 4);
});

const parameters = {
  circuit: 'mine',
  dynamics: 'rate',
  synapse_threshold: 5,
  global_gain: 0.002,
  input_gain: 1,
  output_gain: 2,
  tonic_drive: 0.35,
  tau_ms: 20,
  other_transmitters: 'excluded',
  readout_types: null,
  input_types: null,
  speed_types: [],
  speed_gain: 1,
  spiking: {synapse_weight_mv: 0.275, input_rate_hz: 150, rate_window_ms: 50, rate_scale_hz: 100},
};

test('the circuit summary is cached per circuit file and structure, not per gain', () => {
  const key = summaryKey(parameters, 'aaa');
  // Gains, tonic drive, time constants and dynamics do not change the summary.
  for (const change of [
    {global_gain: 0.01},
    {input_gain: 2},
    {output_gain: 5},
    {tonic_drive: 0.5},
    {tau_ms: 40},
    {dynamics: 'spiking'},
    {spiking: {...parameters.spiking, rate_scale_hz: 50}},
  ])
    assert.equal(summaryKey({...parameters, ...change}, 'aaa'), key, JSON.stringify(change));
  // A rebuilt file under the same name, or a structural parameter, does.
  assert.notEqual(summaryKey(parameters, 'bbb'), key);
  for (const change of [
    {circuit: 'other'},
    {synapse_threshold: 10},
    {other_transmitters: 'excitatory'},
    {readout_types: ['DNa01']},
    {input_types: ['LC10a']},
    {speed_types: ['DNp09']},
  ])
    assert.notEqual(summaryKey({...parameters, ...change}, 'aaa'), key, JSON.stringify(change));
  // Servers before v0.6 send no hash.
  assert.equal(summaryKey(parameters, undefined), summaryKey(parameters, null));
});

test('leaving the connectome model with FlyVis eyes also switches the sensor, and says so', () => {
  const flyvis = modelSwitch({sensor_model: 'flyvis'}, 'engineered');
  assert.deepEqual(flyvis.override, {neural_model: 'engineered', sensor_model: 'vision'});
  assert.match(flyvis.note, /FlyVis eyes drive only the connectome model/);
  assert.deepEqual(modelSwitch({sensor_model: 'vision'}, 'engineered'), {
    override: {neural_model: 'engineered'},
    note: null,
  });
  assert.deepEqual(modelSwitch({sensor_model: 'flyvis'}, 'connectome').override, {
    neural_model: 'connectome',
  });
  const switched = configForModel({...config, sensor_model: 'flyvis'}, 'engineered');
  assert.equal(switched.sensor_model, 'vision');
});

test('a comparison with FlyVis eyes does not offer the engineered model', () => {
  assert.ok(conditionsFor('connectome', true, 'vision').includes('engineered_model'));
  const flyvis = conditionsFor('connectome', true, 'flyvis');
  assert.ok(!flyvis.includes('engineered_model') && flyvis.includes('dna02_both_off'));
  assert.match(
    conditionProblem(['control', 'engineered_model'], 'connectome', '', true, 'flyvis'),
    /cannot use FlyVis eyes/,
  );
  assert.equal(conditionProblem(['control', 'engineered_model'], 'connectome', ''), null);
});

test('the loop names the neural stage of the model that runs', () => {
  assert.equal(neuralStage({neural_model: 'engineered'}), '6 rate units');
  assert.equal(
    neuralStage({neural_model: 'connectome', connectome_parameters: {dynamics: 'rate'}}),
    'Connectome circuit · rate',
  );
  assert.equal(
    neuralStage({neural_model: 'connectome', connectome_parameters: {dynamics: 'spiking'}}),
    'Connectome circuit · spiking',
  );
});
