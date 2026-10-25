"""Render temporary staging-only resources; never contacts Kubernetes."""
import argparse
import hashlib
import json
import pathlib
import re

p = argparse.ArgumentParser()
p.add_argument('kind', choices=['job', 'config'])
p.add_argument('operation')
p.add_argument('scope', choices=['lite', 'canary'])
p.add_argument('--job-uid')
a = p.parse_args()
assert re.fullmatch(r'[a-z0-9][a-z0-9-]{2,31}', a.operation)
name = 'deephive-queue-window-' + a.operation
source = pathlib.Path(__file__).with_name('queue-window.mjs').read_text()
digest = hashlib.sha256(source.encode()).hexdigest()
labels = {'deephive-rollout-operation': a.operation}
meta = {'name': name, 'namespace': 'dph-app', 'labels': labels}
if a.kind == 'config':
    assert a.job_uid and re.fullmatch(r'[a-f0-9-]{36}', a.job_uid)
    meta['name'] += '-code'
    meta['ownerReferences'] = [{'apiVersion': 'batch/v1', 'kind': 'Job', 'name': name,
                                'uid': a.job_uid, 'controller': True, 'blockOwnerDeletion': False}]
    out = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta,
           'immutable': True, 'data': {'queue-window.mjs': source}}
else:
    env = [{'name': key, 'valueFrom': {'secretKeyRef': {'name': 'deephive-full-runner', 'key': key}}}
           for key in ['REDIS_URL', 'REDIS_NAME', 'REDIS_HOSTNAME']]
    env += [{'name': key, 'valueFrom': {'fieldRef': {'fieldPath': path}}}
            for key, path in [('POD_UID', 'metadata.uid'), ('POD_NAMESPACE', 'metadata.namespace')]]
    env += [{'name': 'EXPECTED_SCRIPT_SHA256', 'value': digest}]
    pod = {
        'serviceAccountName': 'deephive-full-worker', 'automountServiceAccountToken': False,
        'imagePullSecrets': [{'name': 'deephive-full-worker-pull'}],
        'restartPolicy': 'OnFailure', 'terminationGracePeriodSeconds': 10,
        'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 1000,
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{
            'name': 'resumer',
            'image': 'ghcr.io/elegantthemes/deephive-runner@sha256:7a43b409e33444be21854822a176980375d24143f44d5155ecace00889c73e27',
            'command': ['node', '/operation/queue-window.mjs', 'watch', a.operation, a.scope],
            'env': env,
            'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                'capabilities': {'drop': ['ALL']}},
            'resources': {'requests': {'cpu': '10m', 'memory': '64Mi'},
                          'limits': {'cpu': '100m', 'memory': '256Mi'}},
            'volumeMounts': [{'name': 'code', 'mountPath': '/operation', 'readOnly': True}],
        }],
        'volumes': [{'name': 'code', 'configMap': {'name': name + '-code', 'defaultMode': 292}}],
    }
    out = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': meta,
           'spec': {'parallelism': 1, 'completions': 1, 'backoffLimit': 100,
                    'activeDeadlineSeconds': 28800, 'ttlSecondsAfterFinished': 600,
                    'template': {'metadata': {'labels': labels}, 'spec': pod}}}
print(json.dumps(out, indent=2))
