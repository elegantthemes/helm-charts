# DeepHive workspace storage

Use a Linode block ReadWriteOnce claim. Consumer, Full controller and sessions
share one node and the same canonical workspace root. Chart routing rejects a
multi-node or RWX configuration. Portable copies remain the only provisioning
method. Capacity checks probe local scratch and the mounted workspace itself.

`sourceReaderService.enabled` must be false; its former CSI broker is retired.
The existing upgrade guard requires the broker and transient reader resources
to be drained before its protections can be removed. New active PVCs are retained
with `helm.sh/resource-policy: keep`; prior PVCs require annotation before cutover.

See [migration prerequisites, artifact order and rollback](remove-juicefs.md).
This chart does not migrate existing workspace data or authorize deletion.
