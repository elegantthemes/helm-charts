AI Server

The chart defaults `WEB_CAPTURES_ROUTE_PRIVACY_ENABLED` to true. A dedicated
Ingress for capture create/read and generate-layout suppresses raw access paths
and tracing on Traefik; AI Server records route templates with independent
request IDs. Requires Traefik 3.3 or later. Keep privacy enabled when turning the
application feature gate off, since already issued IDs remain readable.
Validate both route selection and absence of a test capture ID in ingress logs
before enabling captures. The shared TLS certificate remains owned by the main
Ingress. Maintenance mode routes both Ingresses to the maintenance service.

## Metrics

AI Server exposes Prometheus metrics on the cluster-internal `metrics` service
port (`9090`) at `/metrics`. Set `METRICS_SERVICE_MONITOR_ENABLED` to `true` to
render the Prometheus Operator `ServiceMonitor`. The scrape interval defaults to
`30s` and can be changed with `METRICS_SCRAPE_INTERVAL`.

The public ingress continues to target only the `nodejs` application port
(`9999`); it does not expose the metrics listener.
