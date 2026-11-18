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
assert config['sourceReader']['readerId'] == 'shared-block-readiness-v1'
assert config['sourceReader']['command'][2] == '/opt/deephive/dist/scripts/environment/block-source-reader.js'
assert config['cacheRoot'] == config['workspaceRoot']
for d in docs:
 if d['kind'] == 'Deployment':
  assert not any(v['name'] in ['cache-probe', 'lite-cache-probe', 'source-reader-token'] for v in d['spec']['template']['spec'].get('volumes', []))
print('PASS block readiness has no JuiceFS reader or cache mounts')
