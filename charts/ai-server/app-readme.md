AI Server

## Metrics

AI Server exposes Prometheus metrics on the cluster-internal `metrics` service
port (`9090`) at `/metrics`. Set `METRICS_SERVICE_MONITOR_ENABLED` to `true` to
render the Prometheus Operator `ServiceMonitor`. The scrape interval defaults to
`30s` and can be changed with `METRICS_SCRAPE_INTERVAL`.

The public ingress continues to target only the `nodejs` application port
(`9999`); it does not expose the metrics listener.
