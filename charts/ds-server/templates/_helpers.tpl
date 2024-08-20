{{- define "addCIDRToIPs" -}}
  {{- $ips := . | split "," -}}
  {{- $ipsWithCIDR := list -}}
  {{- range $ip := $ips -}}
    {{- $ipsWithCIDR = append $ipsWithCIDR (print $ip "/32") -}}
  {{- end -}}
  {{ $ipsWithCIDR | join "," | quote }}
{{- end -}}
