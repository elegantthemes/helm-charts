DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a RWO `/workspace` volume.

## Intake vs consumer (chart 1.2.0)

Default is unchanged: one Deployment, Service selects it, Ingress `/` goes there.

To stop dropping Slack/webhooks on consumer drain (DeepHive#164):

1. Ship a DeepHive app version with `yarn start:intake`.
2. Ship a `elegantthemes/deephive` image that honors `DEEPHIVE_ROLE` (`intake` | `consumer` | `all`).
3. Set `INTAKE_ENABLED=true`. Intake pods boot (no PVC, `maxSurge: 1`) but Ingress still targets the consumer. Slack stays on the consumer (`DEEPHIVE_SERVE_INTAKE` unset).
4. When intake is Ready, set `INTAKE_CUTOVER=true`. Ingress `/` (Slack, `/webhook`) goes to intake. `/admin`, `/graph`, `/stream`, `/api` stay on the consumer. Consumer sets `DEEPHIVE_SERVE_INTAKE=false` so it does not also ack Slack.

Consumer `terminationGracePeriodSeconds` defaults to 1800 so SIGTERM drain can finish Cursor jobs. Intake is 60s.

Do not set `INTAKE_CUTOVER` without `INTAKE_ENABLED`. Do not run two intake HTTP processes against Slack (cutover while consumer still serves intake).
