DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a RWO `/workspace` volume.

Design, glossary, four-repo map, and cutover: DeepHive `specs/intake-drain-consumer.md` ([DeepHive#164](https://github.com/elegantthemes/DeepHive/issues/164)).

## Intake vs consumer (chart 1.2.0)

Chart default is still one Deployment (`INTAKE_ENABLED=false`) so `helm template` matches today’s pod. **Do not ship a current DeepHive app tag with that default.** Discord `client.login` lives only on `intake.ts`. The consumer `app.ts` does not log in. No `DEEPHIVE_SERVE_DISCORD` flag.

To run Discord (and later Slack/webhooks on drain-safe intake):

1. DeepHive app with `yarn start:intake` and Discord on that process.
2. `elegantthemes/deephive` image that honors `DEEPHIVE_ROLE` (`intake` | `consumer` | `all`).
3. **`INTAKE_ENABLED=true` in the same apply** that rolls that app tag. Intake pods (`DEEPHIVE_ROLE=intake`, no PVC, `maxSurge: 1`) log into Discord. Ingress `/` can still target the consumer so Slack is not dual-acked.
4. Optional later: `INTAKE_CUTOVER=true`. Ingress `/` (Slack, `/webhook`) → intake. `/admin`, `/graph`, `/stream`, `/api` stay on the consumer. Consumer sets `DEEPHIVE_SERVE_INTAKE=false`.

Consumer `terminationGracePeriodSeconds` defaults to 1800 so SIGTERM drain can finish Cursor jobs. Intake is 60s.

Do not set `INTAKE_CUTOVER` without `INTAKE_ENABLED`. Do not run two intake HTTP processes against Slack (cutover while consumer still serves intake).
