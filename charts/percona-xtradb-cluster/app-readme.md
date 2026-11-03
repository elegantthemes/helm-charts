# Percona XtraDB Cluster

Chart 1.20.5 exposes the database image, backup image, update strategy, full backup schedule and PITR switch. Defaults preserve chart 1.20.4 behavior.

| Value | Default |
| --- | --- |
| `pxc.image` | `percona/percona-xtradb-cluster:8.0.45-36.1` |
| `backup.image` | `percona/percona-xtrabackup:8.0.35-35.1` |
| `update_strategy` | `RollingUpdate` |
| `backup.schedule` | `aws`, `1 6/12 * * *`, keep 60, storage `backup-aws-1` |
| `pitr.enabled` | `true` |

Set `backup.schedule: []` to disable future scheduled backups. Set `pitr.enabled: false` separately to disable the collector. Existing backup requests are not canceled by an empty schedule. Use `pxc.mysql_configuration` for additional MySQL settings.

The staging upgrade sequence is documented in the Terraform repository at `docs/runbooks/staging-pxc-upgrade.md`. Image changes, backup suspension and manual member replacements are separate steps in that procedure.

Local regression checks require Helm, Python 3 and PyYAML. From the Helm repository root, run:

```sh
python3 tests/percona-xtradb-cluster.py
```

The script uses local Git history and Helm rendering only. It compares defaults against the accepted 1.20.4 chart and checks each documented phase without contacting a cluster.
