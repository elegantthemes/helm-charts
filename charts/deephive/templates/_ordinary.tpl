{{- define "deephive.ordinaryCommands" -}}
{{- $f := .Values.fullEnvironment -}}
{{- if $f.ordinaryCapacity.enabled -}}
{{- $entry := printf "%s/dist/scripts/environment/ordinary-capacity.js" (default "/srv/deephive" .Values.INSTALL_PATH) -}}
{{- dict "admit" (list "/usr/bin/env" "node" $entry "/ordinary-config/capacity.json" "admit") "release" (list "/usr/bin/env" "node" $entry "/ordinary-config/capacity.json" "release") | toJson -}}
{{- else -}}
{{- dict "admit" $f.ordinaryAdmissionCommand "release" $f.ordinaryHandoffCommand | toJson -}}
{{- end -}}
{{- end -}}
