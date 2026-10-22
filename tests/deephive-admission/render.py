"""Check release identity, rotation and scheduling contracts in rendered manifests."""
import copy
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import yaml

root = Path(__file__).resolve().parent
values = json.loads((root / 'values.json').read_text())

# Positive activation fixtures model already-installed admission resources. The
# original chart remains used by the explicit protection-first regressions.
fixture = tempfile.TemporaryDirectory(prefix='deephive-installed-admission-')
fixture_chart = Path(fixture.name) / 'deephive'
chart = root.parent.parent / 'charts/deephive'
shutil.copytree(chart, fixture_chart)
for name in ['session-lifecycle.yml', 'source-reader.yml']:
    path = fixture_chart / 'templates' / name
    text = path.read_text()
    if name == 'session-lifecycle.yml':
        old = '$policy := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicy" "" $policyName'
        binding_name = '$policyName'
        policy_var = '$policy'
    else:
        old = '$installed := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicy" "" $policy'
        binding_name = '$policy'
        policy_var = '$installed'
    assert old in text
    text = text.replace(old, policy_var + ' := dict "metadata" (dict "generation" 1) "spec" (dict "failurePolicy" "Fail") "status" (dict "observedGeneration" 1 "typeChecking" (dict "expressionWarnings" (list)))')
    old = '$binding := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicyBinding" "" ' + binding_name
    assert old in text
    text = text.replace(old, '$binding := dict "spec" (dict "policyName" ' + binding_name + ' "validationActions" (list "Deny"))')
    path.write_text(text)

# Model bindings retained from a previously running release for stop/cleanup tests.
for filename, expressions in {
    'full-worker.yml': ['lookup "rbac.authorization.k8s.io/v1" "RoleBinding" .Release.Namespace (include "deephive.fullWorkerName" .)'],
    'source-reader.yml': [
        'lookup "rbac.authorization.k8s.io/v1" "RoleBinding" $readerNS $name',
        'lookup "rbac.authorization.k8s.io/v1" "RoleBinding" .Release.Namespace (printf "%s-workspace" $name)',
        'lookup "rbac.authorization.k8s.io/v1" "ClusterRoleBinding" "" $policy'],
}.items():
    path = fixture_chart / 'templates' / filename
    text = path.read_text()
    for expression in expressions:
        assert expression in text
        text = text.replace(expression, 'dict "metadata" (dict "name" "previous-binding")')
    path.write_text(text)

def render(release='review', namespace='dph-app', config=None, installed=False):
    config = config or values
    activated = installed or config['fullWorker'].get('runnerEnabled') or config.get('sourceReaderService', {}).get('running')
    raw = subprocess.check_output(['helm', 'template', release, str(fixture_chart if activated else chart), '-n', namespace, '-f', '-'], input=json.dumps(config).encode())
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

