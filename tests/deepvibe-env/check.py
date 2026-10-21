"""Verify optional DeepVibe ENV_FILE transport and rollout checksums offline.

Requires Helm and PyYAML. Contains synthetic credentials only.
"""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import yaml

chart = Path(__file__).resolve().parents[2] / 'charts/deephive'

def render(env_file):
    values = {'ENV_FILE': env_file, 'GITHUB_TOKEN': 'fixture-only', 'INSTALL_PATH': '/srv/deephive',
              'REPLICAS': 1, 'VIRTUAL_HOST': 'deephive.example.test', 'MEMORY_LIMIT': '4Gi',
              'DEEPHIVE_IMAGE': 'example/deephive:fixture', 'DEEPHIVE_VERSION': 'fixture',
              'WORKSPACE_ROOT': '/workspace', 'DEEPHIVE_REPO_URL': 'https://example.test/repo'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'values.yaml'
        path.write_text(yaml.safe_dump(values))
        result = subprocess.run(['helm', 'template', 'deephive', str(chart), '--namespace', 'dph-app', '-f', str(path)], check=True, text=True, capture_output=True)
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    secret = next(doc for doc in docs if doc['kind'] == 'Secret' and doc['metadata']['name'] == 'secrets')
    assert secret['stringData']['.env'] == env_file
    expected = hashlib.sha256(env_file.encode()).hexdigest()
    checksums = {}
    for name in ['deephive', 'deephive-intake']:
        deployment = next(doc for doc in docs if doc['kind'] == 'Deployment' and doc['metadata']['name'] == name)
        template = deployment['spec']['template']
        checksums[name] = template['metadata']['annotations']['checksum/env-file']
        assert checksums[name] == expected
        volumes = template['spec']['volumes']
        assert any(v['name'] == 'config' and v.get('secret', {}).get('secretName') == 'secrets' for v in volumes)
        container = template['spec']['containers'][0]
        assert any(m['name'] == 'config' and m['mountPath'] == '/config' and m['readOnly'] for m in container['volumeMounts'])
        assert not any(e['name'].startswith(('AWS_', 'DEEPVIBE_')) for e in container['env'])
    return checksums

base = "ADMIN_API_KEY='fixture-only'"
media = base + "\nDEEPVIBE_MEDIA_BUCKET='fixture-media'\nAWS_REGION='us-east-1'\nAWS_ACCESS_KEY_ID='FIXTUREKEY'\nAWS_SECRET_ACCESS_KEY='fixture-secret'\nDEEPVIBE_WP_SITE_URL='https://wp.example.test/'\nDEEPVIBE_WP_USERNAME='fixture-reader'\nDEEPVIBE_WP_APPLICATION_PASSWORD='fixture password'"
first, configured, rotated = render(base), render(media), render(media.replace('fixture-secret', 'rotated-fixture-secret'))
for name in first:
    assert first[name] != configured[name] != rotated[name]
print('PASS: unconfigured and configured ENV_FILE reach the Secret unchanged; both deployments mount it read-only and roll on connection/credential changes.')
