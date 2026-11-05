# Runner autoscaler chart

Terraform's gha-runners app deploys one release per shared/E2E, docs and CI
namespace. Chart defaults are safe starter values, not current staging pins.
Terraform owns deployed imageVersion, pool configuration, credentials and capacity.

Chart 0.1.8 adds `<release>-provisioning-state`, a retained namespaced ConfigMap.
The Deployment supplies its name through `PROVISIONING_STATE_CONFIG_MAP`.
The namespaced Role permits only get/patch on this exact ConfigMap; no
create/delete/list access is needed. The application owns `state.json` and its
initialization annotation, using resourceVersion-conditional change-only patches.
Templates intentionally omit state data so Helm upgrades do not replay budgets.
The keep annotation retains state on uninstall; operators must preserve it during
reinstalls and troubleshooting. Never delete it to reset a breaker or boot budget.

Deploy this chart before application releases that require persisted state.
Application 0.1.16 was verified with chart 0.1.8 on 2026-11-05. Missing or invalid
initialized state fails closed. An empty never-initialized ConfigMap is valid.

Monitoring exposes metrics and alerts when enabled by deployment values.
The manual-review alert fires after five minutes above zero by default, including
retained diagnostics; its firing delay is not a resolution delay. Readiness alone
does not establish capacity health.

See the [application recovery contract](https://github.com/elegantthemes/gha-runner-autoscaler#provisioning-circuit-breaker)
and [deployment operations runbook](https://github.com/elegantthemes/terraform/blob/master/apps/gha-runners/docs/autoscaler-operations.md).
