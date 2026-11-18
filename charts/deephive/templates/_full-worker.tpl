{{/* Preserve the complete release name while bounding Service and label identities. */}}
{{- define "deephive.fullWorkerName" -}}
{{- printf "%s-full-worker" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Normalize values retained by --reuse-values before any template reads them.
Explicit new keys win, including false, empty strings and empty command lists. */}}
{{- define "deephive.normalizeWorkerValues" -}}
{{- $legacy := deepCopy (.Values.fullEnvironment | default dict) -}}
{{- range $suffix := list "Capacity" "AdmissionCommand" "InstallCommand" "HandoffCommand" "ScratchRoot" "CacheProbePath" -}}
{{- $old := printf "ordinary%s" $suffix -}}
{{- if hasKey $legacy $old -}}
{{- $_ := set $legacy (printf "lite%s" $suffix) (index $legacy $old) -}}
{{- $_ := unset $legacy $old -}}
{{- end -}}
{{- end -}}
{{- $_ := set .Values "fullWorker" (mergeOverwrite $legacy (.Values.fullWorker | default dict)) -}}
{{- end -}}

{{- define "deephive.nodeAdmissionName" -}}
{{- printf "dph-node-activation-%s" (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 24) -}}
{{- end -}}

{{- define "deephive.nodeAdmissionReady" -}}
{{- $name := include "deephive.nodeAdmissionName" . -}}
{{- $policy := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicy" "" $name -}}
{{- $binding := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicyBinding" "" $name -}}
{{- $status := $policy.status | default dict -}}
{{- $identity := printf "request.userInfo.username == 'system:serviceaccount:%s:%s'" .Release.Namespace (include "deephive.fullWorkerName" .) -}}
{{- $expected := list (dict "name" "runner-identity" "expression" $identity) -}}
{{- $rules := list (dict "apiGroups" (list "") "apiVersions" (list "v1") "operations" (list "UPDATE") "resources" (list "nodes") "scope" "Cluster") -}}
{{- if and $policy $binding (eq $policy.spec.failurePolicy "Fail")
    (deepEqual $policy.spec.matchConditions $expected)
    (deepEqual $policy.spec.matchConstraints.resourceRules $rules)
    (not $policy.spec.matchConstraints.excludeResourceRules)
    (not $policy.spec.matchConstraints.objectSelector)
    (not $policy.spec.matchConstraints.namespaceSelector)
    (eq $binding.spec.policyName $name) (has "Deny" $binding.spec.validationActions)
    (not $binding.spec.matchResources)
    (eq (int64 $status.observedGeneration) (int64 $policy.metadata.generation))
    (hasKey $status "typeChecking") (not $status.typeChecking.expressionWarnings) -}}
true
{{- else -}}
false
{{- end -}}
{{- end -}}
