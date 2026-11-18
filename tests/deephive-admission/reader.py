"""Verify direct block readiness wiring and absence of CSI reader privileges."""
import json
from pathlib import Path
import subprocess
import yaml
root = Path(__file__).resolve().parent
values = json.loads((root / 'values.json').read_text())
raw = subprocess.check_output(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', '-'], input=json.dumps(values).encode())
docs = [d for d in yaml.safe_load_all(raw) if d]
assert not any(d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-source-reader') for d in docs)
assert not any(d['kind'] in ['ClusterRole', 'ClusterRoleBinding'] and d['metadata']['name'].startswith('dph-reader-') for d in docs)
config = json.loads(next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'review-full-worker')['data']['runner.json'])
assert set(config['sourceReader']) == {'transfer'}
assert config['cacheRoot'] == config['workspaceRoot']
assert config['sourceReader']['transfer'] == {'storage': 'full', 'workspaceRoot': config['workspaceRoot'], 'peer': 'http://review-consumer:3000'}
claims = [d for d in docs if d['kind'] == 'PersistentVolumeClaim']
assert len(claims) == 2
assert all(c['spec']['accessModes'] == ['ReadWriteOnce'] for c in claims)
assert all(c['metadata']['annotations']['helm.sh/resource-policy'] == 'keep' for c in claims)
assert len({c['metadata']['name'] for c in claims}) == 2
consumer = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'review')
reader = json.loads(next(e['value'] for e in consumer['spec']['template']['spec']['containers'][0]['env'] if e['name'] == 'FULL_WORKER_READER_CONFIG'))
assert reader['transfer']['storage'] == 'ordinary'
assert reader['transfer']['peer'] == 'http://review-full-worker:3001'
for d in docs:
 if d['kind'] == 'Deployment':
  assert not any(v['name'] in ['cache-probe', 'lite-cache-probe', 'source-reader-token'] for v in d['spec']['template']['spec'].get('volumes', []))
print('PASS block readiness has no JuiceFS reader or cache mounts')
