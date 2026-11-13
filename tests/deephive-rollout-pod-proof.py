"""Lite recovery gets only namespaced Pod GET, with existing Secret access intact."""
from pathlib import Path
import json, subprocess, yaml
root = Path(__file__).resolve().parents[1]
fixture = json.loads((root / 'tests/deephive-admission/values.json').read_text())
for enabled in (False, True):
    values = {'ENV_FILE':'SYNTHETIC=true', 'CODEX_AUTH_SECRET_NAME':'fixture-auth', 'WORKSPACE_ROOT':'/workspace'}
    if enabled:
        values['fullWorker'] = fixture['fullWorker'] | {'liteScratchRoot':'/lite-scratch', 'liteCapacity': {'enabled': True, 'pool':'test-lite', 'slots':2, 'memoryMiB':8192, 'taskMiB':4096}}
    docs = [d for d in yaml.safe_load_all(subprocess.check_output(['helm','template','canary',str(root/'charts/deephive'),'-n','dph-app','-f','-'],input=json.dumps(values).encode())) if d]
    role = next(d for d in docs if d['kind']=='Role' and d['metadata']['name']=='canary-codex-auth')
    assert role['metadata']['namespace']=='dph-app'
    pod_rules = [r for r in role['rules'] if 'pods' in r['resources']]
    assert pod_rules == ([{'apiGroups':[''], 'resources':['pods'], 'verbs':['get']}] if enabled else [])
    secret = next(r for r in role['rules'] if 'secrets' in r['resources'])
    assert secret['resourceNames']==['fixture-auth'] and secret['verbs']==['get','patch']
    binding = next(d for d in docs if d['kind']=='RoleBinding' and d['metadata']['name']=='canary-codex-auth')
    assert binding['subjects']==[{'kind':'ServiceAccount','name':'canary-consumer-sa','namespace':'dph-app'}]
print('PASS Lite-enabled pod GET only; disabled default and Secret scope preserved')
