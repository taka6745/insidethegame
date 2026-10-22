import test from 'node:test';
import assert from 'node:assert/strict';
import { clock, eventSeconds, replaySeconds, teamNames } from '../lab/format.ts';

test('match clock preserves football minutes past an hour', () => {
  assert.equal(clock(4025), '67:05');
  assert.equal(clock(5701), '95:01');
});

test('clock reads the displayed match time, else the minute', () => {
  assert.equal(eventSeconds({ match_time_seconds: 4025 }), 4025);
  assert.equal(eventSeconds({ minute: 67 }), 4020);
});

test('team labels accept names and normalized objects', () => {
  assert.deepEqual(teamNames({ home: 'Chelsea', away: 'United' }), ['Chelsea', 'United']);
  assert.deepEqual(teamNames([{ id: 'CHE', name: 'Chelsea' }, { id: 'MUN', name: 'United' }]), ['Chelsea', 'United']);
});

test('late corrections do not rewind the displayed match clock', () => {
  assert.equal(replaySeconds([{ match_time_seconds: 4200 }, { match_time_seconds: 3900, revision: 2 }]), 4200);
  assert.equal(replaySeconds([]), 0);
});
