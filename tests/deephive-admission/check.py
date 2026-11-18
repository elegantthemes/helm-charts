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

consumer_ref = subprocess.run([
    "helm", "template", "review", str(root.parent.parent / "charts/deephive"),
    "-n", "dph-app", "-f", str(root / "values.json"),
    "--set", "fullWorker.githubSecretRef.name=secrets",
    "--set", "fullWorker.githubSecretRef.key=GITHUB_TOKEN",
], capture_output=True, text=True)
assert consumer_ref.returncode != 0
assert "must not select the consumer Secret" in consumer_ref.stderr

# Protocol 4 keeps the first ordinary init mount-free and prevents hooks and
# restartable sidecars from bypassing activation. This is offline CEL evidence.
dedicated_values = json.loads((root / 'values.json').read_text())
dedicated_values['fullWorker']['sessionProtocol'] = 4
with tempfile.TemporaryDirectory(prefix='deephive-dedicated-policy-') as temp:
    config = Path(temp) / 'values.json'
    config.write_text(json.dumps(dedicated_values))
    rendered = subprocess.check_output([
        'helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'),
        '-n', 'dph-app', '-f', str(config)], text=True)
    rendered_node_policy = rendered
    dedicated_policy = next(p for p in yaml.safe_load_all(rendered)
                            if p and p['kind'] == 'ValidatingAdmissionPolicy'
                            and p['spec']['matchConstraints']['resourceRules'][0]['resources'] == ['pods'])
    original = json.loads((root / 'pod-protocol4.json').read_text())
    cases = []
    case('protocol 4 gate first', True)
    case('protocol 4 rejects legacy protocol annotation', False,
         lambda p: p['metadata']['annotations'].update({'deephive/protocol': '3'}))
    case('protocol 4 rejects missing protocol annotation', False,
         lambda p: p['metadata']['annotations'].pop('deephive/protocol'))
    case('protocol 4 lets the runner delete a legacy session', True,
         lambda p: p['metadata']['annotations'].update({'deephive/protocol': '3'}),
         operation='DELETE')
    case('protocol 4 shared source rejected', False, lambda p: p['spec']['volumes'][0].update(persistentVolumeClaim={'claimName': 'fixture'}))
    case('protocol 4 source subpath rejected', False, lambda p: p['spec']['containers'][0]['volumeMounts'][0].update(subPath='tasks/old'))
    case('protocol 4 unbounded source rejected', False, lambda p: p['spec']['volumes'][0].update(emptyDir={}))
    case('gate explicit empty args', True, lambda p: p['spec']['initContainers'][0].update(args=[]))
    case('gate Node eval override', False, lambda p: p['spec']['initContainers'][0].update(args=['--eval', 'process.exit(0)']))
    case('gate arbitrary argument', False, lambda p: p['spec']['initContainers'][0].update(args=['ignored']))

    def term(p):
        return p['spec']['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]

    def selector(p):
        return term(p)['labelSelector']

    case('anti-affinity namespace selector empty fields', True,
         lambda p: term(p).update(namespaceSelector={'matchLabels': {}, 'matchExpressions': []}))
    case('anti-affinity namespace selector with label', False,
         lambda p: term(p).update(namespaceSelector={'matchLabels': {'team': 'app'}}))
    case('anti-affinity namespace selector with expression', False,
         lambda p: term(p).update(namespaceSelector={'matchExpressions': [{'key': 'team', 'operator': 'Exists'}]}))
    for key in ['matchLabelKeys', 'mismatchLabelKeys']:
        case(f'anti-affinity {key} narrowing', False,
             lambda p, key=key: term(p).update({key: ['deephive/session']}))

    case('anti-affinity empty expressions', True, lambda p: selector(p).update(matchExpressions=[]))
    case('anti-affinity contradictory expression', False, lambda p: selector(p).update(matchExpressions=[{
        'key': 'app.kubernetes.io/name', 'operator': 'NotIn', 'values': ['deephive-session']}]))
    case('anti-affinity narrowing expression', False, lambda p: selector(p).update(matchExpressions=[{
        'key': 'deephive/session', 'operator': 'In', 'values': [p['metadata']['name']]}]))
    case('anti-affinity narrowing label', False, lambda p: selector(p)['matchLabels'].update({
        'deephive/session': p['metadata']['name']}))
    case('anti-affinity missing required label', False, lambda p: selector(p).update(matchLabels={}))
    case('protocol 4 harmless pod metadata', True, lambda p: p['metadata']['labels'].update({'example.internal/notes': 'demo'}))

    case('pre-init volume ownership mutation', False, lambda p: p['spec']['securityContext'].update(fsGroup=1000))
    case('fixed worker bypass', False, lambda p: p['spec'].update(nodeName='worker'))
    case('gate after writer', False, lambda p: p['spec']['initContainers'].reverse())
    case('gate endpoint bypass', False, lambda p: next(e for e in p['spec']['initContainers'][0]['env'] if e['name'] == 'SESSION_RUNNER_URL').update(value='http://fake-claim'))
    case('gate command bypass', False, lambda p: p['spec']['initContainers'][0].update(command=['true']))
    case('gate writable mount', False, lambda p: p['spec']['initContainers'][0].update(volumeMounts=[{'name': 'scratch', 'mountPath': '/scratch'}]))
    case('restartable init sidecar', False, lambda p: p['spec']['initContainers'][1].update(restartPolicy='Always'))
    case('startup hook', False, lambda p: p['spec']['containers'][1].update(lifecycle={'postStart': {'exec': {'command': ['true']}}}))
    case('missing dedicated taint', False, lambda p: p['spec'].update(tolerations=[]))
    case('namespace-limited anti-affinity', False, lambda p: p['spec']['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0].pop('namespaceSelector'))
    case('missing session anti-affinity', False, lambda p: p['spec'].pop('affinity'))
    fixture = Path(temp) / 'cases.json'
    fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in dedicated_policy['spec']['validations']], 'Cases': cases}))
    subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)
