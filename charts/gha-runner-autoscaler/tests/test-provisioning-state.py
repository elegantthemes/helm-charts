#!/usr/bin/env python3
"""Render each pool and check the durable state ownership and RBAC contract."""
from pathlib import Path
import subprocess
import yaml

chart = Path(__file__).resolve().parents[1]
for pool in ("shared", "docs", "ci"):
    release = f"autoscaler-{pool}"
    namespace = f"gha-runners-{pool}"
    documents = list(yaml.safe_load_all(subprocess.check_output(
        ["helm", "template", release, str(chart), "--namespace", namespace], text=True
    )))
    state_name = f"{release}-provisioning-state"
    state = next(doc for doc in documents if doc["kind"] == "ConfigMap")
    assert state["metadata"]["name"] == state_name
    assert state["metadata"]["namespace"] == namespace
    assert state["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
    assert "data" not in state, "Helm must never own or reset state.json"
    role = next(doc for doc in documents if doc["kind"] == "Role")
    rules = [rule for rule in role["rules"] if "configmaps" in rule["resources"]]
    assert rules == [{"apiGroups": [""], "resources": ["configmaps"],
                      "resourceNames": [state_name], "verbs": ["get", "patch"]}]
    cluster_role = next(doc for doc in documents if doc["kind"] == "ClusterRole")
    assert all("configmaps" not in rule["resources"] for rule in cluster_role["rules"])
    deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    assert next(item["value"] for item in env if item["name"] == "PROVISIONING_STATE_CONFIG_MAP") == state_name
print("Provisioning state render and RBAC checks passed for shared, docs, and ci.")
