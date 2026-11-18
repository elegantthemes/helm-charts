{{- define "deephive.sourceReader" -}}
{{- $storage := default "ordinary" .storage -}}
{{- $root := .context.Values.WORKSPACE_ROOT -}}
{{- $peer := printf "http://%s:3001" (include "deephive.fullWorkerName" .context) -}}
{{- if eq $storage "full" -}}
{{- $root = .context.Values.fullWorker.workspaceRoot -}}
{{- $peer = printf "http://%s-consumer:%v" .context.Release.Name .context.Values.PORT -}}
{{- end -}}
{{- dict "transfer" (dict "storage" $storage "workspaceRoot" $root "peer" $peer) | toJson -}}
{{- end -}}

{{- define "deephive.readerWorkloadNamespace" -}}
{{- printf "dph-reader-%s" (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 24) -}}
{{- end -}}

{{- define "deephive.readerServiceName" -}}
{{- $name := printf "%s-source-reader" .Release.Name -}}
{{- if gt (len $name) 53 -}}
{{- printf "%s-%s" ($name | trunc 40 | trimSuffix "-") (printf "%s/%s" .Release.Namespace .Release.Name | sha256sum | trunc 12) -}}
{{- else -}}{{- $name -}}{{- end -}}
{{- end -}}
{{- define "deephive.drainCheckName" -}}
{{- $name := printf "%s-session-drain-check" .Release.Name -}}
{{- if gt (len $name) 53 -}}
{{- printf "%s-%s" ($name | trunc 40 | trimSuffix "-") (printf "%s/%s/drain" .Release.Namespace .Release.Name | sha256sum | trunc 12) -}}
{{- else -}}{{- $name -}}{{- end -}}
{{- end -}}