before = item(render(), 'Deployment', '-full-worker')['spec']['template']
changed = copy.deepcopy(values)
changed['fullWorker']['runnerSecretRevision'] = 'rotated-2'
changed['fullWorker']['prepullTolerations'] = [{'key': 'execution', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'}]
after_docs = render(config=changed)
after = item(after_docs, 'Deployment', '-full-worker')['spec']['template']
assert before['metadata']['annotations'] != after['metadata']['annotations']
assert after['spec']['containers'][0]['readinessProbe']['tcpSocket']['port'] == 'control'
assert all(t in item(after_docs, 'DaemonSet', '-full-session-prepull')['spec']['template']['spec']['tolerations'] for t in changed['fullWorker']['prepullTolerations'])
proxy = item(after_docs, 'ConfigMap', '-session-egress')['data']['squid.conf']
assert 'acl approved dstdomain -n ' in proxy
print('PASS secret rotation, readiness, taints and proxy lookup configuration')

for name in ['true', 'null', '123']:
    changed['fullWorker'].update(pullSecret=name, runnerSecret=name, workspaceClaim=name)
    runner = item(render(config=changed), 'Deployment', '-full-worker')['spec']['template']['spec']
    assert runner['imagePullSecrets'][0]['name'] == name
    proxy = item(render(config=changed), 'Deployment', '-session-egress')['spec']['template']['spec']
    assert proxy['imagePullSecrets'][0]['name'] == name
    assert proxy['containers'][0]['readinessProbe']['tcpSocket']['port'] == 'proxy'
    assert runner['containers'][0]['envFrom'][0]['secretRef']['name'] == name
    assert next(v for v in runner['volumes'] if 'persistentVolumeClaim' in v)['persistentVolumeClaim']['claimName'] == name
print('PASS configured object names remain strings')

for release in ['first', 'second']:
    docs = render(release=release)
    runner_config = json.loads(item(docs, 'ConfigMap', '-full-worker')['data']['runner.json'])
    assert runner_config['release'] == release
    policies = [p for p in docs if p['kind'] == 'NetworkPolicy']
    sessions = next(p for p in policies if p['metadata']['name'] == release + '-sessions')
    assert sessions['spec']['podSelector']['matchLabels']['app.kubernetes.io/instance'] == release
    for suffix in ['-full-worker-control', '-session-egress']:
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
runner_role = next(p for p in mysql_docs if p['kind'] == 'Role' and p['metadata']['name'] == 'review-full-worker')
assert all('secrets' not in rule['resources'] and ('list' not in rule['verbs'] or rule['resources'] == ['pods']) for rule in runner_role['rules'])
assert any(rule['resources'] == ['pods'] and 'list' in rule['verbs'] for rule in runner_role['rules'])
print('PASS consumer MySQL credential references, rotation and runner read permissions')

# Phase 3 feature-off boundaries and fresh-reader admission.
plain = render()
assert item(plain, 'NetworkPolicy', '-sessions')['spec']['ingress'] == []
assert all(rule['ports'][0]['port'] != 3002 for rule in item(plain, 'NetworkPolicy', '-full-worker-control')['spec']['ingress'])
phase3 = copy.deepcopy(values)
phase3.update(WORKSPACE_CLAIM_NAME='workspace', WORKSPACE_ROOT='/workspace-root', WORKSPACE_ACCESS_MODES=['ReadWriteMany'], VIRTUAL_HOST='deephive.example')
phase3['fullWorker'].update(
    routingEnabled=True, runnerEnabled=True, observationEnabled=True, sourceSeedPath='/workspace-root/seed',
    sourceReader={'readerId': 'fresh-csi-fixture', 'command': ['/opt/bin/read-source']},
    evidenceBucket='private-fixture', evidenceRegion='us-east-1',
    evidenceReadSecret='evidence-read', evidenceReadSecretRevision='1',
    publicOrigin='https://deephive.example', runnerSecretRevision='1',
    liteAdmissionCommand=['/opt/bin/admit'], liteHandoffCommand=['/opt/bin/stop-proof'],
    liteScratchRoot='/scratch/lite')
phase3_docs = render(config=phase3)
assert item(phase3_docs, 'NetworkPolicy', '-sessions')['spec']['ingress'][0]['ports'][0]['port'] == 5901
assert any(rule['ports'][0]['port'] == 3002 for rule in item(phase3_docs, 'NetworkPolicy', '-full-worker-control')['spec']['ingress'])
def consumer_template(docs):
    return next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['template']
before = consumer_template(phase3_docs)
rotated = copy.deepcopy(phase3)
rotated['fullWorker']['evidenceReadSecretRevision'] = '2'
assert before['metadata']['annotations'] != consumer_template(render(config=rotated))['metadata']['annotations']
print('PASS observation-off isolation and evidence credential rotation')

def rejected(config, expected):
    activated = config['fullWorker'].get('runnerEnabled') or config.get('sourceReaderService', {}).get('running')
    result = subprocess.run(['helm', 'template', 'review', str(fixture_chart if activated else chart), '-f', '-'], input=json.dumps(config), text=True, capture_output=True)
    assert result.returncode != 0 and expected in result.stderr, result.stderr
missing = copy.deepcopy(phase3)
missing['fullWorker']['sourceReader']['readerId'] = ''
rejected(missing, 'fresh reader')
missing['fullWorker']['sourceReader']['readerId'] = '  '
rejected(missing, 'fresh reader')
missing = copy.deepcopy(phase3)
missing['fullWorker']['approvedBootstraps'] = {}
rejected(missing, 'approved bootstrap/runtime identity')
missing = copy.deepcopy(phase3)
missing['fullWorker']['evidenceReadSecretRevision'] = ''
rejected(missing, 'Evidence read Secret revision required')
for origin in ['http://deephive.example', 'https://deephive.example/', 'https://deephive.example/path', 'https://deephive.example?x=1', 'https://deephive.example#fragment', 'https://user@deephive.example', 'arbitrary text']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['publicOrigin'] = origin
    rejected(missing, 'exact HTTPS origin')
print('PASS reader identity, bootstrap migration, rotation revision and HTTPS origin validation')

rotated = copy.deepcopy(phase3)
rotated['fullWorker']['runnerSecretRevision'] = '2'
rotated_docs = render(config=rotated)
assert consumer_template(phase3_docs)['metadata']['annotations'] != consumer_template(rotated_docs)['metadata']['annotations']
assert item(phase3_docs, 'Deployment', '-full-worker')['spec']['template']['metadata']['annotations'] != item(rotated_docs, 'Deployment', '-full-worker')['spec']['template']['metadata']['annotations']
for protocol in [3.7, 2.1, '3', True]:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['sessionProtocol'] = protocol
    rejected(missing, 'Session protocol must be 2 or 3')
missing = copy.deepcopy(phase3)
del missing['fullWorker']['approvedBootstraps'][missing['fullWorker']['compatibleSessionImages'][0]]
rejected(missing, 'approved bootstrap/runtime identity')
for key in ['liteAdmissionCommand', 'liteHandoffCommand']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker'][key] = []
    rejected(missing, 'Routing requires')
    missing['fullWorker'][key] = ['relative-command']
    rejected(missing, 'absolute executable paths')
print('PASS observation-token rollout, exact protocols, compatible identities and lite-worker fencing')

for origin in ['https://deephive.example:65536', 'https://deephive.example:99999', 'https://deephive.example:443', 'https://deephive.example:0', 'https://deephive.example:0443', 'https://[::::]', 'https://[a:b]']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['publicOrigin'] = origin
    rejected(missing, 'origin')
valid_port = copy.deepcopy(phase3)
valid_port['fullWorker']['publicOrigin'] = 'https://deephive.example:8443'
render(config=valid_port)
for key in ['WORKSPACE_CLAIM_NAME', 'WORKSPACE_ROOT']:
    missing = copy.deepcopy(phase3)
    missing[key] = 'different' if key.endswith('NAME') else '/different-root'
    rejected(missing, 'share the same workspace claim')
print('PASS canonical origin ports and shared workspace claim/root admission')

for seed in ['/workspace/seed', '/workspace-root', '/workspace-root/../seed', '/workspace-root//seed']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['sourceSeedPath'] = seed
    rejected(missing, 'canonical descendant')
print('PASS canonical shared source seed admission')

consumer_env = consumer_template(phase3_docs)['spec']['containers'][0]['env']
assert next(e['value'] for e in consumer_env if e['name'] == 'WORKSPACE_ROOT') == phase3['WORKSPACE_ROOT']
print('PASS routing consumer uses the configured canonical workspace root')

for scratch in ['/workspace-root/seed/scratch', '/workspace-root', '/', '/scratch/../scratch']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['liteScratchRoot'] = scratch
    rejected(missing, 'scratch must be canonical and disjoint')
missing = copy.deepcopy(phase3)
missing['fullWorker']['publicOrigin'] = 'https://other.example'
rejected(missing, 'hostname must match')
missing = copy.deepcopy(phase3)
missing['WORKSPACE_ACCESS_MODES'] = ['ReadWriteOnce']
rejected(missing, 'ReadWriteMany')
for secret in ['runner', 'agent', 'integration', 'secrets']:
    missing = copy.deepcopy(phase3)
    missing['fullWorker']['evidenceReadSecret'] = secret
    rejected(missing, 'dedicated read-only Secret')
print('PASS disjoint scratch, ingress host, multi-node claim and reader credential boundaries')

# Old protocol 2 manifests drain without invented bootstrap metadata.
legacy = copy.deepcopy(values)
image = legacy['fullWorker']['compatibleSessionImages'][0]
legacy['fullWorker']['approvedBootstraps'].pop(image)
legacy['fullWorker']['legacyProtocol2Images'] = [image]
render(config=legacy)
invalid = copy.deepcopy(legacy)
invalid['fullWorker']['legacyProtocol2Images'].append(invalid['fullWorker']['sessionImage'])
assert subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-f', '-'], input=json.dumps(invalid).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
invalid = copy.deepcopy(phase3)
invalid['fullWorker']['liteInstallCommand'] = []
render(config=invalid)
invalid['fullWorker']['liteInstallCommand'] = ['relative-installer']
assert subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-f', '-'], input=json.dumps(invalid).encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
print('PASS explicit protocol 2 drain exception and optional trusted installer')

# Protection installation must not grant a runner admission identity prematurely.
docs = render()
assert item(docs, 'Deployment', '-full-worker')['spec']['replicas'] == 0
assert not any(p['kind'] == 'RoleBinding' and p['metadata']['name'].endswith('-full-worker') for p in docs)
hook = item(docs, 'Job', '-session-drain-check')
assert hook['metadata']['annotations']['helm.sh/hook'] == 'pre-delete'
assert hook['spec']['activeDeadlineSeconds'] == 120
assert 'Runner pods remain' in hook['spec']['template']['spec']['containers'][0]['args'][0]
changed = copy.deepcopy(values)
changed['fullWorker']['runnerEnabled'] = True
attempt = subprocess.run(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', '-'], input=json.dumps(changed).encode(), capture_output=True)
assert attempt.returncode != 0 and b'runnerEnabled=false' in attempt.stderr
print('PASS protection-first install and drain-before-uninstall gate')

# Local task cancellation does not require a privileged node-wide fence command.
changed = copy.deepcopy(values)
changed['fullWorker']['pressureCommand'] = []
docs = render(config=changed)
consumer = next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['template']['spec']
probe = next(v for v in consumer['volumes'] if v['name'] == 'lite-cache-probe')
assert probe['hostPath'] == {'path': '/var/lib/deephive/cache', 'type': 'Directory'}
mount = next(v for v in consumer['containers'][0]['volumeMounts'] if v['name'] == 'lite-cache-probe')
assert mount['readOnly'] is True
assert next(e for e in consumer['containers'][0]['env'] if e['name'] == 'LITE_WORKER_CACHE_ROOT')['value'] == '/lite-cache-probe'
print('PASS local pressure probe and optional infrastructure hook')

# Built-in hooks receive the exact config consumed by the compiled CLI.
builtin = copy.deepcopy(phase3)
builtin['fullWorker'].update(liteAdmissionCommand=[], liteHandoffCommand=[], liteCapacity={'enabled': True, 'pool': 'stage-lite', 'slots': 1, 'memoryMiB': 4096, 'taskMiB': 4096})
docs = render(config=builtin)
capacity = json.loads(item(docs, 'ConfigMap', '-lite-capacity')['data']['capacity.json'])
assert capacity == {'pool': 'stage-lite', 'workspaceRoot': phase3['WORKSPACE_ROOT'], 'slots': 1, 'memoryMiB': 4096, 'taskMiB': 4096}
consumer = consumer_template(docs)['spec']
env = {e['name']: e.get('value') for e in consumer['containers'][0]['env']}
for name, action in [('LITE_WORKER_ADMISSION_COMMAND', 'admit'), ('LITE_WORKER_HANDOFF_COMMAND', 'release')]:
    command = json.loads(env[name])
    assert command[-2:] == ['/lite-config/capacity.json', action]
    assert command[2].endswith('/dist/scripts/environment/lite-capacity.js')
assert any(v.get('configMap', {}).get('name') == 'review-lite-capacity' for v in consumer['volumes'])
assert any('emptyDir' in v for v in consumer['volumes'])
invalid = copy.deepcopy(builtin)
invalid['fullWorker']['liteCapacity']['taskMiB'] = 8192
rejected(invalid, 'positive slot and memory budgets')
invalid = copy.deepcopy(builtin)
invalid['fullWorker']['liteHandoffCommand'] = ['/bin/true']
rejected(invalid, 'not both')
print('PASS built-in capacity config, commands, scratch and budget validation')
seed = copy.deepcopy(values)
seed['WORKSPACE_ROOT'] = seed['fullWorker'].get('workspaceRoot', '/workspace-root')
seed['WORKSPACE_CLAIM_NAME'] = seed['fullWorker']['workspaceClaim']
seed['fullWorker'].update(sourceSeedExportEnabled=True, sourceSeedPath='/workspace-root/seeds/candidate')
docs = render(config=seed)
job = next(p for p in docs if p['kind'] == 'Job' and '-seed-' in p['metadata']['name'])
assert job['spec']['backoffLimit'] == 0
pod = job['spec']['template']['spec']
assert pod['automountServiceAccountToken'] is False
assert pod['containers'][0]['command'][-1].endswith('/export-source-seed.js')
assert 'envFrom' not in pod['containers'][0]
seed['fullWorker']['sourceSeedPath'] = '/outside'
rejected(seed, 'canonical workspace descendant')
print('PASS credential-free, explicit source seed export')

# The uninstall hook reads both Deployments even when the reader was disabled.
for release in ['review', 'other']:
    docs = render(release=release)
    role = item(docs, 'Role', '-session-drain-check')
    deployment_rule = next(r for r in role['rules'] if r['resources'] == ['deployments'])
    assert deployment_rule['verbs'] == ['get']
    assert set(deployment_rule['resourceNames']) == {release + '-full-worker', release + '-source-reader'}
print('PASS uninstall hook can read both drained deployment identities')

# Source export is prepared against the same claim and root even with routing off.
seed = copy.deepcopy(values)
seed['WORKSPACE_ROOT'] = seed['fullWorker'].get('workspaceRoot', '/workspace-root')
seed['WORKSPACE_CLAIM_NAME'] = seed['fullWorker']['workspaceClaim']
seed['fullWorker'].update(sourceSeedExportEnabled=True, sourceSeedPath='/workspace-root/seeds/candidate')
docs = render(config=seed)
job = next(p for p in docs if p['kind'] == 'Job' and '-seed-' in p['metadata']['name'])
assert {'key': 'deephive-full', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'} in job['spec']['template']['spec']['tolerations']
for key in ['WORKSPACE_CLAIM_NAME', 'WORKSPACE_ROOT']:
    invalid = copy.deepcopy(seed)
    invalid[key] = 'other' if key == 'WORKSPACE_CLAIM_NAME' else '/other'
    rejected(invalid, 'active consumer workspace')
runner = item(docs, 'Deployment', '-full-worker')['spec']['template']['spec']
assert all(v['hostPath']['type'] == 'Directory' for v in runner['volumes'] if 'hostPath' in v)
hook = item(docs, 'Job', '-session-drain-check')
role = item(docs, 'Role', '-session-drain-check')
assert not any('pods/log' in r['resources'] for r in role['rules'])
cluster_role = next(p for p in docs if p['kind'] == 'ClusterRole' and p['metadata']['name'].startswith('dph-drain-'))
assert cluster_role['rules'] == [{'apiGroups': [''], 'resources': ['persistentvolumes'], 'verbs': ['list']}]
assert 'const readerNamespace' not in hook['spec']['template']['spec']['containers'][0]['args'][0]
assert '/persistentvolumes?labelSelector=' in hook['spec']['template']['spec']['containers'][0]['args'][0]
print('PASS probe directories, seed workspace/taint and retained reader storage drain checks')

# Routing activation cannot select a stopped runner or managed reader broker.
invalid = copy.deepcopy(phase3)
invalid['fullWorker']['runnerEnabled'] = False
rejected(invalid, 'runnerEnabled=true')
invalid = copy.deepcopy(phase3)
invalid['sourceReaderService'] = {'enabled': True, 'running': False, 'tokenSecret': 'reader-token', 'tokenRevision': '1', 'nodeName': 'reader-node'}
rejected(invalid, 'managed source reader running=true')
managed = copy.deepcopy(values)
managed['INSTALL_PATH'] = '/custom/deephive'
managed['sourceReaderService'] = invalid['sourceReaderService']
docs = render(config=managed)
command = json.loads(next(e['value'] for e in consumer_template(docs)['spec']['containers'][0]['env'] if e['name'] == 'FULL_WORKER_READER_CONFIG'))['command']
assert command[2] == '/custom/deephive/dist/scripts/environment/remote-source-reader.js'
seed = copy.deepcopy(values)
seed.update(WORKSPACE_ROOT='/workspace-root', WORKSPACE_CLAIM_NAME='workspace')
seed['fullWorker'].update(sourceSeedExportEnabled=True, sourceSeedPath='/workspace-root/seeds/candidate')
def seed_name(config):
    return next(p['metadata']['name'] for p in render(config=config) if p['kind'] == 'Job' and '-seed-' in p['metadata']['name'])
original = seed_name(seed)
for key, value in [('nodeName', 'other-node'), ('pullSecret', 'new-pull'), ('prepullTolerations', [{'key': 'extra', 'operator': 'Exists'}])]:
    changed = copy.deepcopy(seed)
    changed['fullWorker'][key] = value
    assert seed_name(changed) != original
print('PASS routing activation, custom install root and immutable seed-job replacement')

managed = copy.deepcopy(values)
managed['sourceReaderService'] = {'enabled': True, 'running': True, 'tokenSecret': 'reader-token', 'tokenRevision': '1', 'nodeName': 'reader-node'}
docs = render(config=managed)
reader_namespace = json.loads(item(docs, 'ConfigMap', '-source-reader')['data']['reader.json'])['namespace']
assert reader_namespace != 'dph-app' and len(reader_namespace) <= 63
bindings = [d for d in docs if d['kind'] == 'RoleBinding' and d['metadata']['name'] == 'review-source-reader']
assert len(bindings) == 1 and bindings[0]['metadata']['namespace'] == reader_namespace
assert bindings[0]['subjects'][0]['namespace'] == 'dph-app'
roles = [d for d in docs if d['kind'] == 'Role' and any('pods/log' in r['resources'] for r in d['rules'])]
assert roles and all(d['metadata']['namespace'] == reader_namespace for d in roles)
workspace = item(docs, 'Role', '-source-reader-workspace')
assert workspace['rules'] == [{'apiGroups': [''], 'resources': ['persistentvolumeclaims'], 'resourceNames': ['workspace'], 'verbs': ['get']}]
network = item(docs, 'NetworkPolicy', '-source-reader-workloads')
assert network['metadata']['namespace'] == reader_namespace and network['spec']['egress'] == []
for name, volume in [('review', 'source-reader-token'), ('review-full-worker', 'source-reader-token'), ('review-source-reader', 'token')]:
    pod = next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == name)['spec']['template']['spec']
    secret = next(v['secret'] for v in pod['volumes'] if v['name'] == volume)
    assert secret['items'] == [{'key': 'token', 'path': 'token'}]
reader_drain = item(docs, 'Role', '-session-drain-check-reader')
assert reader_drain['metadata']['namespace'] == reader_namespace
assert reader_drain['rules'][0]['resources'] == ['pods', 'persistentvolumeclaims']
script = item(docs, 'Job', '-session-drain-check')['spec']['template']['spec']['containers'][0]['args'][0]
assert reader_namespace in script and '/persistentvolumeclaims?labelSelector=' in script
invalid = copy.deepcopy(managed)
invalid['sourceReaderService']['tokenSecret'] = 'runner'
rejected(invalid, 'dedicated Secret')
print('PASS dedicated reader namespace, scoped logs, kubelet-only credentials and token projections')

stopped = copy.deepcopy(managed)
stopped['sourceReaderService']['running'] = False
stopped['fullWorker']['runnerEnabled'] = False
docs = render(config=stopped, installed=True)
for name in ['review-full-worker', 'review-source-reader', 'review-source-reader-workspace']:
    assert any(d['kind'] == 'RoleBinding' and d['metadata']['name'] == name for d in docs)
assert any(d['kind'] == 'ClusterRoleBinding' and d['roleRef']['name'].startswith('dph-reader-') for d in docs)
print('PASS stopped workloads retain previously granted cleanup permissions')

long_names = set()
for release in ['a' * 50 + 'one', 'a' * 50 + 'two']:
    docs = render(release=release, config=managed)
    broker = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].startswith('a') and any(v.get('name') == 'token' for v in d['spec']['template']['spec'].get('volumes', [])))
    name = broker['metadata']['name']
    assert len(name) <= 53 and name not in long_names
    long_names.add(name)
    assert any(d['kind'] == 'Service' and d['metadata']['name'] == name for d in docs)
    assert len(broker['spec']['template']['metadata']['labels']['app']) <= 63
    consumer = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == release)
    config = json.loads(next(e['value'] for e in consumer['spec']['template']['spec']['containers'][0]['env'] if e['name'] == 'FULL_WORKER_READER_CONFIG'))
    assert 'http://' + name + ':3003' in config['command']
    assert all(len(d['metadata']['name']) <= 63 for d in docs if d['kind'] == 'Job')
