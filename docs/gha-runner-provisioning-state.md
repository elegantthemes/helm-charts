# Retained autoscaler state and dedicated DeepHive interface

Autoscaler chart **0.1.10** introduces `provisioningStateConfigMapName` (string).
Empty selects `<release>-provisioning-state`. Set it explicitly to the existing
state ConfigMap name when upgrading a pool that already has durable state.
The Deployment explicitly sets `PROVISIONING_STATE_CONFIG_MAP` to this name;
this overrides any same-named `envFrom` setting. Each pool must use its own
stable state name, configMapName, secretName, release and clusterRoleName.
Existing dryRun, scaleDownEnabled, monitoring and shared/docs/CI defaults remain.

On first installation, an install-only `pre-install` ConfigMap hook creates an
empty object before the Deployment starts. It writes neither a state schema nor
an initialized marker. The autoscaler initializes that empty map for its pool
through resourceVersion CAS. Its namespaced Role remains get/patch on the exact
state name; runtime create/list/update/delete privileges are not added.

The bootstrap has `helm.sh/resource-policy: keep` and an explicit `hook-failed`
delete policy, so successful creation is retained rather than deleted or replaced
by the default before-hook-creation policy. Server-side lookup suppresses the
hook entirely if the object already exists, including reinstall/adoption. Use
Helm with lookup access; client-only template output is an empty-install fixture,
not an applyable replacement or a bootstrap command for an existing pool. Do not
run competing installers for the same stable object.

State is application-owned: neither `data` nor the initialized marker is ever
copied into a regular Helm release manifest. Upgrade emits no state resource;
rollback uses the stored regular manifest and runs no pre-install hook. It
therefore cannot replay stale state or remove the marker, even after state
advances between upgrade and rollback. Uninstall has no regular state resource
or uninstall hook to delete. Reinstall with lookup retains the existing object.
An upgrade whose object is missing fails rendering; restore the retained object
and exact data before proceeding. An initialized object missing `state.json`
is left untouched and remains fail-closed in the autoscaler. Never erase the
marker or reseed state to recover. Schema/pool validation and CAS remain in the
application. Keep the state name stable and never transfer it between pools.

The offline Go lifecycle suite uses pinned Helm 3.16.2 release sorting and its
actual Kubernetes update/three-way patch path against an in-process API. It
stores install and initialized revision manifests, advances A to B, and rolls
back those stored manifests without rerendering. A negative control reproduces
the predecessor's stale restoration and marker removal. These are offline
semantics checks, not live cluster/uninstall/admission acceptance.

Terraform integration contract (no Terraform files or live migration here):

- Select autoscaler chart **0.1.10**, with stable release/namespace and explicit
  `provisioningStateConfigMapName`. Empty still means `<release>-provisioning-state`.
  Preserve distinct pool state names, `configMapName`, `secretName`, and
  `clusterRoleName`; `configMapName` selects ordinary configuration only.
- For a new pool, order the autoscaler chart/bootstrap before any state-dependent
  application. Preserve existing dryRun/scaleDownEnabled/monitoring defaults.
- For a Terraform-owned existing ConfigMap, first review a no-delete ownership
  migration: detach it from Terraform management using a removed block with
  `destroy = false` (or separately authorized state removal), without a destroy,
  replacement or data update. Preserve the live object, UID, complete data and
  annotations, including the initialized marker. The new chart sees that object
  and leaves it outside Helm ownership; Helm adoption labels are unnecessary.
  Review the exact Terraform plan before any execution. Do not delete/recreate
  the object to resolve ownership errors.
- For a predecessor Helm-managed object, its existing `keep` annotation must be
  present before migration; Helm's update removal path retains it while the new
  revision stops listing it. Historical **0.1.9** and older manifests remain
  unsafe rollback targets because they contain mutable snapshots. Establish **0.1.10** as the rollback
  floor; restoring compatible application references must use a safe chart
  revision, never a historical manifest that embeds state. Quiescing alone does
  not make those older rollback targets safe.
- Keep DeepHive chart **1.4.1**, `fullWorker.runnerEnabled=false` while installing
  admission policies/bindings, then observe and accept protection before enabling
  protocol 4. Supply actual compatible digest-pinned artifacts and reviewed
  bootstrap identities. No image build, migration, cluster mutation or deployment
  is authorized by this interface document.

DeepHive chart **1.4.1** adds dedicated-taint admission enforcement for protocol
4. Keep `fullWorker.runnerEnabled=false` for the first installation of the
protocol 4 admission policies/bindings. Only enable the runner after Kubernetes has observed and type-checked both
the session Pod and Node admission policies and both bindings enforce Deny.
Set `fullWorker.sessionProtocol=4` with compatible, actually built digest-pinned
runner/session/database references and reviewed bootstrap identities; fixture
digests are synthetic and cannot be deployed. Protocol 4 uses local volumes,
mount-free activation init0, ordinary local initialization before database
startup, dedicated `deephive-full=true:NoSchedule` tolerance, and hostname
anti-affinity against session Pods across all namespaces. Protocol 2/3 retains
its compatible legacy policy. Existing Lite/legacy storage and pool defaults
are retained. Deployment, image builds and runtime acceptance are not performed.

The protocol 4 controller runs on ordinary nodes so it can submit session Pods
while the dedicated pool is empty. Only the session Pods and image pre-pull
DaemonSet target dedicated nodes. The controller does not mount the legacy
disk probes. Node admission limits its write access to the activation claim on
identified DeepHive burst Nodes.
