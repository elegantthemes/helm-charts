DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a RWO `/workspace` volume.

Design: DeepHive `specs/intake-drain-consumer.md` ([DeepHive#164](https://github.com/elegantthemes/DeepHive/issues/164)).

## Intake vs consumer (chart 1.2.0)

Two Deployments:

- **Intake** (`DEEPHIVE_ROLE=intake`): Slack, webhooks, Discord gateway. No PVC. `maxSurge: 1`. Service `deephive` (Ingress `/`).
- **Consumer** (`DEEPHIVE_ROLE=consumer`): `app.ts` admin + `worker.ts`. RWO `/workspace`. `maxSurge: 0`. Service `deephive-consumer` (`/admin`, `/graph`, `/stream`, `/api`).

Intake deploys roll (`maxSurge: 1`). Readiness is `/readyz` (Discord connected); liveness is `/healthz`. Consumer deploys drain in 120s: stop fetch, interrupt Cursor, requeue fix/feedback for phase skip, exit. Kubernetes grace is 120s consumer / 30s intake. s6 service grace is aligned (not the 3s default).

This chart replaces the previous single Deployment. Merge with the matching DeepHive app tag and `DEEPHIVE_ROLE` image in one apply. Slack/Discord are down until intake is Ready.