print('PASS bounded, collision-resistant reader and drain identities')

with tempfile.TemporaryDirectory(prefix='reader-default-off-') as temp:
    target = Path(temp) / 'chart'
    shutil.copytree(chart, target)
    path = target / 'templates/session-lifecycle.yml'
    text = path.read_text().replace('lookup "v1" "PersistentVolume" "" ""', 'fail "unexpected cluster PV lookup"')
    path.write_text(text)
    subprocess.run(['helm', 'template', 'review', str(target), '--is-upgrade', '-n', 'dph-app', '-f', '-'], input=json.dumps(values).encode(), stdout=subprocess.DEVNULL, check=True)
print('PASS never-enabled reader upgrade avoids cluster storage lookup')

# Regression evidence: conditional activation keeps the runner Role and binding
# as distinct YAML documents, including after the binding is retained on stop.
for config in [phase3, stopped]:
    docs = render(config=config, installed=True)
    role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'review-full-worker')
    binding = next(d for d in docs if d['kind'] == 'RoleBinding' and d['metadata']['name'] == 'review-full-worker')
    assert 'rules' in role and 'rules' not in binding
    assert binding['roleRef']['name'] == role['metadata']['name']
print('PASS runner Role and conditional RoleBinding are separate documents')

# ConfigMaps use DNS subdomain names (253 chars), unlike Service DNS labels.
for release in ['a' * 50 + 'one', 'a' * 50 + 'two']:
    docs = render(release=release, config=builtin)
    capacity = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith('-lite-capacity'))
    assert all(len(d['metadata']['name']) <= 63 for d in docs if d['kind'] == 'Service')
    assert capacity['metadata']['name'] == release + '-lite-capacity'
    assert len(capacity['metadata']['name']) <= 253
    consumer = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == release)
    assert any(v.get('configMap', {}).get('name') == capacity['metadata']['name'] for v in consumer['spec']['template']['spec']['volumes'])
