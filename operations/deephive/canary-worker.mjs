// Disposable native BullMQ proof. This cannot consume a real application queue.
import { createRequire } from 'node:module';
async function main() {
	const [id] = process.argv.slice(2);
	if (!/^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/.test(id)) throw new Error('Invalid canary identity');
	const name = `deephive-rollout-canary-${id}`;
	const require = createRequire(process.cwd() + '/package.json');
	require('dotenv').config();
	const { Queue, Worker } = require('bullmq');
	const { createRedisConnection } = await import(
		new URL('./dist/src/queues/config.js', 'file://' + process.cwd() + '/')
	);
	const redis = createRedisConnection();
	redis.on('error', () => {});
	const queue = new Queue(name, { connection: redis });
	queue.on('error', () => {});
	const events = [];
	const worker = new Worker(
		name,
		async (job) => {
			const event = { job: job.id, startedAt: Date.now() };
			events.push(event);
			console.log(JSON.stringify({ event: 'started', ...event }));
			if (!['first', 'second'].includes(job.id)) throw new Error('Unexpected canary job');
			await new Promise((done) => setTimeout(done, job.id === 'first' ? 15_000 : 500));
			event.finishedAt = Date.now();
			event.pausedAtFinish = await queue.isPaused();
			return 'canary only';
		},
		{ connection: redis, concurrency: 1 },
	);
	worker.on('error', () => {});
	try {
		await worker.waitUntilReady();
		await queue.add('active-proof', { ms: 15_000 }, { jobId: 'first' });
		await queue.add('waiting-proof', { ms: 500 }, { jobId: 'second' });
		const until = Date.now() + 6 * 60_000;
		while (Date.now() < until) {
			const raw = await redis.hget(`deephive:rollout:queue-window:v1:${id}`, 'record');
			const state = raw && JSON.parse(raw);
			if (
				(await queue.getCompletedCount()) === 2 &&
				state?.phase === 'complete' &&
				!(await queue.isPaused())
			)
				break;
			await new Promise((done) => setTimeout(done, 500));
		}
		const counts = await queue.getJobCounts('active', 'completed', 'failed');
		const raw = await redis.hget(`deephive:rollout:queue-window:v1:${id}`, 'record');
		const record = raw && JSON.parse(raw);
		if (
			counts.completed !== 2 ||
			counts.failed ||
			counts.active ||
			record?.phase !== 'complete' ||
			record.completedAt > record.hardResumeAt ||
			(await queue.isPaused())
		)
			throw new Error('Canary recovery incomplete');
		if (
			events.length !== 2 ||
			events[0].pausedAtFinish !== true ||
			events[1].pausedAtFinish !== false
		)
			throw new Error('Active/new pickup contract not observed');
		console.log(
			JSON.stringify({ event: 'verified', queue: name, events, counts, recovery: record }),
		);
		await worker.close();
		await queue.obliterate({ force: false });
	} catch (error) {
		console.error(JSON.stringify({ event: 'failed', name: error.name, code: error.code }));
		process.exitCode = 1;
	} finally {
		await worker.close();
		await queue.close();
		await redis.quit().catch(() => redis.disconnect());
	}
}
main()
	.catch((error) => {
		console.error(JSON.stringify({ event: 'failed', name: error.name, code: error.code }));
		process.exitCode = 1;
	})
	.finally(() => {
		process.stdout.write('', () => process.exit(process.exitCode ?? 0));
	});
