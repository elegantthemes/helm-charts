"""Render and evaluate the admission CEL locally; never contacts Kubernetes."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import yaml

root = Path(__file__).resolve().parent
rendered = subprocess.check_output([
    'helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'),
    '-n', 'dph-app', '-f', str(root / 'values.json'),
], text=True)
policy = next(p for p in yaml.safe_load_all(rendered)
              if p and p['kind'] == 'ValidatingAdmissionPolicy')
# Generated from DeepHive's sessionPod; includes representative directory/file
# dependency mounts and the API server's default serviceAccountName.
original = json.loads((root / 'pod.json').read_text())
cases = []


def case(name, expected, change=None, operation='CREATE', old=None):
    pod = copy.deepcopy(original)
    if change:
        change(pod)
    cases.append({'Name': name, 'Expect': expected, 'Activation': {
        'object': pod, 'oldObject': old or pod,
        'request': {'operation': operation},
        'variables': {'pod': pod, 'containers': pod['spec']['containers'] + pod['spec']['initContainers']},
    }})


case('real session manifest', True)
case('harmless extra metadata', True, lambda p: p['metadata']['labels'].update({'example.internal/notes': 'demo', 'app.kubernetes.io/version': '1.4.80'}))
case('legacy session without mode metadata', True, lambda p: p['metadata']['labels'].pop('deephive/worker-mode'))
case('spoofed Lite mode', False, lambda p: p['metadata']['labels'].update({'deephive/worker-mode': 'lite'}))
for key in ['app', 'release', 'redis-client', 'k8s-app', 'deephive/role', 'deephive/source-reader']:
    case('forbidden isolation label ' + key, False, lambda p, key=key: p['metadata']['labels'].update({key: 'true'}))
case('foreign release', False, lambda p: p['metadata']['labels'].update({'app.kubernetes.io/instance': 'other'}))
case('missing release', False, lambda p: p['metadata']['labels'].pop('app.kubernetes.io/instance'))
foreign = copy.deepcopy(original)
foreign['metadata']['labels']['app.kubernetes.io/instance'] = 'other'
case('relabel foreign pod', False, operation='UPDATE', old=foreign)
case('compatible image adoption after upgrade', True, lambda p: p['spec']['containers'][0].update(image='ghcr.io/elegantthemes/session@sha256:' + 'e' * 64))
case('hostPath', False, lambda p: p['spec']['volumes'].append({'name': 'host', 'hostPath': {'path': '/'}}))
case('consumer credential env', False, lambda p: p['spec']['containers'][0]['env'].append({'name': 'BAD', 'valueFrom': {'secretKeyRef': {'name': 'secrets', 'key': 'GITHUB_TOKEN'}}}))
case('consumer envFrom', False, lambda p: p['spec']['containers'][0].update(envFrom=[{'secretRef': {'name': 'secrets'}}]))
case('missing policy label', False, lambda p: p['metadata']['labels'].clear())
case('spoofed privileged workload label', False, lambda p: p['metadata']['labels'].update(app='review-full-worker'))
case('runner service account', False, lambda p: p['spec'].update(serviceAccountName='review-full-worker'))
case('projected API token', False, lambda p: p['spec']['volumes'].append({'name': 'token', 'projected': {'sources': [{'serviceAccountToken': {'path': 'token'}}]}}))
case('host network', False, lambda p: p['spec'].update(hostNetwork=True))
case('host PID', False, lambda p: p['spec'].update(hostPID=True))
case('privileged container', False, lambda p: p['spec']['containers'][0]['securityContext'].update(privileged=True))
case('extra capability', False, lambda p: p['spec']['containers'][0]['securityContext']['capabilities']['add'].append('SYS_ADMIN'))
case('whole workspace', False, lambda p: p['spec']['containers'][0]['volumeMounts'][0].update(subPath=''))
case('parent path traversal', False, lambda p: p['spec']['containers'][0]['volumeMounts'][0].update(subPath='task/../another'))
case('host port', False, lambda p: p['spec']['containers'][0].update(ports=[{'containerPort': 80, 'hostPort': 80}]))
case('unapproved image', False, lambda p: p['spec']['containers'][0].update(image='attacker/image'))
case('compatible old-image cleanup', True, lambda p: p['spec']['containers'][0].update(image='previous-approved-image'), operation='DELETE')
case('metadata-only update', True, lambda p: p['metadata'].update(finalizers=[]), operation='UPDATE', old=original)
case('spec-changing update', False, lambda p: p['spec'].update(hostNetwork=True), operation='UPDATE', old=original)

case('unbounded emptyDir', False, lambda p: p['spec']['volumes'][1].update(emptyDir={}))
case('oversized emptyDir', False, lambda p: p['spec']['volumes'][1]['emptyDir'].update(sizeLimit='300Gi'))
case('unexpected memory-backed dependencies', False, lambda p: p['spec']['volumes'][1]['emptyDir'].update(medium='Memory'))
case('missing cpu limit', False, lambda p: p['spec']['containers'][0]['resources']['limits'].pop('cpu'))
case('oversized cpu limit', False, lambda p: p['spec']['containers'][0]['resources']['limits'].update(cpu='64'))
case('missing memory limit', False, lambda p: p['spec']['containers'][0]['resources']['limits'].pop('memory'))
case('oversized memory limit', False, lambda p: p['spec']['containers'][0]['resources']['limits'].update(memory='32Gi'))
case('missing database disk limit', False, lambda p: p['spec']['containers'][1]['resources']['limits'].pop('ephemeral-storage'))
case('missing init disk limit', False, lambda p: p['spec']['initContainers'][0]['resources']['limits'].pop('ephemeral-storage'))

with tempfile.TemporaryDirectory(prefix='deephive-admission-') as temp:
    fixture = Path(temp) / 'fixtures.json'
    fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in policy['spec']['validations']], 'Cases': cases}))
    subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)


# Explicitly reuse only the deployed Lite GitHub key, not the consumer Secret.
shared_render = subprocess.check_output([
    'helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'),
    '-n', 'dph-app', '-f', str(root / 'values.json'),
    '--set', 'fullWorker.githubSecretRef.name=review-full-runner',
    '--set', 'fullWorker.githubSecretRef.key=GH_TOKEN',
], text=True)
shared_policy = next(p for p in yaml.safe_load_all(shared_render)
                     if p and p['kind'] == 'ValidatingAdmissionPolicy')
cases = []
case('exact Lite GitHub key', True, lambda p: p['spec']['containers'][0]['env'].append({'name': 'GITHUB_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'review-full-runner', 'key': 'GH_TOKEN'}}}))
case('unrelated runner database key', False, lambda p: p['spec']['containers'][0]['env'].append({'name': 'BAD', 'valueFrom': {'secretKeyRef': {'name': 'review-full-runner', 'key': 'REDIS_URL'}}}))
case('unrelated runner model key', False, lambda p: p['spec']['containers'][0]['env'].append({'name': 'BAD', 'valueFrom': {'secretKeyRef': {'name': 'review-full-runner', 'key': 'OPENAI_API_KEY'}}}))
case('whole consumer Secret still forbidden', False, lambda p: p['spec']['containers'][0].update(envFrom=[{'secretRef': {'name': 'secrets'}}]))
with tempfile.TemporaryDirectory(prefix='deephive-shared-github-') as temp:
    fixture = Path(temp) / 'fixtures.json'
    fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in shared_policy['spec']['validations']], 'Cases': cases}))
    subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)
