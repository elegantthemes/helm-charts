# DeepVibe media and WordPress connections

DeepHive [PR #339](https://github.com/elegantthemes/DeepHive/pull/339) can deploy
without either connection. Planning, source editing and reviews use the existing
Redis configuration; media uploads remain unavailable until configured.

Use the canonical Terraform app workspace (`apps/deephive/stage`, workspace
`elegantthemes/deephive-stage-v2`) to provision media and supply optional WordPress variables. The
shared module generates `ENV_FILE`; this chart already stores it in Secret
`secrets`, key `.env`, and mounts `/config` read-only into intake and consumer.
Both deployment checksums roll on changes. Do not add separate Helm values or
plaintext container environment entries for the same credentials. The existing ENV_FILE transport needs no template changes.

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
switch allows all origins. The chart transports configuration only. No new values or provider logic are
needed here. This guide lives outside the packaged chart, so no chart release is
required for this documentation-only companion.

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
