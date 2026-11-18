# Remove DeepHive JuiceFS

See the [coordinated cutover and rollback instructions](https://github.com/elegantthemes/terraform/blob/codex/remove-deephive-juicefs/apps/deephive/REMOVE-JUICEFS.md).

The change requires one node-attached block workspace shared by Lite and Full.
Drain and copy the stopped workspace before changing claims. Retain prior storage.
No migration, merge, image publication, deployment or Terraform apply is performed
by these PRs. Current Full-environment WIP may need storage/scheduling adjustments.
