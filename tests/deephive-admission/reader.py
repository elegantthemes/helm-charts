"""Render broker wiring and evaluate reader admission without cluster access."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import yaml
root = Path(__file__).resolve().parent
values = json.loads((root / 'values.json').read_text())
values['sourceReaderService'] = {'enabled': True, 'running': False, 'tokenSecret': 'reader-token', 'tokenRevision': '1', 'nodeName': 'reader-node'}
raw = subprocess.check_output(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', '-'], input=json.dumps(values).encode())
docs = [d for d in yaml.safe_load_all(raw) if d]
policy = next(d for d in docs if d['kind'] == 'ValidatingAdmissionPolicy' and d['metadata']['name'].startswith('dph-reader-'))
broker = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'review-source-reader')
assert broker['spec']['replicas'] == 0
assert not any(d['kind'] in ['RoleBinding', 'ClusterRoleBinding'] and d.get('roleRef', {}).get('name') in ['review-source-reader', policy['metadata']['name']] for d in docs)
for name in ['review', 'review-runner']:
 pod = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == name)['spec']['template']['spec']
 if name == 'review':
  command = json.loads(next(e for e in pod['containers'][0]['env'] if e['name'] == 'FULL_ENVIRONMENT_READER_CONFIG')['value'])['command']
  assert command[2] == '/srv/deephive/dist/scripts/environment/remote-source-reader.js'
 assert next(v for v in pod['volumes'] if v['name'] == 'source-reader-token')['secret']['secretName'] == 'reader-token'
config = json.loads(next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'review-runner')['data']['runner.json'])
assert config['sourceReader']['command'][-2:] == ['http://review-source-reader:3003', '/source-reader-token/token']
meta = {'name': 'dh-source-test', 'labels': {'app.kubernetes.io/instance': 'review', 'deephive/source-reader': 'test', 'deephive/role': 'source-reader'}}
pod = {'metadata': meta, 'spec': {'serviceAccountName': 'default', 'automountServiceAccountToken': False, 'containers': [{'name': 'reader', 'image': values['fullEnvironment']['runnerImage'], 'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}}, 'volumeMounts': [{'name': 'source', 'mountPath': '/workspace-root/task', 'readOnly': True}]}], 'volumes': [{'name': 'source', 'persistentVolumeClaim': {'claimName': 'dh-source-test', 'readOnly': True}}]}}
pvc = {'metadata': meta, 'spec': {'volumeName': 'dh-source-test', 'storageClassName': '', 'accessModes': ['ReadOnlyMany']}}
pv = {'metadata': meta, 'spec': {'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '', 'accessModes': ['ReadOnlyMany'], 'claimRef': {'name': 'dh-source-test', 'namespace': 'dph-app'}, 'csi': {'driver': 'csi.juicefs.com', 'readOnly': True, 'volumeHandle': 'dh-source-test', 'nodePublishSecretRef': {'name': 'juicefs-deephive-workspace', 'namespace': 'kube-system'}}, 'mountOptions': ['ro', 'cache-size=0', 'open-cache=0', 'attr-cache=0', 'entry-cache=0', 'buffer-size=64']}}
cases = []
def case(name, obj, resource, expected=True, mutate=None):
 obj = copy.deepcopy(obj)
 if mutate: mutate(obj)
 cases.append({'Name': name, 'Expect': expected, 'Activation': {'variables': {'obj': obj}, 'object': obj, 'oldObject': obj, 'request': {'namespace': 'dph-app' if resource != 'persistentvolumes' else '', 'resource': {'resource': resource}, 'operation': 'CREATE'}}})
case('reader Pod', pod, 'pods')
case('reader PVC', pvc, 'persistentvolumeclaims')
case('reader PV', pv, 'persistentvolumes')
case('reject writer claim', pod, 'pods', False, lambda p: p['spec']['volumes'][0]['persistentVolumeClaim'].update(claimName='workspace'))
case('reject reader credentials', pod, 'pods', False, lambda p: p['spec']['containers'][0].update(envFrom=[{'secretRef': {'name': 'runner'}}]))
case('reject host access', pod, 'pods', False, lambda p: p['spec'].update(hostPID=True))
case('reject workload token', pod, 'pods', False, lambda p: p['spec'].update(automountServiceAccountToken=True))
case('reject foreign role', pod, 'pods', False, lambda p: p['metadata']['labels'].update({'deephive/role': 'consumer'}))
case('old reader image cleanup', pod, 'pods', True, lambda p: p['spec']['containers'][0].update(image='previous-approved-image'))
cases[-1]['Activation']['request']['operation'] = 'DELETE'
case('reject destructive reclaim', pv, 'persistentvolumes', False, lambda p: p['spec'].update(persistentVolumeReclaimPolicy='Delete'))
case('reject writable volume', pv, 'persistentvolumes', False, lambda p: p['spec']['csi'].update(readOnly=False))
case('reject foreign secret', pv, 'persistentvolumes', False, lambda p: p['spec']['csi']['nodePublishSecretRef'].update(name='other'))
with tempfile.TemporaryDirectory(prefix='reader-admission-') as temp:
 fixture = Path(temp) / 'fixtures.json'
 fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in policy['spec']['validations']], 'Cases': cases}))
 subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)
print('PASS reader protection-first wiring and command configuration')

values['sourceReaderService']['running'] = True
attempt = subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', '-'], input=json.dumps(values).encode(), capture_output=True)
assert attempt.returncode != 0 and b'running=false' in attempt.stderr
print('PASS reader requires installed admission before startup')
