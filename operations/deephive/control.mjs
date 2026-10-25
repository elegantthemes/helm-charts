// Run through stdin inside the existing Lite Pod, from /srv/deephive.
import { createRequire } from 'node:module';
async function main() {
	const [mode, id, hash] = process.argv.slice(2);
	if (
		!['status', 'arm', 'resume', 'cleanup'].includes(mode) ||
		!/^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/.test(id) ||
		!/^[a-f0-9]{64}$/.test(hash)
	)
		throw new Error('Invalid operation command');
	const require = createRequire(process.cwd() + '/package.json');
	require('dotenv').config();
	const { Queue } = require('bullmq');
	const { createRedisConnection } = await import(
		new URL('./dist/src/queues/config.js', 'file://' + process.cwd() + '/')
	);
	const redis = createRedisConnection();
	redis.on('error', () => {});
	const queues = [];
	try {
		const key = `deephive:rollout:queue-window:v1:${id}`;
		const raw = await redis.hget(key, 'record');
		const state = raw && JSON.parse(raw);
		if (!state || state.id !== id || state.scriptHash !== hash)
			throw new Error('Unexpected recovery record');
		const heartbeatAt = Number(await redis.hget(key, 'heartbeatAt'));
		const [seconds, micros] = await redis.time();
		const now = Number(seconds) * 1000 + Math.floor(Number(micros) / 1000);
		if (mode === 'arm') {
			if (state.phase !== 'waiting' || now - heartbeatAt > 5000)
				throw new Error('Watchdog is not ready');
			await redis.hset(key, 'command', 'arm');
		} else if (mode === 'resume') {
			await redis.hset(key, 'command', 'resume');
		}
		const actual = [];
		for (const item of state.queues) {
			const queue = new Queue(item.name, { connection: redis });
			queue.on('error', () => {});
			queues.push(queue);
			actual.push({ name: item.name, paused: await queue.isPaused() });
		}
		if (mode === 'cleanup') {
			if (state.phase !== 'complete') throw new Error('Recovery is not complete');
			for (const q of state.queues) {
				if (q.intentAt !== undefined && actual.find((x) => x.name === q.name)?.paused)
					throw new Error('An owned queue remains paused');
			}
			// Delete only this operation's journal after the completed Job is removed.
			await redis.del(key, `${key}:lock`);
		}
		console.log(
			JSON.stringify({
				...state,
				heartbeatAt,
				podUid: await redis.hget(key, 'podUid'),
				actual,
			}),
		);
	} catch (error) {
		console.error(JSON.stringify({ event: 'failed', name: error.name, code: error.code }));
		process.exitCode = 1;
	} finally {
		await Promise.allSettled(queues.map((q) => q.close()));
		await redis.quit().catch(() => redis.disconnect());
	}
}
main().catch((error) => {
	console.error(JSON.stringify({ event: 'failed', name: error.name, code: error.code }));
	process.exitCode = 1;
});
