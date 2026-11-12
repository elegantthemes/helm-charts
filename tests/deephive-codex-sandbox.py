"""The host AppArmor profile applies only to the shared coding worker."""
from pathlib import Path
import json
import subprocess
import yaml
chart = Path(__file__).resolve().parents[1] / 'charts/deephive'
for profile in ['', 'deephive-codex-sandbox']:
    values = {'ENV_FILE': 'SYNTHETIC=true', 'MYSQL_ENABLED': True,
              'CODEX_SANDBOX_APPARMOR_PROFILE': profile}
    raw = subprocess.check_output(['helm', 'template', 'canary', str(chart), '-n', 'dph-app', '-f', '-'], input=json.dumps(values).encode())
    docs = [d for d in yaml.safe_load_all(raw) if d]
    found = 0
    for doc in docs:
        if doc['kind'] != 'Deployment':
            continue
        spec = doc['spec']['template']['spec']
        for container in spec['containers']:
            actual = container.get('securityContext', {}).get('appArmorProfile')
            if doc['metadata']['name'] == 'canary' and container['name'] == 'canary':
                found += 1
                assert actual == ({'type': 'Localhost', 'localhostProfile': profile} if profile else None)
                if profile:
                    assert 'SYS_ADMIN' in container['securityContext']['capabilities']['drop']
                assert not container.get('securityContext', {}).get('privileged')
                assert 'SYS_ADMIN' not in container.get('securityContext', {}).get('capabilities', {}).get('add', [])
            else:
                assert actual is None, (doc['metadata']['name'], container['name'])
    assert found == 1
print('PASS configured profile applies only to worker; default, intake and MySQL unchanged; no added capabilities')
