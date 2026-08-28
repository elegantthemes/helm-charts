DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a RWO `/workspace` volume.

Design, glossary, four-repo map, and deploys: DeepHive `specs/intake-drain-consumer.md` ([DeepHive#164](https://github.com/elegantthemes/DeepHive/issues/164)).

## Intake vs consumer (chart 1.2.0)

Two Deployments:

- **Intake** (`DEEPHIVE_ROLE=intake`): Slack, webhooks, Discord gateway. No PVC. `maxSurge: 1`. Service `deephive` (Ingress `/`).
- **Consumer** (`DEEPHIVE_ROLE=consumer`): `app.ts` admin + `worker.ts`. RWO `/workspace`. `maxSurge: 0`. Service `deephive-consumer` (`/admin`, `/graph`, `/stream`, `/api`).

First apply of this chart against today’s one-pod app: Slack/Discord/webhooks are down until the intake pods are Ready (fetch/build). After that, intake rolling deploys keep an old Ready replica until the new one is Ready. Consumer deploys drain in-flight Cursor jobs (grace 1800s).

Requires DeepHive app with `yarn start:intake` and image `elegantthemes/deephive` that honors `DEEPHIVE_ROLE`.
