package lifecycle

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"helm.sh/helm/v3/pkg/chart/loader"
	"helm.sh/helm/v3/pkg/chartutil"
	"helm.sh/helm/v3/pkg/engine"
	"helm.sh/helm/v3/pkg/kube"
	"helm.sh/helm/v3/pkg/release"
	"helm.sh/helm/v3/pkg/releaseutil"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/util/strategicpatch"
	"k8s.io/cli-runtime/pkg/resource"
	"k8s.io/client-go/kubernetes/typed/core/v1"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/yaml"
)

type revision struct {
	hooks    []*release.Hook
	manifest string
}

// Render once per revision, then use the stored manifest for rollback. Lookup
// is the only substituted cluster input, matching the Python fixture suite.
func render(t *testing.T, existing *corev1.ConfigMap, upgrade bool) (revision, error) {
	t.Helper()
	chart, err := loader.Load("../../charts/gha-runner-autoscaler")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(existing)
	if existing == nil {
		raw = []byte("{}")
	}
	quoted, _ := json.Marshal(string(raw))
	for _, f := range chart.Templates {
		if f.Name == "templates/provisioning-state.yaml" {
			f.Data = []byte(strings.ReplaceAll(string(f.Data), `lookup "v1" "ConfigMap" .Release.Namespace $name`, "("+string(quoted)+" | fromJson)"))
		}
	}
	values, err := chartutil.ToRenderValues(chart, map[string]interface{}{}, chartutil.ReleaseOptions{Name: "shared", Namespace: "runners", Revision: 1, IsInstall: !upgrade, IsUpgrade: upgrade}, nil)
	if err != nil {
		t.Fatal(err)
	}
	files, err := engine.Render(chart, values)
	if err != nil {
		return revision{}, err
	}
	hooks, manifests, err := releaseutil.SortManifests(files, chartutil.VersionSet{}, releaseutil.InstallOrder)
	if err != nil {
		t.Fatal(err)
	}
	var stored strings.Builder
	for _, m := range manifests {
		stored.WriteString("---\n" + m.Content + "\n")
	}
	return revision{hooks, stored.String()}, nil
}

// Drive Helm 3.16.2's actual kube.Client.Update against an in-process API.
// This exercises its GET/three-way strategic patch/delete paths, with no cluster.
type api struct {
	live      *corev1.ConfigMap
	mutations int
}

