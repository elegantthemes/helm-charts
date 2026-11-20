# Offline stored-manifest lifecycle regression

Run `go test -v ./...` in this directory with Go 1.26. The module pins Helm
3.16.2 (matching the installed CLI) and its Kubernetes dependencies in go.sum.
Ordinary dependency downloads may use a writable GOPATH/GOMODCACHE/GOCACHE.
No live Kubernetes configuration is used.

The test renders the actual chart with only lookup substituted, separates hooks
using Helm's release sorter, stores each revision's regular manifest, and invokes
Helm's real kube.Client.Update for upgrade and rollback against an in-process
ConfigMap API. It checks empty install, initialization A, upgrade, advancement B,
rollback to both stored revisions, uninstall inventory, reinstall, missing object
and initialized-but-missing data. A negative control proves the same harness
reproduces stale restoration and marker removal from regular lookup snapshots.
Uninstall checks inventory and hook events; it does not execute a live uninstall.

Also run `python3 charts/gha-runner-autoscaler/tests/test-state.py` from the repo
root for pool names, Deployment wiring and named get/patch-only runtime RBAC.
