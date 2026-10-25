import assert from 'node:assert/strict';
import test from 'node:test';
import { advance, initialRecord, AUTO_MS, HARD_MS, LITE_QUEUES } from './queue-window.mjs';

function fixture(scope = 'canary') {
	let now = 1_000_000;
	let persisted = initialRecord('52548-test', scope, now, 'hash');
	const paused = new Map(persisted.names.map((name) => [name, false]));
	const calls = [];
	const io = {
		now: () => now,
		save: async (state) => {
			persisted = structuredClone(state);
		},
		claimScope: async () => true,
		isPaused: async (name) => paused.get(name),
		pause: async (name) => {
			calls.push(['pause', name]);
			paused.set(name, true);
		},
		resume: async (name) => {
			calls.push(['resume', name]);
			paused.set(name, false);
		},
	};
	return {
		io,
		paused,
		calls,
		load: () => structuredClone(persisted),
		at: (value) => {
			now = value;
		},
	};
}
async function steps(f, command, count) {
	for (let n = 0; n < count; n++) await advance(f.load(), command, f.io);
}

test('automatic recovery uses the original absolute deadline after restart', async () => {
	const f = fixture();
	await steps(f, 'arm', 3);
	const before = f.load();
	assert.equal(before.phase, 'paused');
	f.at(before.autoResumeAt + 1);
	await steps(f, 'arm', 2);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.load().autoResumeAt, before.autoResumeAt);
	assert.equal(f.paused.get(before.names[0]), false);
});

test('Lite uses a thirty-minute margin before six hours', async () => {
	const f = fixture('lite');
	await steps(f, 'arm', 1);
	const state = f.load();
	assert.equal(state.names.length, 16);
	assert.deepEqual(state.names, LITE_QUEUES);
	assert.equal(state.autoResumeAt - state.startedAt, AUTO_MS);
	assert.equal(state.hardResumeAt - state.startedAt, HARD_MS);
	assert.equal(HARD_MS - AUTO_MS, 30 * 60_000);
});

test('pre-existing pauses are never resumed', async () => {
	const f = fixture('lite');
	f.paused.set(LITE_QUEUES[0], true);
	await steps(f, 'arm', 18);
	await steps(f, 'resume', 17);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.paused.get(LITE_QUEUES[0]), true);
	assert.ok(!f.calls.some(([, name]) => name === LITE_QUEUES[0]));
});

test('write-ahead intent recovers a crash after native pause but before receipt', async () => {
	const f = fixture();
	await steps(f, 'arm', 1);
	const pause = f.io.pause;
	f.io.pause = async (name) => {
		await pause(name);
		throw new Error('lost receipt');
	};
	await assert.rejects(steps(f, 'arm', 1));
	const held = f.load();
	assert.ok(held.queues[0].intentAt);
	assert.equal(held.queues[0].pausedAt, undefined);
	f.at(held.autoResumeAt + 1);
	await steps(f, 'arm', 2);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.paused.get(held.names[0]), false);
});

test('an external pause added before our call is left untouched', async () => {
	const f = fixture();
	await steps(f, 'arm', 1);
	f.paused.set(f.load().names[0], true);
	await steps(f, 'arm', 2);
	await steps(f, 'resume', 1);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.paused.get(f.load().names[0]), true);
	assert.deepEqual(f.calls, []);
});

test('early resume stops pausing remaining queues', async () => {
	const f = fixture('lite');
	await steps(f, 'arm', 2);
	await steps(f, 'resume', 2);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.calls.filter(([kind]) => kind === 'pause').length, 1);
	assert.equal(f.calls.filter(([kind]) => kind === 'resume').length, 1);
});

test('an expired idle watchdog cannot start a new pause', async () => {
	const f = fixture();
	f.at(f.load().readyAt + 20 * 60_000);
	await steps(f, 'arm', 1);
	assert.equal(f.load().phase, 'complete');
	assert.deepEqual(f.calls, []);
});

test('a failed resume is retried without extending deadlines', async () => {
	const f = fixture();
	await steps(f, 'arm', 3);
	const deadline = f.load().autoResumeAt;
	const resume = f.io.resume;
	f.io.resume = async () => {
		throw new Error('temporary outage');
	};
	f.at(deadline + 1);
	await assert.rejects(steps(f, 'arm', 1));
	f.io.resume = resume;
	await steps(f, 'arm', 2);
	assert.equal(f.load().phase, 'complete');
	assert.equal(f.load().autoResumeAt, deadline);
});
