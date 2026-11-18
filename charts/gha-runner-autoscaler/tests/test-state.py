"""Offline Helm lookup fixtures; never contacts Kubernetes."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import yaml

chart = Path(__file__).resolve().parents[1]
lookup = 'lookup "v1" "ConfigMap" .Release.Namespace $name'

def render(release='shared', state=None, name=None, upgrade=False):
    with tempfile.TemporaryDirectory(prefix='autoscaler-state-') as tmp:
        target = Path(tmp) / 'chart'
        shutil.copytree(chart, target)
        if state is not None:
            template = target / 'templates/provisioning-state.yaml'
            text = template.read_text()
            assert text.count(lookup) == 1
            template.write_text(text.replace(lookup, '(' + json.dumps(json.dumps(state)) + ' | fromJson)'))
        command = ['helm', 'template', release, str(target), '-n', 'runners']
        if name is not None:
            command += ['--set-string', 'provisioningStateConfigMapName=' + name]
        if upgrade:
            command += ['--is-upgrade']
        return [d for d in yaml.safe_load_all(subprocess.check_output(command, text=True)) if d]

def state_map(docs):
    return next(d for d in docs if d['kind'] == 'ConfigMap')

for release, name in [('shared', 'shared-provisioning-state'), ('docs', 'docs-provisioning-state'), ('deephive', 'deep-state')]:
    docs = render(release, name=name)
    cm = state_map(docs)
    assert cm['metadata']['name'] == name and cm['data'] == {}
    assert cm['metadata']['annotations'] == {'helm.sh/resource-policy': 'keep', 'helm.sh/hook': 'pre-install', 'helm.sh/hook-weight': '-10', 'helm.sh/hook-delete-policy': 'hook-failed'}
    env = next(d for d in docs if d['kind'] == 'Deployment')['spec']['template']['spec']['containers'][0]['env']
    assert next(e['value'] for e in env if e['name'] == 'PROVISIONING_STATE_CONFIG_MAP') == name
    role = next(d for d in docs if d['kind'] == 'Role')
    assert [r for r in role['rules'] if 'configmaps' in r['resources']] == [{
        'apiGroups': [''], 'resources': ['configmaps'], 'resourceNames': [name], 'verbs': ['get', 'patch']}]
    assert not any('configmaps' in r['resources'] for d in docs if d['kind'] == 'ClusterRole' for r in d['rules'])
assert state_map(render())['metadata']['name'] == 'shared-provisioning-state'
print('PASS first-install empty state, isolated names, explicit environment and named get/patch RBAC')

existing = {'metadata': {'annotations': {'gha.etdevs.com/state-initialized': 'true', 'operator/note': 'retain'}},
            'data': {'state.json': '{"version":1,"pool":"deephive","failures":3,"open":true,"attempts":{}}', 'other': 'retain'}}
for upgrade in [False, True]:
    docs = render(state=existing, upgrade=upgrade)
    assert not any(d['kind'] == 'ConfigMap' for d in docs)
missing = copy.deepcopy(existing)
missing.pop('data')
assert not any(d['kind'] == 'ConfigMap' for d in render(state=missing, upgrade=True))
try:
    render(upgrade=True)
except subprocess.CalledProcessError:
    pass
else:
    raise AssertionError('upgrade with missing retained object must fail')
assert state_map(render())['metadata']['annotations']['helm.sh/hook'] == 'pre-install'
print('PASS existing and initialized-missing state omitted; missing-object upgrade fails closed')
print('PASS install-only retained bootstrap hook; stored-manifest lifecycle covered by Go suite')
