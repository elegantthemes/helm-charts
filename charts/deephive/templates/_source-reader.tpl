{{- define "deephive.sourceReader" -}}
{{- if .context.Values.sourceReaderService.enabled -}}
{{- dict "readerId" (printf "%s-source-reader-v1" .context.Release.Name) "command" (list "/usr/bin/env" "node" (printf "%s/dist/scripts/environment/remote-source-reader.js" .codeRoot) (printf "http://%s-source-reader:3003" .context.Release.Name) "/source-reader-token/token") | toJson -}}
{{- else -}}
{{- .context.Values.fullEnvironment.sourceReader | toJson -}}
{{- end -}}
{{- end -}}
