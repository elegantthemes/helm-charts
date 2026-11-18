"""Check actual generated Pod contracts without Go dependencies or cluster access."""
import json
from pathlib import Path
import subprocess
import yaml
root = Path(__file__).resolve().parent
for protocol in [2, 3, 4]:
    pod = json.loads((root / f'pod-protocol{protocol}.json').read_text())
    spec = pod['spec']
    assert pod['metadata']['annotations']['deephive/protocol'] == str(protocol)
    assert [c['name'] for c in spec['containers']] == ['session', 'database']
    assert spec['containers'][1]['command'] # No image ENTRYPOINT before ordinary init completion.
    all_containers = spec['containers'] + spec['initContainers']
    assert all('lifecycle' not in c and 'restartPolicy' not in c and 'envFrom' not in c for c in all_containers)
    secrets = {e['valueFrom']['secretKeyRef']['name'] for c in all_containers for e in c.get('env', []) if 'secretKeyRef' in e.get('valueFrom', {})}
    assert secrets == {'agent', 'integration'}
    if protocol == 4:
        assert [c['name'] for c in spec['initContainers']] == ['activation-wait', 'local-mounts']
        gate = spec['initContainers'][0]
        assert 'volumeMounts' not in gate
        assert gate['command'] == ['node', '-e', (root.parent.parent / 'charts/deephive/files/activation-wait.js').read_text()]
        assert 'nodeName' not in spec and 'fsGroup' not in spec['securityContext']
        assert all('persistentVolumeClaim' not in v for v in spec['volumes'])
        assert spec['nodeSelector'] == {'deephive-full': 'true'}
        assert spec['tolerations'] == [{'key': 'deephive-full', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'}]
        term = spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'][0]
        assert term == {'labelSelector': {'matchLabels': {'app.kubernetes.io/name': 'deephive-session'}}, 'topologyKey': 'kubernetes.io/hostname', 'namespaceSelector': {}}
    else:
        assert [c['name'] for c in spec['initContainers']] == ['local-mounts']
        assert spec['nodeName'] == 'test-execution'
        assert any('persistentVolumeClaim' in v for v in spec['volumes'])
    raw = subprocess.check_output(['helm', 'template', 'review', str(root.parent.parent / 'charts/deephive'), '-n', 'dph-app', '-f', str(root / 'values.json'), '--set', f'fullWorker.sessionProtocol={protocol}'], text=True)
    docs = [d for d in yaml.safe_load_all(raw) if d]
    assert any(d['kind'] == 'ValidatingAdmissionPolicy' for d in docs)
    assert any(d['kind'] == 'ValidatingAdmissionPolicyBinding' for d in docs)
    assert not any(d['kind'] == 'RoleBinding' and d['metadata']['name'] == 'review-full-worker' for d in docs)
print('PASS actual protocol 2/3/4 Pod shapes, gate source, isolation and admission-before-runner render')
