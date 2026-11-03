{{- define "deephive.liteCommands" -}}
{{- $f := .Values.fullWorker -}}
{{- if $f.liteCapacity.enabled -}}
{{- $entry := printf "%s/dist/scripts/environment/lite-capacity.js" (default "/srv/deephive" .Values.INSTALL_PATH) -}}
{{- dict "admit" (list "/usr/bin/env" "node" $entry "/lite-config/capacity.json" "admit") "release" (list "/usr/bin/env" "node" $entry "/lite-config/capacity.json" "release") | toJson -}}
{{- else -}}
{{- dict "admit" $f.liteAdmissionCommand "release" $f.liteHandoffCommand | toJson -}}
{{- end -}}
{{- end -}}
