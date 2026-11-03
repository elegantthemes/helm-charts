#!/usr/bin/env python3
"""Render upgrade phases locally. Requires Helm and PyYAML; no cluster access."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = "charts/percona-xtradb-cluster"
BASE = "37ee404794f524f062752b875f3c7303aefc1e91"
PXC_INITIAL = "percona/percona-xtradb-cluster:8.0.45-36.1"
PXC_80 = "percona/percona-xtradb-cluster:8.0.46-38.1"
PXC_84 = "percona/percona-xtradb-cluster:8.4.8-8.1"
XB_INITIAL = "percona/percona-xtrabackup:8.0.35-35.1"
XB_80 = "percona/percona-xtrabackup:8.0.35-36.1"
XB_84 = "percona/percona-xtrabackup:8.4.0-5.1"
SCHEDULE = [{"name": "aws", "schedule": "1 6/12 * * *", "keep": 60, "storageName": "backup-aws-1"}]
TUNING = ["innodb_io_capacity=200", "innodb_io_capacity_max=2000", "temptable_max_ram=1073741824"]
IST = ["wsrep_sst_method=ist_only"]
COMMON = {
    "cluster_name": "db-cluster-1",
    "label_name": "io.cattle.field/appId",
    "label_value": "percona-xtradb-cluster",
    "secrets_name": "db-cluster-1-passwords",
    "ssl_secrets_name": "db-cluster-1-ssl",
    "ssl_internal_secrets_name": "db-cluster-1-ssl-internal",
    "vault_secrets_name": "db-cluster-1-vault",
    "pitr": {"resources": {"limits": {"cpu": "1", "memory": "5G"}}},
    "pmm": {"enabled": True},
    "backup_replication": {
        "enabled": True, "schedule": "1 8/12 * * *", "image": "rclone/rclone:1.73.4",
        "resources": {"limits": {"memory": "512Mi", "cpu": "500m"}},
    },
}
for suffix in ["aws_1", "2", "3", "4", "pitr_1"]:
    COMMON[f"s3_bucket_name_backup_{suffix}"] = f"test-backup-{suffix}"
    COMMON[f"s3_secret_name_backup_{suffix}"] = f"test-secret-{suffix}"
    COMMON[f"s3_region_backup_{suffix}"] = "us-east-2"
    COMMON[f"s3_endpoint_backup_{suffix}"] = "https://example.invalid"


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True)


def render(chart, common_file, overrides, scratch):
    override_file = scratch / "overrides.json"
    override_file.write_text(json.dumps(overrides))
    output = command("helm", "template", "percona-xtradb-cluster", str(chart),
                     "--namespace", "pxc-cluster", "-f", str(common_file), "-f", str(override_file))
    documents = [doc for doc in yaml.safe_load_all(output) if doc]
    return {(doc["kind"], doc["metadata"]["name"]): doc for doc in documents}


def main():
    # Read the accepted 1.20.4 baseline from Git without checking out a branch.
    with tempfile.TemporaryDirectory(prefix="pxc-render-") as directory:
        scratch = Path(directory)
        baseline = scratch / "baseline"
        for filename in command("git", "ls-tree", "-r", "--name-only", BASE, CHART).splitlines():
            destination = baseline / Path(filename).relative_to(CHART)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(command("git", "show", f"{BASE}:{filename}"))
        common_file = scratch / "common.json"
        common_file.write_text(json.dumps(COMMON))
        original = render(baseline, common_file, {}, scratch)
        current = render(ROOT / CHART, common_file, {}, scratch)
        assert original == current, "Default rendering changed existing resources"
        print("PASS: complete default manifests match accepted chart 1.20.4")
        print(command("helm", "lint", str(ROOT / CHART), "-f", str(common_file)).strip())
        key = ("PerconaXtraDBCluster", "db-cluster-1")
        # Each tuple is an independently rendered desired state, never an apply.
        phases = [
            ("A", PXC_INITIAL, XB_INITIAL, "RollingUpdate", SCHEDULE, True, []),
            ("intermediate preparation", PXC_INITIAL, XB_INITIAL, "OnDelete", [], True, []),
            ("intermediate suspension", PXC_INITIAL, XB_INITIAL, "OnDelete", [], False, []),
            ("intermediate backup selection", PXC_INITIAL, XB_80, "OnDelete", [], False, []),
            ("intermediate transition", PXC_80, XB_80, "OnDelete", [], False, IST),
            ("intermediate cleanup", PXC_80, XB_80, "OnDelete", [], False, []),
            ("B / intermediate recovery", PXC_80, XB_80, "OnDelete", [], True, []),
            ("intermediate deferred", PXC_80, XB_80, "OnDelete", SCHEDULE, True, []),
            ("C", PXC_80, XB_80, "OnDelete", [], False, []),
            ("D", PXC_84, XB_80, "OnDelete", [], False, TUNING + IST),
            ("E", PXC_84, XB_84, "OnDelete", [], False, TUNING),
            ("F", PXC_84, XB_84, "OnDelete", [], True, TUNING),
            ("G", PXC_84, XB_84, "OnDelete", SCHEDULE, True, TUNING),
            ("false alone", PXC_INITIAL, XB_INITIAL, "RollingUpdate", SCHEDULE, False, []),
            ("empty alone", PXC_INITIAL, XB_INITIAL, "RollingUpdate", [], True, []),
            ("false and empty", PXC_INITIAL, XB_INITIAL, "RollingUpdate", [], False, []),
            ("SmartUpdate passthrough", PXC_INITIAL, XB_INITIAL, "SmartUpdate", SCHEDULE, True, []),
        ]
        for name, pxc, backup, strategy, schedule, pitr, configuration in phases:
            actual = render(ROOT / CHART, common_file, {
                "pxc": {"image": pxc, "mysql_configuration": configuration},
                "backup": {"image": backup, "schedule": schedule},
                "update_strategy": strategy, "pitr": {"enabled": pitr},
            }, scratch)
            expected = copy.deepcopy(original)
            spec = expected[key]["spec"]
            spec["pxc"]["image"] = pxc
            spec["backup"]["image"] = backup
            spec["updateStrategy"] = strategy
            spec["backup"]["schedule"] = schedule
            spec["backup"]["pitr"]["enabled"] = pitr
            if configuration:
                extra = "\n".join(configuration) + "\n"
                spec["pxc"]["configuration"] = spec["pxc"]["configuration"].replace("[sst]\n", extra + "[sst]\n")
            assert type(actual[key]["spec"]["backup"]["pitr"]["enabled"]) is bool
            assert actual == expected, f"Unexpected resource changes in {name}"
            print(f"PASS: {name}; only intended fields changed")


if __name__ == "__main__":
    main()
