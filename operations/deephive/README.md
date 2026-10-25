# Temporary staging pickup window

This is the specifically authorized DeepHive staging rollout operation, not an
installed chart component. It creates no credentials, RBAC, network policy, source
mount, or persistent workload. Chart content/version remain unchanged.

The Job uses the existing `deephive-full-worker` identity without an API token,
the existing pull Secret, and only the three Redis keys from
`deephive-full-runner`. Its unique label does not match app Service selectors.
The mounted code is immutable and checked against its SHA-256. The ConfigMap is
owned by the Job, whose controller/TTL reclaim it after completion. An unarmed Redis
journal expires after 24 hours. Arming removes that expiry; recovery and its
journal remain available until the recorded pauses are restored. Completed
journals regain the 24-hour fallback expiry. The Job has no
active deadline and retries container failures; TTL cleanup follows completion.

## Contract

Only native BullMQ `Queue.pause()` and `Queue.resume()` change queue pickup.
Active jobs finalize normally. Snapshot all original pause states before the
first pause; never resume a pre-existing pause. Persist intent before each pause,
so a crash cannot hide an uncertain successful pause. A restarted Job keeps the
original absolute deadlines and resumes recorded intents, not arbitrary queues.
The six-hour maximum is conservative from the start of the batch. Automatic
resume starts after **5 hours 30 minutes**, leaving 30 minutes for replacement
and Redis recovery. No controller or journal expiry stops recovery during an extended
Redis outage; the six-hour deadline is never reset or extended. A per-operation 60-second mutex prevents overlapping Job
Pods from rewriting the journal. Redis commands have bounded timeouts and do not
replay offline pause requests. Do not run concurrent manual pause/resume
operations on these queues during this operator window.

All 16 Lite-consumed queues are enumerated in `LITE_QUEUES`; Full session queues
are excluded. A pause added externally before our call is skipped and retained.
An unarmed watchdog exits after 20 minutes. Never extend a window or automatically
start another one to evade the maximum. If automatic resume occurs before a safe
deployment, leave the queues running and hold deployment.

## Review, create and verify before pausing real work

Run `node --test operations/deephive/queue-window.test.mjs`. Merge only with the
required exact-head CI/review results. Use only context `k8s-cluster-stage-v2`,
namespace `dph-app`; the renderer fixes the namespace and approved runner digest.

1. Choose distinct DNS-safe operation IDs for the real window and canary.
2. Render each Job with `python3 operations/deephive/render.py job ID SCOPE`.
   Server-dry-run it, then create it. Read its actual UID. Render/create its
   ConfigMap with `render.py config ID SCOPE --job-uid UID`. Creating the Job
   first lets its ConfigMap have a real owner reference from the start.
3. From the current Lite Pod's `/srv/deephive`, run `control.mjs` through stdin:
   `node --input-type=module - status ID HASH`. Verify the matching code hash,
   fresh heartbeat and Pod UID against the Job's actual Pod/owner reference.
4. Test only the disposable `deephive-rollout-canary-ID` queue. Run
   `canary-worker.mjs` through stdin in that same Lite runtime. Once its first
   15-second job is active, run `control.mjs ... arm ID HASH` for the **canary**.
   Observe the pause, then delete only that canary watchdog Pod (not its Job).
   Require a replacement Pod and the same absolute deadline. The existing active
   job must complete while paused; the second job must run only after automatic
   recovery. The driver records both and removes only its own synthetic queue.
   Its 20-second automatic deadline and five-minute hard bound make this test
   independent of desktop sleep and the future Lite worker replacement.
5. Preserve the canary receipt/old and new Pod identities. Delete the completed
   canary Job; its ConfigMap is garbage-collected. Use `control.mjs cleanup` only
   after completion to remove its own Redis journal. Do not arm real pickup if
   any recovery check fails or requires expanded access.

## Real window and cleanup

Arm the real Job only with fresh matching heartbeat/hash. Wait for phase `paused`
and verify every originally running queue is now paused. Save original states,
actual pause receipts, automatic/hard deadlines, Job UID, Pod UID and code hash.
Observe **active** counts draining; queued/paused/prioritized jobs remain durable
and must not be deleted. Do not interrupt active agents or use Admin Pause Active.

Apply only the fully reviewed staging plan after all active work finishes and
with at least 20 minutes left before automatic resume. Recheck pause state and
deadline immediately before apply. If the timer has resumed queues or work is
still active near the limit, hold deployment. Preserve the original rollback,
source holds, 500 GiB volume, resource/security settings and closed broad routing.

As soon as the deployment is verified, send `control.mjs ... resume ID HASH`.
Require phase `complete` and actual unpaused states for every queue this operation
paused; pre-existing pauses remain untouched. Preserve the receipt and verify
normal queued activity resumes. Then delete only this completed Job/owned
ConfigMap and run `control.mjs cleanup` to remove its own journal. Do not remove
the recovery Job or its journal while any owned queue remains paused. No held
work, task source, real queued jobs or existing Secrets are deleted.
