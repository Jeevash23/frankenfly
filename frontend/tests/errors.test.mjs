import test from 'node:test';
import assert from 'node:assert/strict';
import {describeError} from '../src/errors.ts';

test('validation errors become readable sentences instead of JSON', () => {
  const detail = [
    {
      location: ['body', 'protocol'],
      message: 'Value error, Event steps must be unique, sorted, and before the protocol end.',
      type: 'value_error',
    },
  ];
  assert.equal(
    describeError(detail, 422),
    'protocol: Event steps must be unique, sorted, and before the protocol end.',
  );
});

test('plain messages pass through and unknown errors stay generic', () => {
  assert.equal(
    describeError('Step is available only while paused.', 409),
    'Step is available only while paused.',
  );
  assert.equal(describeError(undefined, 502), 'The local command failed (HTTP 502).');
});
