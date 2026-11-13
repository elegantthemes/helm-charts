"""Pod proof is independent of auth; neither feature grants default-SA access."""
from pathlib import Path
from itertools import product
import json, subprocess, yaml
root = Path(__file__).resolve().parents[1]
fixture = json.loads((root / 'tests/deephive-admission/values.json').read_text())
for enabled, auth in product((False, True), repeat=2):
    values = {'ENV_FILE':'SYNTHETIC=true', 'CODEX_AUTH_SECRET_NAME':'fixture-auth' if auth else '', 'WORKSPACE_ROOT':'/workspace'}
    if enabled:
        values['fullWorker'] = fixture['fullWorker'] | {'liteScratchRoot':'/lite-scratch', 'liteCapacity': {'enabled': True, 'pool':'test-lite', 'slots':2, 'memoryMiB':8192, 'taskMiB':4096}}
    docs = [d for d in yaml.safe_load_all(subprocess.check_output(['helm','template','canary',str(root/'charts/deephive'),'-n','dph-app','-f','-'],input=json.dumps(values).encode())) if d]
    roles = [d for d in docs if d['kind']=='Role' and d['metadata']['name']=='canary-codex-auth']
    accounts = [d for d in docs if d['kind']=='ServiceAccount' and d['metadata']['name']=='canary-consumer-sa']
    bindings = [d for d in docs if d['kind']=='RoleBinding' and d['metadata']['name']=='canary-codex-auth']
    deployment = next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='canary')
    spec = deployment['spec']['template']['spec']
    assert len(roles)==len(accounts)==len(bindings)==int(enabled or auth)
    if not (enabled or auth):
        assert not spec.get('serviceAccountName')
        continue
    assert spec['serviceAccountName']=='canary-consumer-sa'
    role = roles[0]
    assert role['metadata']['namespace']=='dph-app'
    pod_rules = [r for r in role['rules'] if 'pods' in r['resources']]
    assert pod_rules == ([{'apiGroups':[''], 'resources':['pods'], 'verbs':['get']}] if enabled else [])
    secret_rules = [r for r in role['rules'] if 'secrets' in r['resources']]
    assert secret_rules == ([{'apiGroups':[''], 'resources':['secrets'], 'resourceNames':['fixture-auth'], 'verbs':['get','patch']}] if auth else [])
    assert len(role['rules'])==int(enabled)+int(auth)
    assert bindings[0]['subjects']==[{'kind':'ServiceAccount','name':'canary-consumer-sa','namespace':'dph-app'}]
print('PASS all Lite/auth combinations: dedicated SA, Pod GET only, conditional named Secret scope, unchanged disabled default')
