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
`elegantthemes/deephive-stage-v2`) to supply the optional DeepVibe variables. The
shared module generates `ENV_FILE`; this chart already stores it in Secret
`secrets`, key `.env`, and mounts `/config` read-only into intake and consumer.
Both deployment checksums roll on changes. Do not add separate Helm values or
plaintext container environment entries for the same credentials. No chart
version bump is needed for these existing capabilities.

Runtime names carried in that file:

- `DEEPVIBE_MEDIA_BUCKET` and `AWS_REGION`: an existing private AWS S3 bucket and
  its region. This adapter uses AWS S3, not the separate Linode execution-evidence
  bucket or credentials.
- Optional `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`: a
  dedicated, scoped S3 identity supplied as sensitive Terraform inputs. Leave
  them absent when an already-configured SDK workload identity is available.
- `DEEPVIBE_WP_SITE_URL`, `DEEPVIBE_WP_USERNAME`,
  `DEEPVIBE_WP_APPLICATION_PASSWORD`: a dedicated WordPress account/application
  password for read imports. Use staging for the pilot. Application passwords
  inherit the account's capabilities; choose the account role accordingly.

Provision the bucket and identity through the owning AWS infrastructure process.
This chart does not create AWS resources. Keep Block Public Access enabled and
limit the identity to `s3:PutObject` and `s3:GetObject` on
`arn:aws:s3:::<bucket>/deepvibe/*`. HeadObject verification uses GetObject
permission. If using SSE-KMS, grant the required key permissions for checksum
verification. No bucket listing or deletion permission is required by the app.

Set bucket CORS to allow browser POST uploads from each exact admin origin,
including scheme and port where applicable. For staging this is
`https://deephive.staging.etdevs.com`. Example (replace the origin for other
installations):

```json
{
  "CORSRules": [{
    "AllowedOrigins": ["https://deephive.staging.etdevs.com"],
    "AllowedMethods": ["POST"],
    "AllowedHeaders": ["*"]
  }]
}
```

CORS does not grant bucket access. The signed policy restricts the object key,
size, content type and SHA256 checksum. Never use a public-read bucket or reuse
execution-runner credentials. Media remains private and uses short-lived read
URLs. No automatic media cleanup is enabled.

After a reviewed Terraform apply, confirm both deployments roll, then use the
DeepVibe Connections screen and a staging upload to verify browser POST, checksum
verification, preview/download and source import. Never print runtime `.env` or
credential values to verify their presence. A bucket/region check alone does not
prove credentials, CORS or KMS access work. No infrastructure apply or credential
population is part of this companion PR.

Offline contract check (requires Helm and PyYAML):
`python3 tests/deepvibe-env/check.py`.
