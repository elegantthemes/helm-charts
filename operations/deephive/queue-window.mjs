import { createHash, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const LITE_QUEUES = [
	'deepvibe-queue',
	'triage-queue',
	'dupe-detection-queue',
	'checkout-queue',
	'fix-queue',
	'feedback-queue',
	'feedback-agentic-queue',
	'orchestrator-queue',
	'cleanup-queue',
	'scheduled-task-queue',
	'model-repo-refresh-queue',
	'retro-queue',
	'agent-merge-queue',
	'slack-intake-queue',
	'webhook-intake-queue',
	'discord-intake-queue',
];
export const AUTO_MS = 330 * 60_000;
export const HARD_MS = 360 * 60_000;
export const canaryQueue = (id) => `deephive-rollout-canary-${id}`;

export function initialRecord(id, scope, now, scriptHash) {
	if (!/^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/.test(id) || !['lite', 'canary'].includes(scope)) {
		throw new Error('Invalid operation identity');
	}
	return {
		version: 1,
		id,
		scope,
		scriptHash,
		phase: 'waiting',
		readyAt: now,
		names: scope === 'lite' ? [...LITE_QUEUES] : [canaryQueue(id)],
		queues: [],
	};
}

/** One bounded step; the persisted intent precedes every native pause call. */
export async function advance(state, command, io) {
	const now = await io.now();
	if (state.phase === 'complete') return;
	if (state.phase === 'waiting') {
		if (command === 'resume' || now - state.readyAt >= 20 * 60_000) {
			state.phase = 'complete';
			state.completedAt = now;
			await io.save(state);
			return;
		}
		if (command !== 'arm') return;
		if (!(await io.claimScope())) throw new Error('Another window owns pickup control');
		state.startedAt = now;
		state.autoResumeAt = now + (state.scope === 'lite' ? AUTO_MS : 20_000);
		state.hardResumeAt = now + (state.scope === 'lite' ? HARD_MS : 300_000);
		state.queues = await Promise.all(
			state.names.map(async (name) => ({
				name,
				originalPaused: await io.isPaused(name),
			})),
		);
		state.phase = 'pausing';
		await io.save(state);
		return;
	}
	if (command === 'resume' || now >= state.autoResumeAt) {
		state.phase = 'resuming';
		await io.save(state);
	}
	if (state.phase === 'pausing') {
		const entry = state.queues.find(
			(q) => !q.originalPaused && !q.skippedExisting && q.pausedAt === undefined,
		);
		if (!entry) {
			state.phase = 'paused';
			await io.save(state);
			return;
		}
		// Respect a pause another operator added after our original snapshot.
		if (entry.intentAt === undefined && (await io.isPaused(entry.name))) {
			entry.skippedExisting = true;
			await io.save(state);
			return;
		}
		entry.recoveredReceipt = entry.intentAt !== undefined;
		entry.intentAt ??= now;
		await io.save(state);
		await io.pause(entry.name);
		entry.pausedAt = await io.now();
		await io.save(state);
		return;
	}
	if (state.phase === 'resuming') {
		const entry = state.queues.find(
			(q) =>
				!q.originalPaused &&
				!q.skippedExisting &&
				q.intentAt !== undefined &&
				q.resumedAt === undefined,
		);
		if (!entry) {
			state.phase = 'complete';
			state.completedAt = now;
			await io.save(state);
			return;
		}
		if (await io.isPaused(entry.name)) await io.resume(entry.name);
		if (await io.isPaused(entry.name)) throw new Error('Native resume did not complete');
		entry.resumedAt = await io.now();
		await io.save(state);
	}
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const unlock = async (redis, key, token) =>
	redis.eval(
		'if redis.call("GET",KEYS[1])==ARGV[1] then return redis.call("DEL",KEYS[1]) end return 0',
		1,
		key,
		token,
	);

async function main() {
	const [mode, id, scope] = process.argv.slice(2);
	if (!['watch', 'arm', 'resume', 'status', 'cleanup'].includes(mode))
		throw new Error('Invalid mode');
	if (process.env.POD_NAMESPACE !== 'dph-app' || !process.env.POD_UID)
		throw new Error('Run inside the staging operation Pod');
	const scriptHash = createHash('sha256')
		.update(readFileSync(new URL(import.meta.url)))
		.digest('hex');
	if (scriptHash !== process.env.EXPECTED_SCRIPT_SHA256)
		throw new Error('Unexpected mounted script');
	const initial = initialRecord(id, scope, Date.now(), scriptHash);
	const require = createRequire('/opt/deephive/package.json');
	const { Queue } = require('bullmq');
	const Redis = require('ioredis');
	if (!process.env.REDIS_URL || (process.env.REDIS_NAME && !process.env.REDIS_HOSTNAME))
		throw new Error('Missing existing Redis configuration');
	const sentinel = process.env.REDIS_NAME
		? {
				name: process.env.REDIS_NAME,
				sentinels: [{ host: process.env.REDIS_HOSTNAME, port: 26379 }],
				failoverDetector: true,
			}
		: {};
	const redis = new Redis(process.env.REDIS_URL, {
		...sentinel,
		maxRetriesPerRequest: 1,
		enableOfflineQueue: false,
		autoResendUnfulfilledCommands: false,
		commandTimeout: 5000,
		connectTimeout: 5000,
		reconnectOnError: (error) => /^(READONLY|MASTERDOWN)\b/.test(error.message),
	});
	redis.on('error', () => {});
	const serverNow = async () => {
		const [seconds, micros] = await redis.time();
		return Number(seconds) * 1000 + Math.floor(Number(micros) / 1000);
	};
	const queues = new Map();
	const key = `deephive:rollout:queue-window:v1:${id}`;
	const scopeKey = scope === 'lite' ? 'deephive:rollout:queue-window:active' : `${key}:active`;
	const token = `${process.env.POD_UID}:${randomUUID()}`;
	try {
		if (redis.status !== 'ready')
			await new Promise((done, fail) => {
				redis.once('ready', done);
				redis.once('error', fail);
			});
		for (const name of initial.names) {
			const queue = new Queue(name, { connection: redis });
			queue.on('error', () => {});
			queues.set(name, queue);
		}
		const load = async () => {
			const raw = await redis.hget(key, 'record');
			const state = raw && JSON.parse(raw);
			if (
				!state ||
				state.id !== id ||
				state.scope !== scope ||
				state.scriptHash !== scriptHash ||
				JSON.stringify(state.names) !== JSON.stringify(initial.names)
			)
				throw new Error('Operation record does not match');
			return state;
		};
		const io = {
			now: serverNow,
			save: async (state) => {
				const transaction = redis.multi().hset(key, 'record', JSON.stringify(state));
				// Once armed, recovery metadata must outlive an extended Redis outage.
				if (state.startedAt !== undefined && state.phase !== 'complete')
					transaction.persist(key);
				else transaction.expire(key, 86400);
				const results = await transaction.exec();
				if (!results || results.some(([error]) => error))
					throw new Error('Journal save failed');
			},
			isPaused: (name) => queues.get(name).isPaused(),
			pause: (name) => queues.get(name).pause(),
			resume: (name) => queues.get(name).resume(),
			claimScope: async () =>
				(await redis.set(scopeKey, id, 'PX', 8 * 60 * 60_000, 'NX')) === 'OK' ||
				(await redis.get(scopeKey)) === id,
		};
		if (mode === 'watch') {
			initial.readyAt = await serverNow();
			await redis.eval(
				'if redis.call("EXISTS",KEYS[1])==0 then redis.call("HSET",KEYS[1],"record",ARGV[1]); redis.call("EXPIRE",KEYS[1],86400) end return 1',
				1,
				key,
				JSON.stringify(initial),
			);
			for (;;) {
				if (await redis.set(`${key}:lock`, token, 'PX', 60_000, 'NX')) {
					try {
						const state = await load();
						await advance(state, await redis.hget(key, 'command'), io);
						await redis.hset(
							key,
							'heartbeatAt',
							await serverNow(),
							'podUid',
							process.env.POD_UID,
						);
						if (state.phase === 'complete') {
							await unlock(redis, scopeKey, id);
							console.log(JSON.stringify(state));
							break;
						}
					} catch (error) {
						// Never print connection strings, credentials, or command arguments.
						console.error(
							JSON.stringify({ event: 'retry', name: error.name, code: error.code }),
						);
					} finally {
						await unlock(redis, `${key}:lock`, token).catch(() => {});
					}
				}
				await sleep(250);
			}
		} else {
			const state = await load();
			if (mode === 'arm') {
				const heartbeat = Number(await redis.hget(key, 'heartbeatAt'));
				if (state.phase !== 'waiting' || (await serverNow()) - heartbeat > 5000)
					throw new Error('Watchdog is not ready');
				await redis.hset(key, 'command', 'arm');
			} else if (mode === 'resume') {
				await redis.hset(key, 'command', 'resume');
			} else if (mode === 'cleanup') {
				if (state.phase !== 'complete') throw new Error('Cannot remove active recovery');
				for (const q of state.queues)
					if (q.intentAt !== undefined && (await io.isPaused(q.name)))
						throw new Error('A queue remains paused');
				await unlock(redis, scopeKey, id);
				await redis.del(key);
			}
			console.log(
				JSON.stringify({
					...state,
					heartbeatAt: Number(await redis.hget(key, 'heartbeatAt')),
					podUid: await redis.hget(key, 'podUid'),
				}),
			);
		}
	} finally {
		await Promise.allSettled([...queues.values()].map((q) => q.close()));
		await redis.quit().catch(() => redis.disconnect());
	}
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
	main().catch((error) => {
		console.error(JSON.stringify({ event: 'failed', name: error.name, code: error.code }));
		process.exitCode = 1;
	});
}
