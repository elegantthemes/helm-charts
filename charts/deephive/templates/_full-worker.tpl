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
