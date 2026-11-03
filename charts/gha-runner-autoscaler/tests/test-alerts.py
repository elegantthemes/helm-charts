#!/usr/bin/env python3
"""Exercise the rendered recovery alerts with Prometheus, without cluster access."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]
NAMESPACE = "gha-runners"
PREFIX = "gha_node_autoscaler_"


def main():
    rendered = subprocess.check_output([
        "helm", "template", "gha-runner-autoscaler", str(CHART),
        "--namespace", NAMESPACE, "--set", "monitoring.enabled=true",
        "--set-string", "monitoring.clusterName=k8s-cluster-stage",
    ], text=True)
    groups = [group for doc in yaml.safe_load_all(rendered)
              if doc and doc["kind"] == "PrometheusRule"
              for group in doc["spec"]["groups"]]
    rules = {rule["alert"]: rule for group in groups for rule in group["rules"]
             if rule["alert"].startswith("GhaRunnerAutoscaler")
             and rule["alert"] != "GhaRunnerAutoscalerManualReviewRequired"}
    names = ["GhaRunnerAutoscaler" + suffix for suffix in (
        "CapacityDeficit", "CreationRetries", "InventoryUntrusted", "JobsUnscheduled")]
    assert set(rules) == set(names), rules.keys()

    tests = []

    def scenario(name, values, checks, other_pool=False):
        signals = dict(capacity_deficit="0x15", creation_retry_attempts="0x15",
                       inventory_trusted="1x15", unscheduled_jobs="0x15")
        signals.update(values)
        inputs = [{"series": f'{PREFIX}{key}{{namespace="{NAMESPACE}"}}', "values": value}
                  for key, value in signals.items()]
        if other_pool:
            inputs.append({"series": f'{PREFIX}capacity_deficit{{namespace="gha-runners-docs"}}',
                           "values": "1x15"})
        alert_tests = []
        for at, firing in checks:
            for alert in names:
                expected = []
                if alert.removeprefix("GhaRunnerAutoscaler") in firing:
                    expected = [{"exp_labels": {**rules[alert]["labels"], "namespace": NAMESPACE},
                                 "exp_annotations": rules[alert]["annotations"]}]
                alert_tests.append({"eval_time": at, "alertname": alert, "exp_alerts": expected})
        tests.append({"name": name, "interval": "1m", "input_series": inputs,
                      "alert_rule_test": alert_tests})

    scenario("missing capacity fires before workflow timeout", {"capacity_deficit": "1x15"},
             [("2m", []), ("3m", ["CapacityDeficit"])])
    scenario("healthy inventory cannot hide repeated creation failure",
             {"capacity_deficit": "1x15", "creation_retry_attempts": "5x15"},
             [("1m", ["CreationRetries"]), ("3m", ["CapacityDeficit", "CreationRetries"])])
    scenario("provisioning and idle pools stay quiet", {}, [("15m", [])])
    scenario("old retry history without missing capacity stays quiet",
             {"creation_retry_attempts": "5x15"}, [("15m", [])])
    scenario("slow provisioning is caught by waiting jobs",
             {"unscheduled_jobs": "1x15"}, [("4m", []), ("5m", ["JobsUnscheduled"])])
    scenario("untrusted inventory is actionable", {"inventory_trusted": "0x15"},
             [("1m", []), ("2m", ["InventoryUntrusted"])])
    scenario("another pool cannot fire this release's alerts", {}, [("15m", [])], other_pool=True)
    scenario("recovery resolves capacity alert", {"capacity_deficit": "1x3 0x12"},
             [("3m", ["CapacityDeficit"]), ("4m", [])])

    with tempfile.TemporaryDirectory(prefix="gha-alerts-") as directory:
        scratch = Path(directory)
        (scratch / "rules.yaml").write_text(yaml.safe_dump({"groups": [
            {"name": "recovery", "rules": list(rules.values())}]}))
        (scratch / "tests.yaml").write_text(yaml.safe_dump({
            "rule_files": ["rules.yaml"], "evaluation_interval": "1m", "tests": tests}))
        if shutil.which("promtool"):
            command = ["promtool", "test", "rules", "tests.yaml"]
        else:
            command = ["docker", "run", "--rm", "--network=none", "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "/bin/promtool",
                       "-v", f"{scratch}:/tests:ro", "-w", "/tests",
                       "prom/prometheus:v3.8.1", "test", "rules", "tests.yaml"]
        subprocess.run(command, cwd=scratch, check=True)


if __name__ == "__main__":
    main()
