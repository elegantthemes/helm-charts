"""Check release identity, rotation and scheduling contracts in rendered manifests."""
import copy
import json
from pathlib import Path
import subprocess
import yaml

root = Path(__file__).resolve().parent
values = json.loads((root / 'values.json').read_text())

def render(release='review', namespace='dph-app', config=None):
    raw = subprocess.check_output(['helm', 'template', release, str(root.parent.parent / 'charts/deephive'), '-n', namespace, '-f', '-'], input=json.dumps(config or values).encode())
    return [p for p in yaml.safe_load_all(raw) if p]

def item(docs, kind, suffix):
    return next(p for p in docs if p['kind'] == kind and p['metadata']['name'].endswith(suffix))

names = set()
roles = set()
for namespace, release in [('n' * 63, 'one'), ('n' * 63, 'two'), ('m' * 63, 'one'), ('a-b', 'c'), ('a', 'b-c')]:
    docs = render(release, namespace)
    policy = next(p for p in docs if p['kind'] == 'ValidatingAdmissionPolicy')
    binding = next(p for p in docs if p['kind'] == 'ValidatingAdmissionPolicyBinding')
    name = policy['metadata']['name']
    assert len(name) <= 63 and name not in names
    assert binding['spec']['policyName'] == name
    names.add(name)
    role = next(p for p in docs if p['kind'] == 'ClusterRole')
    role_binding = next(p for p in docs if p['kind'] == 'ClusterRoleBinding')
    role_name = role['metadata']['name']
    assert len(role_name) <= 63 and role_name not in roles
    assert role_binding['roleRef']['name'] == role_name
    roles.add(role_name)
print('PASS long namespace/release admission identity')

before = item(render(), 'Deployment', '-runner')['spec']['template']
changed = copy.deepcopy(values)
changed['fullEnvironment']['runnerSecretRevision'] = 'rotated-2'
changed['fullEnvironment']['prepullTolerations'] = [{'key': 'execution', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'}]
after_docs = render(config=changed)
after = item(after_docs, 'Deployment', '-runner')['spec']['template']
assert before['metadata']['annotations'] != after['metadata']['annotations']
assert after['spec']['containers'][0]['readinessProbe']['tcpSocket']['port'] == 'control'
assert item(after_docs, 'DaemonSet', '-session-prepull')['spec']['template']['spec']['tolerations'] == changed['fullEnvironment']['prepullTolerations']
proxy = item(after_docs, 'ConfigMap', '-session-egress')['data']['squid.conf']
assert 'acl approved dstdomain -n ' in proxy
print('PASS secret rotation, readiness, taints and proxy lookup configuration')

for name in ['true', 'null', '123']:
    changed['fullEnvironment'].update(pullSecret=name, runnerSecret=name, workspaceClaim=name)
    runner = item(render(config=changed), 'Deployment', '-runner')['spec']['template']['spec']
    assert runner['imagePullSecrets'][0]['name'] == name
    proxy = item(render(config=changed), 'Deployment', '-session-egress')['spec']['template']['spec']
    assert proxy['imagePullSecrets'][0]['name'] == name
    assert proxy['containers'][0]['readinessProbe']['tcpSocket']['port'] == 'proxy'
    assert runner['containers'][0]['envFrom'][0]['secretRef']['name'] == name
    assert next(v for v in runner['volumes'] if 'persistentVolumeClaim' in v)['persistentVolumeClaim']['claimName'] == name
print('PASS configured object names remain strings')

for release in ['first', 'second']:
    docs = render(release=release)
    runner_config = json.loads(item(docs, 'ConfigMap', '-runner')['data']['runner.json'])
    assert runner_config['release'] == release
    policies = [p for p in docs if p['kind'] == 'NetworkPolicy']
    sessions = next(p for p in policies if p['metadata']['name'] == release + '-sessions')
    assert sessions['spec']['podSelector']['matchLabels']['app.kubernetes.io/instance'] == release
    for suffix in ['-runner-control', '-session-egress']:
        ingress = next(p for p in policies if p['metadata']['name'] == release + suffix)
        assert ingress['spec']['ingress'][0]['from'][0]['podSelector']['matchLabels']['app.kubernetes.io/instance'] == release
print('PASS release-specific session, runner and proxy selectors')
