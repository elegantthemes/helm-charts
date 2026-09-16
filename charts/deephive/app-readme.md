DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a configurable persistent `/workspace` volume.

Design: DeepHive `specs/intake-drain-consumer.md` ([DeepHive#164](https://github.com/elegantthemes/DeepHive/issues/164)).

## Intake vs consumer (chart 1.2.1)

Two Deployments:

- **Intake** (`DEEPHIVE_ROLE=intake`): Slack, webhooks, Discord gateway. No PVC. `maxSurge: 1`. Service `deephive` (Ingress `/`). The 2Gi memory limit covers the dependency install + TypeScript build performed at container startup.
- **Consumer** (`DEEPHIVE_ROLE=consumer`): `app.ts` admin + `worker.ts`. Persistent `/workspace`. `maxSurge: 0`. Service `deephive-consumer` (`/admin`, `/graph`, `/stream`, `/api`).

Intake deploys roll (`maxSurge: 1`). Readiness is `/readyz` (Discord connected, recent Discord source replay complete, and Redis accepting work); liveness is `/healthz`. Consumer deploys drain in 120s: stop fetch, interrupt Cursor, stage fix/feedback successors before retiring predecessors, allow a bounded short-job finish window, then exit. Kubernetes grace is 120s consumer / 30s intake. Application deadlines are 90s consumer / 20s intake, with matching outer s6 grace (not the 3s default).

This chart replaces the previous single Deployment. Merge with the matching DeepHive app tag and `DEEPHIVE_ROLE` image in one apply. Slack/Discord are down until intake is Ready.

## Workspace cutover

Defaults preserve the existing `<release>-workspace` Linode `ReadWriteOnce` claim. Staging selects `WORKSPACE_CLAIM_NAME: deephive-workspace-rwx`, `WORKSPACE_ACCESS_MODES: [ReadWriteMany]`, and `WORKSPACE_STORAGE_CLASS_NAME: juicefs-rwx`. This creates a fresh 250Gi workspace; no existing data is copied.

With `LEGACY_WORKSPACE_RETAIN: true`, the chart continues rendering the original 250Gi Linode RWO claim with `helm.sh/resource-policy: keep`. The active claim must have a different name. Keep the legacy settings aligned with the existing PVC; do not change its immutable storage class or access modes.

Before applying, verify that the JuiceFS CSI driver and `juicefs-rwx` StorageClass are available. After applying, verify that the new claim is Bound, the consumer mounts it, and the original claim remains. Staging keeps one consumer replica and removes the worker-node hostname pin; RWX storage does not make concurrent consumers safe. Intake remains PVC-free.
