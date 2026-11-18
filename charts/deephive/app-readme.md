# DeepHive workspace storage

With protocols 2 and 3, Lite and Full each use a Linode block ReadWriteOnce
claim on their own node. The workspace root is the same canonical absolute
path on both claims. The existing
promotion/return lifecycle streams a stopped task workspace between the private
consumer/controller Services before admitting its next writer. Transfer topology
is rendered inside existing readiness configuration; authentication reuses the
platform-only shared ADMIN_API_KEY, never a session credential.

Portable fs.cp/tar replaces native JuiceFS clones. Capacity checks probe local
scratch and each process's mounted workspace, not a retained JuiceFS cache.
Future prepared seeds export onto the consumer claim/node. Full receives its
source copy before Pod creation in protocols 2 and 3.

With protocol 4, the controller mounts the existing Lite claim on the Lite
node for stopped-source handoff. Full session Pods run on separate disposable
nodes and use local volumes. The old Full claim is retained for rollback.

sourceReaderService.enabled must be false; the retired CSI broker/resources must
be drained before upgrade removes their protections. Both new PVCs use Helm's
keep annotation; the prior claim must be annotated before changing release values.

See [cutover, artifact order and rollback](remove-juicefs.md). The chart does not
migrate existing data or authorize storage deletion.
