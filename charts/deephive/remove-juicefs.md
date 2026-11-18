# Remove DeepHive JuiceFS

See the [coordinated cutover and rollback instructions](https://github.com/elegantthemes/terraform/blob/codex/remove-deephive-juicefs/apps/deephive/REMOVE-JUICEFS.md).

Lite and Full retain their separate nodes and have independent block claims.
The existing Lite-to-Full promotion copies stopped source before session start;
stopped Full changes return to Lite before ownership is released. Drain and copy
the old workspace before cutover, and retain prior storage. No migration, merge,
image publication, deployment or Terraform apply is performed by these PRs.
