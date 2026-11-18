# Remove DeepHive JuiceFS

See the [coordinated cutover and rollback instructions](https://github.com/elegantthemes/terraform/blob/7957073eca3abbda9cedcc45e8693791b89e14dc/apps/deephive/REMOVE-JUICEFS.md).

Lite and Full retain their separate nodes and have independent block claims.
The existing Lite-to-Full promotion copies stopped source before session start;
stopped Full changes return to Lite before ownership is released. Drain and copy
the old workspace before cutover, and retain prior storage. No migration, merge,
image publication, deployment or Terraform apply is performed by these PRs.

The stopped-volume cutover requires an `Immediate` workspace StorageClass.
Before the protection-first install, confirm the selected class's
`volumeBindingMode`. `WaitForFirstConsumer` cannot bind while the runner is
disabled or through a Pod pinned with `spec.nodeName`. The live chart render
rejects a class with deferred binding.

The Full runner uses one replica with a `Recreate` strategy. The runner also
holds an exclusive lock on the Full volume root for its entire lifetime, so a
replacement on the same mounted volume cannot start during its predecessor's
shutdown. Before the first upgrade to this chart, a manual replacement, or a
node move, drain Full sessions and wait for source returns. Disable the runner,
confirm the old Pod and its processes have terminated, and for a node move
confirm the volume has detached before enabling the runner on the target node.
If termination is uncertain, keep it disabled until the old node is fenced.
Force-deleting a Pod object is not proof that its processes or writers stopped.
