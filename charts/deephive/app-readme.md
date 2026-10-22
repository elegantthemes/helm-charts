DeepHive

Slack Events HTTP, GitHub/ZenHub webhooks, Discord, BullMQ workers, and a configurable persistent `/workspace` volume.

Design: DeepHive `specs/intake-drain-consumer.md` ([DeepHive#164](https://github.com/elegantthemes/DeepHive/issues/164)).

## Intake vs consumer (chart 1.2.2)

Two Deployments:

- **Intake** (`DEEPHIVE_ROLE=intake`): Slack, webhooks, Discord gateway. No PVC. RollingUpdate `maxSurge: 0` `maxUnavailable: 1`, default 2 replicas. Service `deephive` (Ingress `/`). The 2Gi memory limit covers the dependency install + TypeScript build performed at container startup.
- **Consumer** (`DEEPHIVE_ROLE=consumer`): `app.ts` admin + `worker.ts`. Persistent `/workspace`. `maxSurge: 0`. Service `deephive-consumer` (`/admin`, `/graph`, `/stream`, `/api`).

Intake rolls **one replica at a time**: `maxUnavailable: 1` with 2 replicas means Kubernetes will not take both down — at least one Ready intake stays on `deephive`. `maxSurge: 0` means it does not add a third pod; it replaces one instance, then the other. Slack Events, GitHub/ZenHub webhooks, and Discord stay up on the remaining replica. `/readyz` is Discord connected, recent Discord source replay complete, and Redis accepting work; liveness is `/healthz`. Consumer deploys drain in 120s: stop fetch, interrupt Cursor, stage fix/feedback successors before retiring predecessors, allow a bounded short-job finish window, then exit. Kubernetes grace is 120s consumer / 30s intake. Application deadlines are 90s consumer / 20s intake, with matching outer s6 grace (not the 3s default). Processor work can pause while the RWO consumer Recreates; jobs wait in Redis.

This chart replaces the previous single Deployment. Merge with the matching DeepHive app tag and `DEEPHIVE_ROLE` image in one apply. First cutover (or a roll when **no** intake is Ready) is the only time Slack/Discord HTTP is down until a new intake passes `/readyz`.

## Workspace cutover

Defaults preserve the existing `<release>-workspace` Linode `ReadWriteOnce` claim. Staging selects `WORKSPACE_CLAIM_NAME: deephive-workspace-rwx`, `WORKSPACE_ACCESS_MODES: [ReadWriteMany]`, and `WORKSPACE_STORAGE_CLASS_NAME: juicefs-rwx`. This creates a fresh 250Gi workspace; no existing data is copied.

With `LEGACY_WORKSPACE_RETAIN: true`, the chart continues rendering the original 250Gi Linode RWO claim with `helm.sh/resource-policy: keep`. The active claim must have a different name. Keep the legacy settings aligned with the existing PVC; do not change its immutable storage class or access modes.

Before applying, verify that the JuiceFS CSI driver and `juicefs-rwx` StorageClass are available. After applying, verify that the new claim is Bound, the consumer mounts it, and the original claim remains. Staging keeps one consumer replica and removes the worker-node hostname pin; RWX storage does not make concurrent consumers safe. Intake remains PVC-free.

## Workspace copy method

`WORKSPACE_COPY_METHOD` controls consumer workspace provisioning. The default `fs.cp` uses portable copying. Set it to `juicefs` to opt into native cloning on a JuiceFS-backed workspace with toolbox image `elegantthemes/deephive:26.10.20` or another image containing the CLI. The application falls back to portable copying if the clone command fails or its source lock times out; Git validation still runs.

Terraform staging exposes this chart value through the `workspace_copy_method` Terraform variable. Set that variable in the Terraform Cloud workspace UI, then plan/apply and verify the consumer rollout and copy-method logs. Set it back to `fs.cp` and apply to disable native cloning. Changing the setting affects future provisioning copies.

## DeepVibe media and WordPress connections

DeepHive [PR #339](https://github.com/elegantthemes/DeepHive/pull/339) can deploy
without either connection. Planning, source editing and reviews use the existing
Redis configuration; media uploads remain unavailable until configured.

Use the canonical Terraform app workspace (`apps/deephive/stage`, workspace
`elegantthemes/deephive-stage-v2`) to provision media and supply optional WordPress variables. The
shared module generates `ENV_FILE`; this chart already stores it in Secret
`secrets`, key `.env`, and mounts `/config` read-only into intake and consumer.
Both deployment checksums roll on changes. Do not add separate Helm values or
plaintext container environment entries for the same credentials. No chart
version bump is needed for these existing capabilities.

Runtime names carried in that file:

- `DEEPVIBE_MEDIA_BUCKET`: dedicated private bucket created by
  [Terraform #39](https://github.com/elegantthemes/terraform/pull/39).
- `DEEPVIBE_MEDIA_ENDPOINT`: generated HTTPS Linode service origin, without a
  bucket path. Required for Linode; omitting it selects Amazon S3 SDK defaults.
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`: Linode region and
  generated bucket-limited key. These names are S3 SDK conventions, not evidence
  of an Amazon AWS deployment. Terraform does not need manual media credentials.
- `DEEPVIBE_WP_SITE_URL`, `DEEPVIBE_WP_USERNAME`,
  `DEEPVIBE_WP_APPLICATION_PASSWORD`: optional dedicated WordPress read-import
  account; supply the complete group or omit it. The password inherits the user's
  capabilities.

Terraform provisions the bucket explicitly as E1 and private, with a dedicated
Linode `read_write` bucket-scoped identity. That permission is broader than a
prefix-scoped AWS IAM policy; do not describe it as PutObject/GetObject-only or
reuse execution-evidence credentials. Terraform manages exact admin-origin POST
CORS through the Linode S3 endpoint, because the Linode provider's simple CORS
switch allows all origins. The chart transports configuration only. No new values,
provider logic, or chart version bump is needed here.

Deploy the endpoint-capable app from #339 before applying Terraform #39; older
app code ignores the custom endpoint. Then verify both deployments roll and test
browser POST, SHA256 HEAD verification, private preview/download and anonymous
access denial against the real E1 bucket. SDK signing tests and configuration
presence do not prove live E1 checksum compatibility. Keep verification fail-closed
and resolve incompatibilities before enabling editorial uploads. WordPress import
requires its separate optional credentials. Never print `.env` or generated keys.

CORS does not grant access. Policies constrain key, size, content type and checksum;
read URLs are short-lived. Do not grant public ACLs or blanket lifecycle expiry:
this storage holds durable source files alongside draft media. No automatic media
cleanup, cloud plan, infrastructure apply or live acceptance is performed by this
chart companion.

Offline contract check (requires Helm and PyYAML):
`python3 tests/deepvibe-env/check.py`.
