#!/usr/bin/env bash

set -euo pipefail

chart_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rendered="$(mktemp)"
disabled="$(mktemp)"
trap 'rm -f "${rendered}" "${disabled}"' EXIT

helm template gha-runner-autoscaler "${chart_dir}" \
  --namespace gha-runners \
  --set monitoring.enabled=true \
  --set-string monitoring.clusterName=k8s-cluster-stage-v2 > "${rendered}"
helm template gha-runner-autoscaler "${chart_dir}" > "${disabled}"

grep -q '^kind: Service$' "${rendered}"
grep -q '^kind: ServiceMonitor$' "${rendered}"
grep -q '^kind: PrometheusRule$' "${rendered}"
grep -q 'port: metrics' "${rendered}"
grep -q 'expr: gha_node_autoscaler_manual_review_resources > 0' "${rendered}"
grep -q 'name: gha-runner-autoscaler-arc-controller' "${rendered}"
grep -q 'alert: GhaRunnerListenerMissing' "${rendered}"
grep -Fq 'expr: absent(gha_controller_running_listeners{namespace="gha-runners",name=~"et-runners-[^-]+-listener"})' "${rendered}"
grep -q 'oldest_age_metric: gha_node_autoscaler_manual_review_oldest_age_seconds' "${rendered}"
grep -q 'cluster: "k8s-cluster-stage-v2"' "${rendered}"

if grep -Eq '^kind: (ServiceMonitor|PrometheusRule)$' "${disabled}"; then
  echo "monitoring resources rendered while monitoring.enabled=false" >&2
  exit 1
fi

# A docs pool shares the ARC controller, but must alert on its own listener.
helm template gha-runner-autoscaler "${chart_dir}" \
  --namespace gha-runners-docs \
  --set monitoring.enabled=true \
  --set monitoring.arcControllerMonitoringEnabled=false \
  --set-string monitoring.arcControllerNamespace=gha-runners \
  --set-string monitoring.arcRunnerScaleSetName=et-runners-docs > "${rendered}"
grep -Fq 'expr: absent(gha_controller_running_listeners{namespace="gha-runners",name=~"et-runners-docs-[^-]+-listener"})' "${rendered}"
grep -Fq 'get autoscalingrunnerset et-runners-docs' "${rendered}"
if [[ $(grep -c '^kind: Service$' "${rendered}") != 1 ]] || [[ $(grep -c '^kind: ServiceMonitor$' "${rendered}") != 1 ]]; then
  echo "shared ARC controller scrape target duplicated in docs namespace" >&2
  exit 1
fi
