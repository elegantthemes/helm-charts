#!/usr/bin/env bash

set -euo pipefail

chart_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered="$(mktemp)"
disabled="$(mktemp)"
trap 'rm -f "${rendered}" "${disabled}"' EXIT

helm template gha-runner-autoscaler "${chart_dir}" \
  --namespace gha-runners \
  --set monitoring.enabled=true \
  --set monitoring.clusterName=k8s-cluster-stage-v2 > "${rendered}"
helm template gha-runner-autoscaler "${chart_dir}" > "${disabled}"

grep -q '^kind: Service$' "${rendered}"
grep -q '^kind: ServiceMonitor$' "${rendered}"
grep -q '^kind: PrometheusRule$' "${rendered}"
grep -q 'port: metrics' "${rendered}"
grep -q 'expr: gha_node_autoscaler_manual_review_resources > 0' "${rendered}"
grep -q 'oldest_age_metric: gha_node_autoscaler_manual_review_oldest_age_seconds' "${rendered}"
grep -q 'cluster: "k8s-cluster-stage-v2"' "${rendered}"

if grep -q '^kind: ServiceMonitor$\|^kind: PrometheusRule$' "${disabled}"; then
  echo "monitoring resources rendered while monitoring.enabled=false" >&2
  exit 1
fi
