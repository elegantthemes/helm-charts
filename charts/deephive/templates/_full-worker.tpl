{{/* Preserve the complete release name while bounding Service and label identities. */}}
{{- define "deephive.fullWorkerName" -}}
{{- printf "%s-full-worker" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
