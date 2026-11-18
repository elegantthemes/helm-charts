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
for name in ['session-lifecycle.yml']:
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
    if name == 'session-lifecycle.yml':
        identity = '(printf "request.userInfo.username in [\'system:serviceaccount:%s:%s\', \'system:serviceaccount:%s:%s-runner\']" .Release.Namespace (include "deephive.fullWorkerName" .) .Release.Namespace .Release.Name)'
        text = text.replace('"spec" (dict "failurePolicy" "Fail")', '"spec" (dict "failurePolicy" "Fail" "matchConditions" (list (dict "name" "runner-identity" "expression" ' + identity + ')))')
    old = '$binding := lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicyBinding" "" ' + binding_name
    assert old in text
    text = text.replace(old, '$binding := dict "spec" (dict "policyName" ' + binding_name + ' "validationActions" (list "Deny"))')
    path.write_text(text)

# Model bindings retained from a previously running release for stop/cleanup tests.
for filename, expressions in {
    'full-worker.yml': ['lookup "rbac.authorization.k8s.io/v1" "RoleBinding" .Release.Namespace (include "deephive.fullWorkerName" .)'],
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

# A pre-rename live policy cannot authorize startup under the new account.
with tempfile.TemporaryDirectory(prefix='deephive-old-policy-') as tmp:
    old_policy_chart = Path(tmp) / 'deephive'
    shutil.copytree(fixture_chart, old_policy_chart)
    lifecycle = old_policy_chart / 'templates/session-lifecycle.yml'
    text = lifecycle.read_text().replace('"matchConditions" (list (dict "name" "runner-identity"', '"matchConditions" (list (dict "name" "old-identity"')
    lifecycle.write_text(text)
    config = copy.deepcopy(values)
    config['fullWorker']['runnerEnabled'] = True
    result = subprocess.run(['helm', 'template', 'review', str(old_policy_chart), '-n', 'dph-app', '-f', '-'], input=json.dumps(config), text=True, capture_output=True)
    assert result.returncode and 'Install admission for the renamed worker' in result.stderr, result.stderr
print('PASS old live admission identity cannot start renamed worker')

# Model the old stored value table used by Helm --reuse-values: no fullWorker
# defaults exist in that rendering context. Preserve legacy hooks and budget.
with tempfile.TemporaryDirectory(prefix='deephive-legacy-values-') as tmp:
    legacy_chart = Path(tmp) / 'deephive'
    shutil.copytree(chart, legacy_chart)
    defaults = yaml.safe_load((chart / 'values.yaml').read_text())
    legacy = defaults.pop('fullWorker')
    for suffix in ['Capacity', 'AdmissionCommand', 'InstallCommand', 'HandoffCommand', 'ScratchRoot']:
        legacy['ordinary' + suffix] = legacy.pop('lite' + suffix)
    defaults['fullEnvironment'] = legacy
    (legacy_chart / 'values.yaml').write_text(yaml.safe_dump(defaults))
    config = copy.deepcopy(values)
    configured = config.pop('fullWorker')
    for suffix in ['Capacity', 'AdmissionCommand', 'InstallCommand', 'HandoffCommand', 'ScratchRoot']:
        if 'lite' + suffix in configured:
            configured['ordinary' + suffix] = configured.pop('lite' + suffix)
    config['fullEnvironment'] = configured
    raw = subprocess.check_output(['helm', 'template', 'review', str(legacy_chart), '-n', 'dph-app', '-f', '-'], input=json.dumps(config), text=True)
    assert any(p and p['kind'] == 'Service' and p['metadata']['name'] == 'review-full-worker' for p in yaml.safe_load_all(raw))
    config['fullWorker'] = {'enabled': False}
    raw = subprocess.check_output(['helm', 'template', 'review', str(legacy_chart), '-n', 'dph-app', '-f', '-'], input=json.dumps(config), text=True)
    assert not any(p and p['kind'] == 'Service' and p['metadata']['name'] == 'review-full-worker' for p in yaml.safe_load_all(raw))
print('PASS reused legacy value table and explicit new disable override')

# Both old and new worker pods remain reachable through policy cutover.
network_config = copy.deepcopy(values)
network_config['VIRTUAL_HOST'] = 'deephive.example'
network_config['fullWorker']['observationEnabled'] = True
network_config['fullWorker']['publicOrigin'] = 'https://deephive.example'
network_config['fullWorker']['runnerSecretRevision'] = '1'
network_docs = render(config=network_config)
sessions = next(p for p in network_docs if p['kind'] == 'NetworkPolicy' and p['metadata']['name'] == 'review-sessions')
assert sessions['spec']['policyTypes'] == ['Ingress']
assert 'egress' not in sessions['spec']
for selector in [sessions['spec']['ingress'][0]['from'][0]['podSelector']]:
    assert selector['matchExpressions'] == [{'key': 'app', 'operator': 'In', 'values': ['review-full-worker', 'review-runner']}]
print('PASS legacy/current worker selectors retain callback and observation access')

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
assert not any(p['metadata']['name'].endswith('-session-egress') for p in after_docs)
assert 'proxyUrl' not in json.loads(item(after_docs, 'ConfigMap', '-full-worker')['data']['runner.json'])
print('PASS secret rotation, readiness, taints and direct session egress')

for name in ['true', 'null', '123']:
    changed['fullWorker'].update(pullSecret=name, runnerSecret=name, workspaceClaim=name)
    runner = item(render(config=changed), 'Deployment', '-full-worker')['spec']['template']['spec']
    assert runner['imagePullSecrets'][0]['name'] == name
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
    for suffix in ['-full-worker-control']:
        ingress = next(p for p in policies if p['metadata']['name'] == release + suffix)
        assert ingress['spec']['ingress'][0]['from'][0]['podSelector']['matchLabels']['app.kubernetes.io/instance'] == release
print('PASS release-specific session and runner selectors')

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
phase3.update(WORKSPACE_CLAIM_NAME='workspace-lite', WORKSPACE_ROOT='/workspace-root', WORKSPACE_ACCESS_MODES=['ReadWriteOnce'], NODE_SELECTOR_HOSTNAME='test-consumer', VIRTUAL_HOST='deephive.example')
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
duplicate_claim = copy.deepcopy(values)
duplicate_claim['WORKSPACE_CLAIM_NAME'] = duplicate_claim['fullWorker']['workspaceClaim']
rejected(duplicate_claim, 'distinct Lite and Full workspace claims')
legacy_claim = copy.deepcopy(values)
legacy_claim.update(LEGACY_WORKSPACE_RETAIN=True, WORKSPACE_CLAIM_NAME='lite-block')
legacy_claim['fullWorker']['workspaceClaim'] = 'review-workspace'
rejected(legacy_claim, 'Full workspace claim must differ from the retained legacy workspace claim')

# Offline helm template has no StorageClass lookup. Model the live API object
# while keeping the real guard and all other chart rendering intact.
with tempfile.TemporaryDirectory(prefix='deephive-storage-class-') as tmp:
    storage_chart = Path(tmp) / 'deephive'
    shutil.copytree(chart, storage_chart)
    template = storage_chart / 'templates/full-worker.yml'
    original = template.read_text()
    lookup = 'lookup "storage.k8s.io/v1" "StorageClass" "" $storageClassName'
    assert lookup in original
    for mode in ['Immediate', 'WaitForFirstConsumer']:
        template.write_text(original.replace(lookup, f'dict "volumeBindingMode" "{mode}"'))
        result = subprocess.run(
            ['helm', 'template', 'review', str(storage_chart), '-f', '-'],
            input=json.dumps(values), text=True, capture_output=True,
        )
        if mode == 'Immediate':
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode and 'Full workspace StorageClass must use Immediate binding' in result.stderr
print('PASS Full claims require Immediate binding and cannot reuse the retained legacy claim')

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
    rejected(missing, 'Session protocol must be 2, 3 or 4')
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
    missing[key] = phase3['fullWorker']['workspaceClaim'] if key.endswith('NAME') else '/different-root'
    rejected(missing, 'distinct Lite and Full workspace claims')
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
missing['WORKSPACE_ACCESS_MODES'] = ['ReadWriteMany']
rejected(missing, 'ReadWriteOnce')
missing = copy.deepcopy(phase3)
missing['NODE_SELECTOR_HOSTNAME'] = ''
rejected(missing, 'explicit consumer node')
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
changed['WORKSPACE_ROOT'] = '/workspace'
docs = render(config=changed)
consumer = next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'] == 'review')['spec']['template']['spec']
assert not any(v['name'] == 'lite-cache-probe' for v in consumer['volumes'])
assert next(e for e in consumer['containers'][0]['env'] if e['name'] == 'LITE_WORKER_CACHE_ROOT')['value'] == changed.get('WORKSPACE_ROOT', '')
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
seed['WORKSPACE_CLAIM_NAME'] = 'workspace-lite'
seed['NODE_SELECTOR_HOSTNAME'] = 'test-consumer'
seed['fullWorker'].update(sourceSeedExportEnabled=True, sourceSeedPath='/workspace-root/seeds/candidate')
docs = render(config=seed)
job = next(p for p in docs if p['kind'] == 'Job' and '-seed-' in p['metadata']['name'])
assert job['spec']['backoffLimit'] == 0
pod = job['spec']['template']['spec']
assert pod['automountServiceAccountToken'] is False
assert pod['containers'][0]['command'][-1].endswith('/export-source-seed.js')
assert 'envFrom' not in pod['containers'][0]
invalid = copy.deepcopy(seed)
invalid['WORKSPACE_ACCESS_MODES'] = ['ReadWriteMany']
rejected(invalid, 'Source seed export requires a ReadWriteOnce Lite workspace')
assert {'key': 'deephive-full', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'} in job['spec']['template']['spec']['tolerations']
for key in ['WORKSPACE_CLAIM_NAME', 'WORKSPACE_ROOT']:
    invalid = copy.deepcopy(seed)
    invalid[key] = seed['fullWorker']['workspaceClaim'] if key == 'WORKSPACE_CLAIM_NAME' else '/other'
    rejected(invalid, 'consumer root and a distinct Full workspace claim')
seed['fullWorker']['sourceSeedPath'] = '/outside'
rejected(seed, 'canonical workspace descendant')
print('PASS credential-free, explicit source seed export')

# The uninstall hook reads both Deployments even when the reader was disabled.
for release in ['review', 'other']:
    docs = render(release=release)
    role = item(docs, 'Role', '-session-drain-check')
    deployment_rule = next(r for r in role['rules'] if r['resources'] == ['deployments'])
    assert deployment_rule['verbs'] == ['get']
    assert set(deployment_rule['resourceNames']) == {release + '-full-worker', release + '-runner', release + '-source-reader'}
print('PASS uninstall hook can read both drained deployment identities')

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
rejected(invalid, 'JuiceFS source reader retired')
managed = copy.deepcopy(values)
managed['sourceReaderService'] = {'enabled': True}
rejected(managed, 'JuiceFS source reader retired')
stopped = copy.deepcopy(values)
stopped['fullWorker']['runnerEnabled'] = False
print('PASS retired JuiceFS broker cannot be reactivated')

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

# Both names must remain subject to admission while Helm replaces the worker.
policy = next(p for p in render() if p['kind'] == 'ValidatingAdmissionPolicy')
identity = next(c['expression'] for c in policy['spec']['matchConditions'] if c['name'] == 'runner-identity')
with tempfile.TemporaryDirectory(prefix='deephive-worker-identities-') as tmp:
    data = Path(tmp) / 'identities.json'
    data.write_text(json.dumps({'Expressions': [identity], 'Cases': [
        {'Name': username, 'Expect': expected, 'Activation': {'request': {'userInfo': {'username': username}}}}
        for username, expected in [
            ('system:serviceaccount:dph-app:review-full-worker', True),
            ('system:serviceaccount:dph-app:review-runner', True),
            ('system:serviceaccount:other:review-runner', False),
            ('system:serviceaccount:dph-app:other-runner', False),
        ]
    ]}))
    subprocess.run(['go', '-C', str(root), 'run', '.', str(data)], check=True)

# Offline lookups model an old deployment and orphan pods during disable.
# No policy is installed and no cluster is contacted.
for name in ['review-runner', 'review-full-worker']:
    for live in ['deployment', 'pod', 'drained']:
        with tempfile.TemporaryDirectory(prefix='deephive-worker-drain-') as tmp:
            fixture_chart = Path(tmp) / 'deephive'
            shutil.copytree(chart, fixture_chart)
            lifecycle = fixture_chart / 'templates/session-lifecycle.yml'
            text = lifecycle.read_text()
            lookup = 'lookup "apps/v1" "Deployment" $.Release.Namespace $runnerName'
            assert lookup in text
            replicas = 1 if live == 'deployment' else 0
            text = text.replace(lookup, f'dict "spec" (dict "replicas" (ternary {replicas} 0 (eq $runnerName "{name}"))) "status" (dict "replicas" 0)')
            lookup = 'lookup "v1" "Pod" .Release.Namespace ""'
            assert lookup in text
            pod = f'(dict "metadata" (dict "labels" (dict "app" "{name}")))' if live == 'pod' else ''
            text = text.replace(lookup, 'dict "items" (list ' + pod + ')')
            lifecycle.write_text(text)
            config = copy.deepcopy(values)
            config['fullWorker']['enabled'] = False
            result = subprocess.run(['helm', 'template', 'review', str(fixture_chart), '--is-upgrade', '-n', 'dph-app', '-f', '-'], input=json.dumps(config), text=True, capture_output=True)
            if live == 'drained':
                assert result.returncode == 0, result.stderr
            else:
                assert result.returncode != 0 and ('runner to zero' in result.stderr or 'Runner pods remain' in result.stderr), result.stderr
print('PASS legacy/current worker identity and disable-drain regression cases')

# Execute the rendered uninstall check against an in-memory API adapter. A live
# legacy deployment or orphan pod must fail just as a current worker does.
hook = item(render(), 'Job', '-session-drain-check')['spec']['template']['spec']['containers'][0]['args'][0]
body = hook[hook.index('const api ='):].replace('const api = await KubernetesApi.inCluster();', '')
for name in ['review-runner', 'review-full-worker']:
    for live in ['deployment', 'pod', 'drained']:
        stub = '''const api = { call: async (method, path) => {
          if (path.endsWith('/deployments/' + NAME)) return {spec:{replicas: LIVE === 'deployment' ? 1 : 0},status:{replicas:0}};
          if (path.includes('/deployments/')) return undefined;
          if (path.includes('/pods?') && decodeURIComponent(path).endsWith('app=' + NAME) && LIVE === 'pod') return {items:[{}]};
          return {items:[]};
        }};'''.replace('NAME', json.dumps(name)).replace('LIVE', json.dumps(live))
        result = subprocess.run(['node', '--input-type=module', '-e', stub + body], text=True, capture_output=True)
        if live == 'drained':
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0 and ('runner to zero' in result.stderr or 'Runner pods remain' in result.stderr), result.stderr
print('PASS rendered uninstall check blocks legacy/current deployments and orphan pods')

# Immutable active sessions still call the pre-rename DNS name. Both Services
# must resolve to the current controller, including long release names.
for release in ['review', 'other', 'r' * 53]:
    docs = render(release=release)
    worker = next(p for p in docs if p['kind'] == 'Deployment' and p['metadata']['name'].endswith(('-full-worker', '-full-work')))
    current = next(p for p in docs if p['kind'] == 'Service' and p['metadata']['name'] == worker['metadata']['name'])
    legacy = next(p for p in docs if p['kind'] == 'Service' and p['metadata']['name'] == release + '-runner')
    assert legacy['spec']['selector'] == current['spec']['selector'] == worker['spec']['selector']['matchLabels']
    assert legacy['spec']['ports'] == current['spec']['ports']
    assert {p['port']: p['targetPort'] for p in legacy['spec']['ports']} == {3001: 'control', 3002: 'observation'}
print('PASS legacy session callback Service resolves to the renamed controller')

# Project only nonsecret protocol metadata into the admission worker.
admission_checksums = []
for protocol in [3, 4]:
    config = copy.deepcopy(values)
    config['fullWorker']['sessionProtocol'] = protocol
    docs = render(config=config)
    template = consumer_template(docs)
    pod = template['spec']
    configmap = item(docs, 'ConfigMap', '-full-worker')
    assert json.loads(configmap['data']['admission.json']) == {'sessionProtocol': protocol}
    container = pod['containers'][0]
    assert next(e['value'] for e in container['env'] if e['name'] == 'FULL_WORKER_CONFIG') == '/full-admission/admission.json'
    assert next(v for v in pod['volumes'] if v['name'] == 'full-admission')['configMap']['items'] == [{'key': 'admission.json', 'path': 'admission.json'}]
    assert next(m for m in container['volumeMounts'] if m['name'] == 'full-admission')['readOnly'] is True
    admission_checksums.append(template['metadata']['annotations']['checksum/full-admission'])
assert admission_checksums[0] != admission_checksums[1]
print('PASS fresh admission receives the runner protocol without runner credentials')

# Protocol 4 starts on ordinary capacity, even when there are zero session nodes.
config = copy.deepcopy(values)
config['fullWorker'].update(sessionProtocol=4, cacheProbePath='', scratchProbePath='')
docs = render(config=config)
pod = item(docs, 'Deployment', '-full-worker')['spec']['template']['spec']
assert 'nodeName' not in pod and 'tolerations' not in pod
terms = pod['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms']
assert terms == [{'matchExpressions': [
    {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['test-consumer']},
    {'key': 'deephive-full', 'operator': 'NotIn', 'values': ['true']},
]}]
assert 'initContainers' not in pod  # Do not chown the already-owned Lite volume.
assert next(v for v in pod['volumes'] if v['name'] == 'workspace')['persistentVolumeClaim']['claimName'] == 'review-workspace'
runner_config = json.loads(item(docs, 'ConfigMap', '-full-worker')['data']['runner.json'])
assert runner_config['workspaceClaim'] == 'review-workspace'
assert runner_config['nodeName'] == 'test-execution'  # Drain the original node ledger.
legacy_pvc = next(p for p in docs if p['kind'] == 'PersistentVolumeClaim' and p['metadata']['name'] == config['fullWorker']['workspaceClaim'])
assert legacy_pvc['metadata']['annotations']['helm.sh/resource-policy'] == 'keep'
for overrides, error in [
    ({'NODE_SELECTOR_HOSTNAME': ''}, 'explicit Lite consumer node'),
    ({'WORKSPACE_ROOT': '/other'}, 'same canonical workspace root'),
    ({'WORKSPACE_ACCESS_MODES': ['ReadWriteMany']}, 'ReadWriteOnce Lite workspace'),
]:
    rejected(dict(config, **overrides), error)
assert {v['name'] for v in pod['volumes']}.isdisjoint({'cache-probe', 'scratch-probe'})
assert {m['name'] for m in pod['containers'][0]['volumeMounts']}.isdisjoint({'cache-probe', 'scratch-probe'})
role = next(p for p in docs if p['kind'] == 'ClusterRole' and any(r.get('resources') == ['nodes'] for r in p['rules']))
assert role['rules'] == [{'apiGroups': [''], 'resources': ['nodes'], 'verbs': ['get']}]
node_policy = next(p for p in docs if p['kind'] == 'ValidatingAdmissionPolicy' and p['metadata']['name'].startswith('dph-node-activation-'))
node_binding = next(p for p in docs if p['kind'] == 'ValidatingAdmissionPolicyBinding' and p['metadata']['name'] == node_policy['metadata']['name'])
assert node_policy['spec']['matchConstraints']['resourceRules'] == [
    {'apiGroups': [''], 'apiVersions': ['v1'], 'operations': ['UPDATE'], 'resources': ['nodes'], 'scope': 'Cluster'}]
assert node_policy['spec']['matchConditions'] == [
    {'name': 'runner-identity', 'expression': "request.userInfo.username == 'system:serviceaccount:dph-app:review-full-worker'"}]
assert node_binding['spec'] == {'policyName': node_policy['metadata']['name'], 'validationActions': ['Deny']}

# Feed exact rendered resources back as installed lookup fixtures. Compare
# against the old policy and a new policy whose generation is unobserved.
session_policy = next(p for p in docs if p['kind'] == 'ValidatingAdmissionPolicy' and p is not node_policy)
legacy_policy = next(p for p in render() if p['kind'] == 'ValidatingAdmissionPolicy')
for policy in [session_policy, legacy_policy, node_policy]:
    policy['metadata']['generation'] = 2
    policy['status'] = {'observedGeneration': 2, 'typeChecking': {}}


def enable_protocol4(installed_session, installed_node, installed_binding=node_binding):
    config['fullWorker']['runnerEnabled'] = True
    with tempfile.TemporaryDirectory(prefix='deephive-protocol4-enable-') as tmp:
        candidate = Path(tmp) / 'deephive'
        shutil.copytree(chart, candidate)
        lifecycle = candidate / 'templates/session-lifecycle.yml'
        source = lifecycle.read_text()
        source = source.replace('lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicy" "" $policyName',
                                '(fromJson ' + json.dumps(json.dumps(installed_session)) + ')')
        source = source.replace('lookup "admissionregistration.k8s.io/v1" "ValidatingAdmissionPolicyBinding" "" $policyName',
                                '(dict "spec" (dict "policyName" $policyName "validationActions" (list "Deny")))')
        lifecycle.write_text(source)
        helpers = candidate / 'templates/_full-worker.tpl'
        source = helpers.read_text()
        for kind, installed in [('ValidatingAdmissionPolicy', installed_node),
                                ('ValidatingAdmissionPolicyBinding', installed_binding)]:
            lookup = f'lookup "admissionregistration.k8s.io/v1" "{kind}" "" $name'
            assert lookup in source
            source = source.replace(lookup, '(fromJson ' + json.dumps(json.dumps(installed)) + ')')
        helpers.write_text(source)
        return subprocess.run(['helm', 'template', 'review', str(candidate), '-n', 'dph-app', '-f', '-'],
                              input=json.dumps(config), text=True, capture_output=True)


result = enable_protocol4(legacy_policy, node_policy)
assert result.returncode and 'protocol 4 session admission revision' in result.stderr, result.stderr
pending_session = copy.deepcopy(session_policy)
pending_session['status']['observedGeneration'] = 1
result = enable_protocol4(pending_session, node_policy)
assert result.returncode and 'observe the installed generation' in result.stderr, result.stderr
result = enable_protocol4(session_policy, {})
assert result.returncode and 'Node admission boundary' in result.stderr, result.stderr
pending_node = copy.deepcopy(node_policy)
pending_node['status'].pop('typeChecking')
result = enable_protocol4(session_policy, pending_node)
assert result.returncode and 'Node admission boundary' in result.stderr, result.stderr
narrowed_binding = copy.deepcopy(node_binding)
narrowed_binding['spec']['matchResources'] = {'objectSelector': {'matchLabels': {'allow': 'false'}}}
result = enable_protocol4(session_policy, node_policy, narrowed_binding)
assert result.returncode and 'Node admission boundary' in result.stderr, result.stderr
result = enable_protocol4(session_policy, node_policy)
assert result.returncode == 0, result.stderr
enabled = [p for p in yaml.safe_load_all(result.stdout) if p]
assert item(enabled, 'Deployment', '-full-worker')['spec']['replicas'] == 1
role = next(p for p in enabled if p['kind'] == 'ClusterRole' and p['metadata']['name'] == role['metadata']['name'])
assert [r['verbs'] for r in role['rules']] == [['get'], ['patch']]
print('PASS protocol 4 cold-start placement, Node admission boundary and protection-first enablement')