print('PASS protocol 4 activation ordering and bypass protection')

# Actual legacy Pods remain admissible under their compatible protocol policy.
for protocol in [2, 3]:
    rendered = subprocess.check_output([
        'helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'),
        '-n', 'dph-app', '-f', str(root / 'values.json'),
        '--set', 'fullWorker.sessionProtocol=' + str(protocol)], text=True)
    policy = next(p for p in yaml.safe_load_all(rendered) if p and p['kind'] == 'ValidatingAdmissionPolicy')
    original = json.loads((root / f'pod-protocol{protocol}.json').read_text())
    cases = []
    case(f'actual legacy protocol {protocol}', True)
    case(f'legacy {protocol} rejects protocol 4 without activation', False,
         lambda p: p['metadata']['annotations'].update({'deephive/protocol': '4'}))
    case(f'legacy {protocol} controller secret forbidden', False, lambda p: p['spec']['containers'][0].update(envFrom=[{'secretRef': {'name': 'secrets'}}]))
    with tempfile.TemporaryDirectory(prefix='deephive-legacy-pod-') as temp:
        fixture = Path(temp) / 'cases.json'
        fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in policy['spec']['validations']], 'Cases': cases}))
        subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)
print('PASS actual legacy protocol 2/3 manifests')


# Evaluate Node mutations against the rendered admission boundary.
node_policy = next(p for p in yaml.safe_load_all(rendered_node_policy)
                   if p and p['kind'] == 'ValidatingAdmissionPolicy'
                   and p['metadata']['name'].startswith('dph-node-activation-'))
before = {
    'metadata': {
        'name': 'k8s-cluster-stage-deephive-burst-fixture',
        'labels': {'deephive-full': 'true', 'gha.etdevs.com/capacity': 'burst',
                   'gha.etdevs.com/managed-by': 'gha-runner-autoscaler'},
        'annotations': {'gha.etdevs.com/linode-id': '123', 'gha.etdevs.com/state': 'ready'},
    },
    'spec': {'taints': [{'key': 'deephive-full', 'value': 'true', 'effect': 'NoSchedule'}]},
}
cases = []


def node_case(name, expected, change, initial=before):
    after = copy.deepcopy(initial)
    change(after)
    cases.append({'Name': name, 'Expect': expected, 'Activation': {
        'oldObject': initial, 'object': after,
        'variables': {'before': initial['metadata']['annotations'], 'after': after['metadata']['annotations']},
    }})


def claim(node):
    node['metadata']['annotations']['deephive/activation'] = 'fixture claim'


node_case('set activation on dedicated Node', True, claim)
for taints in (None, [], [{'key': 'deephive-full', 'value': 'false', 'effect': 'NoSchedule'}],
               [{'key': 'deephive-full', 'value': 'true', 'effect': 'PreferNoSchedule'}]):
    untainted = copy.deepcopy(before)
    if taints is None:
        del untainted['spec']['taints']
    else:
        untainted['spec']['taints'] = taints
    node_case(f'Reject activation without exact dedicated taint: {taints}', False, claim, untainted)
claim(untainted)
node_case('clear activation after the dedicated taint was changed', True,
          lambda n: n['metadata']['annotations'].pop('deephive/activation'), untainted)
claimed = copy.deepcopy(before)
claim(claimed)
node_case('clear activation on dedicated Node', True,
          lambda n: n['metadata']['annotations'].pop('deephive/activation'), claimed)
for key in before['metadata']['labels']:
    unrelated = copy.deepcopy(before)
    del unrelated['metadata']['labels'][key]
    node_case(f'Node without {key} identity', False, claim, unrelated)
unrelated = copy.deepcopy(before)
unrelated['metadata']['name'] = 'another-pool'
node_case('claim on unrelated Node', False, claim, unrelated)
node_case('strip a Node taint', False, lambda n: n['spec'].update(taints=[]))
node_case('cordon an eligible Node', False, lambda n: n['spec'].update(unschedulable=True))
node_case('alter a Node label', False, lambda n: n['metadata']['labels'].update({'example.test/label': 'true'}))
node_case('alter retirement state', False, lambda n: n['metadata']['annotations'].update({'gha.etdevs.com/state': 'retiring'}))
node_case('remove provider identity', False, lambda n: n['metadata']['annotations'].pop('gha.etdevs.com/linode-id'))
node_case('add a Node annotation', False, lambda n: n['metadata']['annotations'].update({'example.test/annotation': 'value'}))
node_case('add a Node finalizer', False, lambda n: n['metadata'].update(finalizers=['example.test/hold']))
node_case('assign a Node owner', False, lambda n: n['metadata'].update(ownerReferences=[{'name': 'other'}]))
with tempfile.TemporaryDirectory(prefix='deephive-node-admission-') as temp:
    fixture = Path(temp) / 'cases.json'
    fixture.write_text(json.dumps({'Expressions': [v['expression'] for v in node_policy['spec']['validations']], 'Cases': cases}))
    subprocess.run(['go', '-C', str(root), 'run', '.', str(fixture)], check=True)