func (a *api) serve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	switch r.Method {
	case "GET":
	case "PATCH":
		a.mutations++
		before, _ := json.Marshal(a.live)
		patch, _ := io.ReadAll(r.Body)
		after, err := strategicpatch.StrategicMergePatch(before, patch, corev1.ConfigMap{})
		if err != nil {
			panic(err)
		}
		var next corev1.ConfigMap
		if err := json.Unmarshal(after, &next); err != nil {
			panic(err)
		}
		a.live = &next
	case "DELETE":
		a.mutations++
		a.live = nil
	default:
		panic(r.Method)
	}
	if a.live == nil {
		w.WriteHeader(404)
		io.WriteString(w, `{"kind":"Status","apiVersion":"v1","status":"Failure","reason":"NotFound","code":404}`)
		return
	}
	json.NewEncoder(w).Encode(a.live)
}
func resources(t *testing.T, manifest string, client *v1.CoreV1Client) kube.ResourceList {
	t.Helper()
	var result kube.ResourceList
	for _, doc := range strings.Split(manifest, "---") {
		if strings.TrimSpace(doc) == "" {
			continue
		}
		var obj corev1.ConfigMap
		if err := yaml.Unmarshal([]byte(doc), &obj); err != nil {
			t.Fatal(err)
		}
		if obj.Kind != "ConfigMap" {
			continue
		}
		result = append(result, &resource.Info{Client: client.RESTClient(), Mapping: &meta.RESTMapping{Resource: schema.GroupVersionResource{Version: "v1", Resource: "configmaps"}, GroupVersionKind: schema.GroupVersionKind{Version: "v1", Kind: "ConfigMap"}, Scope: meta.RESTScopeNamespace}, Namespace: obj.Namespace, Name: obj.Name, Object: &obj})
	}
	return result
}
func TestStoredManifestLifecycle(t *testing.T) {
	a := &api{}
	server := httptest.NewServer(http.HandlerFunc(a.serve))
	defer server.Close()
	client, err := v1.NewForConfig(&rest.Config{Host: server.URL})
	if err != nil {
		t.Fatal(err)
	}
	helm := &kube.Client{Log: t.Logf}
	update := func(old, new string) {
		t.Helper()
		if _, err := helm.Update(resources(t, old, client), resources(t, new, client), false); err != nil {
			t.Fatal(err)
		}
	}
	install, err := render(t, nil, false)
	if err != nil {
		t.Fatal(err)
	}
	if len(install.hooks) != 1 {
		t.Fatalf("expected bootstrap hook: %v", install.hooks)
	}
	hook := install.hooks[0]
	if len(hook.Events) != 1 || hook.Events[0] != release.HookPreInstall {
		t.Fatal("bootstrap must run only on install")
	}
	if len(hook.DeletePolicies) != 1 || hook.DeletePolicies[0] != release.HookFailed {
		t.Fatal("successful bootstrap must be retained")
	}
	// Execute only the initial bootstrap. Rollback does not run pre-install hooks.
	if err := yaml.Unmarshal([]byte(hook.Manifest), &a.live); err != nil {
		t.Fatal(err)
	}
	if len(a.live.Data) != 0 {
		t.Fatal("bootstrap prewrote state")
	}
	a.live.Data = map[string]string{"state.json": "A", "other": "retain"}
	a.live.Annotations["gha.etdevs.com/state-initialized"] = "true"
	initialized, err := render(t, a.live, true)
	if err != nil {
		t.Fatal(err)
	}
	update(install.manifest, initialized.manifest)
	a.live.Data["state.json"] = "B"
	expected, _ := json.Marshal(a.live)
	for _, target := range []revision{install, initialized} {
		update(initialized.manifest, target.manifest) // stored rollback; never rerender
		actual, _ := json.Marshal(a.live)
		if string(actual) != string(expected) || a.mutations != 0 {
			t.Fatal("rollback changed application state")
		}
	}
	// Uninstall has no state in the regular manifest, and no uninstall hook.
	if len(resources(t, initialized.manifest, client)) != 0 || len(initialized.hooks) != 0 {
		t.Fatal("state still release-managed")
	}
	reinstall, err := render(t, a.live, false)
	if err != nil || len(reinstall.hooks) != 0 {
		t.Fatal("reinstall would bootstrap existing state")
	}
	a.live.Data = nil
	missing, err := render(t, a.live, true)
	if err != nil || len(missing.hooks) != 0 || len(resources(t, missing.manifest, client)) != 0 {
		t.Fatal("initialized-missing state would be reseeded")
	}
	if _, err := render(t, nil, true); err == nil {
		t.Fatal("missing-object upgrade did not fail closed")
	}
	t.Log("PASS empty install -> initialize A -> upgrade -> advance B -> rollback install/initialized revisions; retained uninstall/reinstall; initialized-missing fail closed")

	// Sensitivity control: the predecessor's regular-manifest lookup strategy
	// really resets B to A, then removes the marker on rollback to empty install.
	a.live = &corev1.ConfigMap{TypeMeta: metav1.TypeMeta{APIVersion: "v1", Kind: "ConfigMap"}, ObjectMeta: metav1.ObjectMeta{Name: "shared-provisioning-state", Namespace: "runners", Annotations: map[string]string{"helm.sh/resource-policy": "keep"}}}
	empty, _ := yaml.Marshal(a.live)
	a.live.Data = map[string]string{"state.json": "A"}
	a.live.Annotations["gha.etdevs.com/state-initialized"] = "true"
	snapshotA, _ := yaml.Marshal(a.live)
	a.live.Data["state.json"] = "B"
	update(string(snapshotA), string(snapshotA))
	if a.live.Data["state.json"] != "A" {
		t.Fatal("control failed to detect stale restoration")
	}
	update(string(snapshotA), string(empty))
	if a.live.Annotations["gha.etdevs.com/state-initialized"] != "" || len(a.live.Data) != 0 {
		t.Fatal("control failed to detect rollback removal")
	}
	t.Log("PASS negative control reproduces predecessor stale restoration and marker/data removal via real Helm patches")
	// Migration removes the predecessor's regular resource from the new
	// manifest. Helm must consult live keep and leave the entire object intact.
	a.live.Data = map[string]string{"state.json": "B", "other": "retain"}
	a.live.Annotations["gha.etdevs.com/state-initialized"] = "true"
	beforeMigration, _ := json.Marshal(a.live)
	mutations := a.mutations
	update(string(snapshotA), initialized.manifest)
	afterMigration, _ := json.Marshal(a.live)
	if string(afterMigration) != string(beforeMigration) || a.mutations != mutations {
		t.Fatal("migration deleted or altered retained application-owned state")
	}
	t.Log("PASS predecessor regular-manifest -> safe revision migration retains object and complete state without delete/patch")
}
