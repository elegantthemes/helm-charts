#!/usr/bin/env bash
set -euo pipefail
chart_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
task_tmp="$(mktemp -d)"
trap 'rm -rf "$task_tmp"' EXIT
for mode in normal maintenance disabled; do
  flags=()
  [[ "$mode" != maintenance ]] || flags+=(--set MAINTENANCE_MODE=true)
  [[ "$mode" != disabled ]] || flags+=(--set WEB_CAPTURES_ROUTE_PRIVACY_ENABLED=false)
  helm template ai-server "$chart_dir" --namespace dai-app --set-string ENV_FILE=SETTING=unit --set-string VIRTUAL_HOST=unit.test --set-string INGRESS_CLASS_NAME=traefik "${flags[@]}" > "$task_tmp/$mode.yaml"
done
python3 - "$task_tmp" <<'PY'
import pathlib, sys, yaml
root = pathlib.Path(sys.argv[1])
for mode in ['normal', 'maintenance', 'disabled']:
    ingresses = [d for d in yaml.safe_load_all((root / (mode + '.yaml')).read_text()) if d and d.get('kind') == 'Ingress']
    private = [d for d in ingresses if d['metadata']['name'] == 'ai-server-private-agent']
    assert len(private) == (0 if mode == 'disabled' else 1)
    main = next(d for d in ingresses if d['metadata']['name'] == 'ai-server')
    assert main['metadata']['annotations']['cert-manager.io/cluster-issuer'] == 'letsencrypt'
    if private:
        ingress = private[0]
        assert ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.observability.accesslogs'] == 'false'
        assert ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.observability.tracing'] == 'false'
        assert 'cert-manager.io/cluster-issuer' not in ingress['metadata']['annotations']
        assert ingress['spec']['ingressClassName'] == 'traefik'
        assert ingress['spec']['tls'] == main['spec']['tls']
        paths = ingress['spec']['rules'][0]['http']['paths']
        assert {p['path'] for p in paths} == {'/api/v2/agent/web-captures', '/api/v2/agent/generate-layout'}
        for path in paths:
            assert path['pathType'] == 'Prefix'
            assert path['backend']['service'] == {'name': 'ai-server-maintenance' if mode == 'maintenance' else 'ai-server', 'port': {'number': 80 if mode == 'maintenance' else 9999}}
print('Capture ingress privacy, certificate ownership, maintenance routing and disabled mode pass.')
PY
