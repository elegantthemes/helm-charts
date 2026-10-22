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
for name in ['review', 'review-full-worker']:
 pod = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == name)['spec']['template']['spec']
 if name == 'review':
  command = json.loads(next(e for e in pod['containers'][0]['env'] if e['name'] == 'FULL_WORKER_READER_CONFIG')['value'])['command']
  assert command[2] == '/srv/deephive/dist/scripts/environment/remote-source-reader.js'
 assert next(v for v in pod['volumes'] if v['name'] == 'source-reader-token')['secret']['secretName'] == 'reader-token'
config = json.loads(next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'review-full-worker')['data']['runner.json'])
assert config['sourceReader']['command'][-2:] == ['http://review-source-reader:3003', '/source-reader-token/token']
reader_namespace = json.loads(next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'review-source-reader')['data']['reader.json'])['namespace']
assert reader_namespace != 'dph-app'
reader_role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'review-source-reader')
assert reader_role['metadata']['namespace'] == reader_namespace
assert all(d['metadata'].get('namespace') == reader_namespace for d in docs if d['kind'] == 'Role' and any('pods/log' in r['resources'] for r in d['rules']))
meta = {'name': 'dh-source-test', 'labels': {'app.kubernetes.io/instance': 'review', 'deephive/source-reader': 'test', 'deephive/role': 'source-reader'}}
pod = {'metadata': meta, 'spec': {'nodeName': 'reader-node', 'serviceAccountName': 'default', 'automountServiceAccountToken': False, 'containers': [{'name': 'reader', 'image': values['fullWorker']['runnerImage'], 'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}}, 'volumeMounts': [{'name': 'source', 'mountPath': '/workspace-root/task', 'readOnly': True}]}], 'volumes': [{'name': 'source', 'persistentVolumeClaim': {'claimName': 'dh-source-test', 'readOnly': True}}]}}
pvc = {'metadata': meta, 'spec': {'volumeName': 'dh-source-test', 'storageClassName': '', 'accessModes': ['ReadOnlyMany']}}
pv = {'metadata': meta, 'spec': {'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': '', 'accessModes': ['ReadOnlyMany'], 'claimRef': {'name': 'dh-source-test', 'namespace': reader_namespace}, 'csi': {'driver': 'csi.juicefs.com', 'readOnly': True, 'volumeHandle': 'dh-source-test', 'nodePublishSecretRef': {'name': 'juicefs-deephive-workspace', 'namespace': 'kube-system'}}, 'mountOptions': ['ro', 'cache-size=0', 'open-cache=0', 'attr-cache=0', 'entry-cache=0', 'buffer-size=64']}}
pod['spec']['containers'][0]['resources'] = {'requests': {'cpu': '100m', 'memory': '128Mi', 'ephemeral-storage': '16Mi'}, 'limits': {'cpu': '1', 'memory': '512Mi', 'ephemeral-storage': '256Mi'}}
cases = []
def case(name, obj, resource, expected=True, mutate=None):
 obj = copy.deepcopy(obj)
 if mutate: mutate(obj)
 cases.append({'Name': name, 'Expect': expected, 'Activation': {'variables': {'obj': obj}, 'object': obj, 'oldObject': obj, 'request': {'namespace': reader_namespace if resource != 'persistentvolumes' else '', 'resource': {'resource': resource}, 'operation': 'CREATE'}}})
case('reader Pod', pod, 'pods')
case('reject writer node', pod, 'pods', False, lambda p: p['spec'].update(nodeName='writer-node'))
case('reject unspecified node', pod, 'pods', False, lambda p: p['spec'].pop('nodeName'))
case('old reader node cleanup', pod, 'pods', True, lambda p: p['spec'].update(nodeName='old-reader'))
cases[-1]['Activation']['request']['operation'] = 'DELETE'
case('reject consumer namespace', pod, 'pods', False)
cases[-1]['Activation']['request']['namespace'] = 'dph-app'
case('reject missing limits', pod, 'pods', False, lambda p: p['spec']['containers'][0].pop('resources'))
case('reject oversized reader memory', pod, 'pods', False, lambda p: p['spec']['containers'][0]['resources']['limits'].update(memory='8Gi'))
case('reject missing ephemeral bound', pod, 'pods', False, lambda p: p['spec']['containers'][0]['resources']['limits'].pop('ephemeral-storage'))
case('old resource-shape cleanup', pod, 'pods', True, lambda p: p['spec']['containers'][0].pop('resources'))
cases[-1]['Activation']['request']['operation'] = 'DELETE'
case('reader PVC', pvc, 'persistentvolumeclaims')
case('reader PV', pv, 'persistentvolumes')
case('reject session network labels', pod, 'pods', False, lambda p: p['metadata']['labels'].update({'app.kubernetes.io/name': 'deephive-session'}))
case('old CSI secret cleanup', pv, 'persistentvolumes', True, lambda p: p['spec']['csi']['nodePublishSecretRef'].update(name='previous', namespace='previous'))
cases[-1]['Activation']['request']['operation'] = 'DELETE'
case('reject writer claim', pod, 'pods', False, lambda p: p['spec']['volumes'][0]['persistentVolumeClaim'].update(claimName='workspace'))
case('reject reader credentials', pod, 'pods', False, lambda p: p['spec']['containers'][0].update(envFrom=[{'secretRef': {'name': 'runner'}}]))
case('reject host port', pod, 'pods', False, lambda p: p['spec']['containers'][0].update(ports=[{'containerPort': 8080, 'hostPort': 8080}]))
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
