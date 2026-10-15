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

mysql = copy.deepcopy(values)
mysql.update(MYSQL_ENABLED=True, MYSQL_PASSWORD='fixture-user-password', MYSQL_ROOT_PASSWORD='fixture-root-password')
mysql_docs = render(config=mysql)
consumer = next(p for p in mysql_docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')
secret = next(p for p in mysql_docs if p['kind'] == 'Secret' and p['metadata']['name'] == 'secrets')
for key in ['MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD']:
    assert secret['stringData'][key] == mysql[key]
    for pod_owner in (p for p in mysql_docs if p['kind'] in ['Deployment', 'DaemonSet']):
        assert mysql[key] not in json.dumps(pod_owner['spec']['template'])
    sidecar = next(c for c in consumer['spec']['template']['spec']['containers'] if c['name'] == 'mysql')
    env = next(e for e in sidecar['env'] if e['name'] == key)
    assert env == {'name': key, 'valueFrom': {'secretKeyRef': {'name': 'secrets', 'key': key}}}
mysql['MYSQL_PASSWORD'] = 'rotated-fixture-password'
rotated = next(p for p in render(config=mysql) if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')
assert rotated['spec']['template']['metadata']['annotations'] != consumer['spec']['template']['metadata']['annotations']
runner_role = next(p for p in mysql_docs if p['kind'] == 'Role' and p['metadata']['name'] == 'review-runner')
assert all('secrets' not in rule['resources'] and ('list' not in rule['verbs'] or rule['resources'] == ['pods']) for rule in runner_role['rules'])
assert any(rule['resources'] == ['pods'] and 'list' in rule['verbs'] for rule in runner_role['rules'])
print('PASS consumer MySQL credential references, rotation and runner read permissions')

# Phase 3 feature-off boundaries and fresh-reader admission.
plain = render()
assert item(plain, 'NetworkPolicy', '-sessions')['spec']['ingress'] == []
assert all(rule['ports'][0]['port'] != 3002 for rule in item(plain, 'NetworkPolicy', '-runner-control')['spec']['ingress'])
phase3 = copy.deepcopy(values)
phase3.update(WORKSPACE_CLAIM_NAME='workspace', WORKSPACE_ROOT='/workspace-root', WORKSPACE_ACCESS_MODES=['ReadWriteMany'], VIRTUAL_HOST='deephive.example')
phase3['fullEnvironment'].update(
    routingEnabled=True, observationEnabled=True, sourceSeedPath='/workspace-root/seed',
    sourceReader={'readerId': 'fresh-csi-fixture', 'command': ['/opt/bin/read-source']},
    evidenceBucket='private-fixture', evidenceRegion='us-east-1',
    evidenceReadSecret='evidence-read', evidenceReadSecretRevision='1',
    publicOrigin='https://deephive.example', runnerSecretRevision='1',
    ordinaryAdmissionCommand=['/opt/bin/admit'], ordinaryHandoffCommand=['/opt/bin/stop-proof'],
    ordinaryScratchRoot='/scratch/ordinary')
phase3_docs = render(config=phase3)
assert item(phase3_docs, 'NetworkPolicy', '-sessions')['spec']['ingress'][0]['ports'][0]['port'] == 5901
assert any(rule['ports'][0]['port'] == 3002 for rule in item(phase3_docs, 'NetworkPolicy', '-runner-control')['spec']['ingress'])
def consumer_template(docs):
    return next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['template']
before = consumer_template(phase3_docs)
rotated = copy.deepcopy(phase3)
rotated['fullEnvironment']['evidenceReadSecretRevision'] = '2'
assert before['metadata']['annotations'] != consumer_template(render(config=rotated))['metadata']['annotations']
print('PASS observation-off isolation and evidence credential rotation')

def rejected(config, expected):
    result = subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-f', '-'], input=json.dumps(config), text=True, capture_output=True)
    assert result.returncode != 0 and expected in result.stderr, result.stderr
missing = copy.deepcopy(phase3)
missing['fullEnvironment']['sourceReader']['readerId'] = ''
rejected(missing, 'fresh reader')
missing['fullEnvironment']['sourceReader']['readerId'] = '  '
rejected(missing, 'fresh reader')
missing = copy.deepcopy(phase3)
missing['fullEnvironment']['approvedBootstraps'] = {}
rejected(missing, 'approved bootstrap/runtime identity')
missing = copy.deepcopy(phase3)
missing['fullEnvironment']['evidenceReadSecretRevision'] = ''
rejected(missing, 'Evidence read Secret revision required')
for origin in ['http://deephive.example', 'https://deephive.example/', 'https://deephive.example/path', 'https://deephive.example?x=1', 'https://deephive.example#fragment', 'https://user@deephive.example', 'arbitrary text']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['publicOrigin'] = origin
    rejected(missing, 'exact HTTPS origin')
print('PASS reader identity, bootstrap migration, rotation revision and HTTPS origin validation')

rotated = copy.deepcopy(phase3)
rotated['fullEnvironment']['runnerSecretRevision'] = '2'
rotated_docs = render(config=rotated)
assert consumer_template(phase3_docs)['metadata']['annotations'] != consumer_template(rotated_docs)['metadata']['annotations']
assert item(phase3_docs, 'Deployment', '-runner')['spec']['template']['metadata']['annotations'] != item(rotated_docs, 'Deployment', '-runner')['spec']['template']['metadata']['annotations']
for protocol in [3.7, 2.1, '3', True]:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['sessionProtocol'] = protocol
    rejected(missing, 'Session protocol must be 2 or 3')
missing = copy.deepcopy(phase3)
del missing['fullEnvironment']['approvedBootstraps'][missing['fullEnvironment']['compatibleSessionImages'][0]]
rejected(missing, 'approved bootstrap/runtime identity')
for key in ['ordinaryAdmissionCommand', 'ordinaryHandoffCommand']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment'][key] = []
    rejected(missing, 'Routing requires')
    missing['fullEnvironment'][key] = ['relative-command']
    rejected(missing, 'absolute executable paths')
print('PASS observation-token rollout, exact protocols, compatible identities and ordinary-worker fencing')

for origin in ['https://deephive.example:65536', 'https://deephive.example:99999', 'https://deephive.example:443', 'https://deephive.example:0', 'https://deephive.example:0443', 'https://[::::]', 'https://[a:b]']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['publicOrigin'] = origin
    rejected(missing, 'origin')
valid_port = copy.deepcopy(phase3)
valid_port['fullEnvironment']['publicOrigin'] = 'https://deephive.example:8443'
render(config=valid_port)
for key in ['WORKSPACE_CLAIM_NAME', 'WORKSPACE_ROOT']:
    missing = copy.deepcopy(phase3)
    missing[key] = 'different' if key.endswith('NAME') else '/different-root'
    rejected(missing, 'share the same workspace claim')
print('PASS canonical origin ports and shared workspace claim/root admission')

for seed in ['/workspace/seed', '/workspace-root', '/workspace-root/../seed', '/workspace-root//seed']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['sourceSeedPath'] = seed
    rejected(missing, 'canonical descendant')
print('PASS canonical shared source seed admission')

consumer_env = consumer_template(phase3_docs)['spec']['containers'][0]['env']
assert next(e['value'] for e in consumer_env if e['name'] == 'WORKSPACE_ROOT') == phase3['WORKSPACE_ROOT']
print('PASS routing consumer uses the configured canonical workspace root')

for scratch in ['/workspace-root/seed/scratch', '/workspace-root', '/', '/scratch/../scratch']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['ordinaryScratchRoot'] = scratch
    rejected(missing, 'scratch must be canonical and disjoint')
missing = copy.deepcopy(phase3)
missing['fullEnvironment']['publicOrigin'] = 'https://other.example'
rejected(missing, 'hostname must match')
missing = copy.deepcopy(phase3)
missing['WORKSPACE_ACCESS_MODES'] = ['ReadWriteOnce']
rejected(missing, 'ReadWriteMany')
for secret in ['runner', 'agent', 'integration', 'secrets']:
    missing = copy.deepcopy(phase3)
    missing['fullEnvironment']['evidenceReadSecret'] = secret
    rejected(missing, 'dedicated read-only Secret')
print('PASS disjoint scratch, ingress host, multi-node claim and reader credential boundaries')

# Old protocol 2 manifests drain without invented bootstrap metadata.
legacy = copy.deepcopy(values)
image = legacy['fullEnvironment']['compatibleSessionImages'][0]
legacy['fullEnvironment']['approvedBootstraps'].pop(image)
legacy['fullEnvironment']['legacyProtocol2Images'] = [image]
render(config=legacy)
invalid = copy.deepcopy(legacy)
invalid['fullEnvironment']['legacyProtocol2Images'].append(invalid['fullEnvironment']['sessionImage'])
assert subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-f', '-'], input=json.dumps(invalid).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
invalid = copy.deepcopy(phase3)
invalid['fullEnvironment']['ordinaryInstallCommand'] = []
render(config=invalid)
invalid['fullEnvironment']['ordinaryInstallCommand'] = ['relative-installer']
assert subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-f', '-'], input=json.dumps(invalid).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
print('PASS explicit protocol 2 drain exception and optional trusted installer')

# Protection installation must not grant a runner admission identity prematurely.
docs = render()
assert item(docs, 'Deployment', '-runner')['spec']['replicas'] == 0
assert not any(p['kind'] == 'RoleBinding' and p['metadata']['name'].endswith('-runner') for p in docs)
hook = item(docs, 'Job', '-session-drain-check')
assert hook['metadata']['annotations']['helm.sh/hook'] == 'pre-delete'
assert hook['spec']['activeDeadlineSeconds'] == 120
assert 'Runner pods remain' in hook['spec']['template']['spec']['containers'][0]['args'][0]
changed = copy.deepcopy(values)
changed['fullEnvironment']['runnerEnabled'] = True
attempt = subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', '-'], input=json.dumps(changed).encode(), capture_output=True)
assert attempt.returncode != 0 and b'runnerEnabled=false' in attempt.stderr
print('PASS protection-first install and drain-before-uninstall gate')

# Local task cancellation does not require a privileged node-wide fence command.
changed = copy.deepcopy(values)
changed['fullEnvironment']['pressureCommand'] = []
docs = render(config=changed)
consumer = next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['template']['spec']
probe = next(v for v in consumer['volumes'] if v['name'] == 'ordinary-cache-probe')
assert probe['hostPath'] == {'path': '/var/lib/deephive/cache', 'type': 'Directory'}
mount = next(v for v in consumer['containers'][0]['volumeMounts'] if v['name'] == 'ordinary-cache-probe')
assert mount['readOnly'] is True
assert next(e for e in consumer['containers'][0]['env'] if e['name'] == 'FULL_ENVIRONMENT_ORDINARY_CACHE_ROOT')['value'] == '/ordinary-cache-probe'
print('PASS local pressure probe and optional infrastructure hook')

# Built-in hooks receive the exact config consumed by the compiled CLI.
builtin = copy.deepcopy(phase3)
builtin['fullEnvironment'].update(ordinaryAdmissionCommand=[], ordinaryHandoffCommand=[], ordinaryCapacity={'enabled': True, 'pool': 'stage-ordinary', 'slots': 1, 'memoryMiB': 4096, 'taskMiB': 4096})
docs = render(config=builtin)
capacity = json.loads(item(docs, 'ConfigMap', '-ordinary-capacity')['data']['capacity.json'])
assert capacity == {'pool': 'stage-ordinary', 'workspaceRoot': phase3['WORKSPACE_ROOT'], 'slots': 1, 'memoryMiB': 4096, 'taskMiB': 4096}
consumer = consumer_template(docs)['spec']
env = {e['name']: e.get('value') for e in consumer['containers'][0]['env']}
for name, action in [('FULL_ENVIRONMENT_ORDINARY_ADMISSION_COMMAND', 'admit'), ('FULL_ENVIRONMENT_ORDINARY_HANDOFF_COMMAND', 'release')]:
    command = json.loads(env[name])
    assert command[-2:] == ['/ordinary-config/capacity.json', action]
    assert command[2].endswith('/dist/scripts/environment/ordinary-capacity.js')
assert any(v.get('configMap', {}).get('name') == 'review-ordinary-capacity' for v in consumer['volumes'])
assert any('emptyDir' in v for v in consumer['volumes'])
invalid = copy.deepcopy(builtin)
invalid['fullEnvironment']['ordinaryCapacity']['taskMiB'] = 8192
rejected(invalid, 'positive slot and memory budgets')
invalid = copy.deepcopy(builtin)
invalid['fullEnvironment']['ordinaryHandoffCommand'] = ['/bin/true']
rejected(invalid, 'not both')
print('PASS built-in capacity config, commands, scratch and budget validation')
seed = copy.deepcopy(values)
seed['fullEnvironment'].update(sourceSeedExportEnabled=True, sourceSeedPath='/workspace-root/seeds/candidate')
docs = render(config=seed)
job = next(p for p in docs if p['kind'] == 'Job' and '-seed-' in p['metadata']['name'])
assert job['spec']['backoffLimit'] == 0
pod = job['spec']['template']['spec']
assert pod['automountServiceAccountToken'] is False
assert pod['containers'][0]['command'][-1].endswith('/export-source-seed.js')
assert 'envFrom' not in pod['containers'][0]
seed['fullEnvironment']['sourceSeedPath'] = '/outside'
rejected(seed, 'canonical workspace descendant')
print('PASS credential-free, explicit source seed export')