print('PASS long-release capacity ConfigMap identity and volume reference')

# Cache metadata startup recovery requires a stopped predecessor. Intake keeps
# its existing independent rolling update and never receives worker boot identity.
cache_docs = render()
consumer = next(p for p in cache_docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')
assert consumer['spec']['strategy'] == {'type': 'Recreate'}
env = consumer['spec']['template']['spec']['containers'][0]['env']
assert next(e for e in env if e['name'] == 'POD_UID') == {'name': 'POD_UID', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.uid'}}}
intake = next(p for p in cache_docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review-intake')
assert intake['spec']['strategy'].get('type', 'RollingUpdate') != 'Recreate'
assert not any(e['name'] == 'POD_UID' for e in intake['spec']['template']['spec']['containers'][0]['env'])
for replicas in [0, 1]:
    config = copy.deepcopy(values)
    config['REPLICAS'] = replicas
    assert next(p for p in render(config=config) if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['replicas'] == replicas
config = copy.deepcopy(values)
config['REPLICAS'] = 2
invalid = subprocess.run(['helm', 'template', 'review', str(chart), '-n', 'dph-app', '-f', '-'], input=json.dumps(config), text=True, capture_output=True)
assert invalid.returncode and 'at most one consumer replica' in invalid.stderr
print('PASS single-consumer Recreate, Downward API identity and unchanged intake rollout')
