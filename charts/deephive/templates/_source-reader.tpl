{{- define "deephive.sourceReader" -}}
{{- dict "readerId" "shared-block-readiness-v1" "command" (list "/usr/bin/env" "node" (printf "%s/dist/scripts/environment/block-source-reader.js" .codeRoot) .context.Values.fullWorker.workspaceRoot) | toJson -}}
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
