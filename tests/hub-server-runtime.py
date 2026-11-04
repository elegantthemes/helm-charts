"""Offline chart contract tests. All credentials are synthetic."""
import base64
import copy
import os
from pathlib import Path
import subprocess
import tempfile
import shutil
import unittest
import yaml

CHART = Path(__file__).resolve().parents[1] / 'charts/hub-server'
HELM = os.environ.get('HELM', 'helm')
SYNTHETIC_KEY = 'base64:' + base64.b64encode(bytes(range(32))).decode()
BASE = dict(APP_KEY=SYNTHETIC_KEY, HUB_SERVER_ENV='staging',
            HUB_SERVER_PATH='/srv/hub-server', WORKSPACE_HOST_PATH='/srv/hub-server', HUB_SERVER_IMAGE='example.invalid/hub:test',
            HUB_SERVER_WORKERS=2, DIVI_HUB_PRIVATE_KEY_64='synthetic-private-key',
            RECONCILE_RUNTIME_CONFIG=True, ADOPT_STAGING_RUNTIME_INIT=True,
            HUB_SERVER_EXTRA_ENV={'LOG_LEVEL': 'debug', 'HORIZON_ALLOWED_IPS': '203.0.113.0/24',
                                 'DIVI_METRICS_ENDPOINT_TOKEN': 'synthetic-metrics'})

EXTRA_NAMES = [
    'APP_PREVIOUS_KEYS', 'APP_DEBUG', 'OUTBOUND_ENFORCE_RETURNED_LOGIN_URL_HOST',
    'OUTBOUND_URL_ALLOWED_HOSTNAMES', 'OUTBOUND_DNS_CACHE_TTL_SECONDS',
    'JWT_VERIFICATION_BYPASS_TTL_SECONDS', 'QUEUE_LEGACY_DEDUPLICATION_UNTIL',
    'ACL_CLEANUP_DRY_RUN', 'DIVI_HUB_API_REQUEST_TIMEOUT_SECONDS',
    'DIVI_HUB_SUSPENDED_QUEUE_TIMEOUT_SECONDS',
]
BASE['HUB_SERVER_EXTRA_ENV'].update(dict.fromkeys(EXTRA_NAMES, 'synthetic'))
BASE['HUB_SERVER_EXTRA_ENV']['APP_PREVIOUS_KEYS'] = ''


def render(values):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as handle:
        yaml.safe_dump(values, handle)
        handle.flush()
        return subprocess.run([HELM, 'template', 'hub-server', str(CHART),
                               '--namespace', 'dd-app', '-f', handle.name],
                              capture_output=True, text=True)


def resources(values):
    result = render(values)
    if result.returncode:
        raise AssertionError(result.stderr)
    return {item['kind']: item for item in yaml.safe_load_all(result.stdout) if item}


class RuntimeContract(unittest.TestCase):
    def test_canonical_secret(self):
        data = resources(BASE)['Secret']['stringData']
        lines = data['.env'].splitlines()
        keys = [line.split('=', 1)[0] for line in lines]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("APP_KEY='" + SYNTHETIC_KEY + "'", lines)
        self.assertIn("LOG_LEVEL='debug'", lines)
        self.assertIn("HORIZON_ALLOWED_IPS='203.0.113.0/24'", lines)
        self.assertEqual(data['DIVI_METRICS_ENDPOINT_TOKEN'], 'synthetic-metrics')
        self.assertNotIn('HORIZON_PREFIX', keys)
        self.assertTrue(set(EXTRA_NAMES).issubset(keys))
        self.assertIn("APP_PREVIOUS_KEYS=''", lines)

    def test_rollout_and_adoption(self):
        dep = resources(BASE)['Deployment']
        self.assertEqual(dep['spec']['strategy']['rollingUpdate'],
                         {'maxSurge': 0, 'maxUnavailable': 1})
        pod = dep['spec']['template']['spec']
        init, bridge = pod['initContainers']
        self.assertIn('config:cache', init['args'][0])
        self.assertEqual(bridge['name'], 'staging-runtime-config')
        self.assertEqual(bridge['args'], ['true'])
        self.assertNotIn('volumeMounts', bridge)
        self.assertIn('worker-1', [c['name'] for c in pod['containers']])
        final = copy.deepcopy(BASE)
        final['ADOPT_STAGING_RUNTIME_INIT'] = False
        self.assertEqual(len(resources(final)['Deployment']['spec']['template']['spec']['initContainers']), 1)

    def test_checksum_changes_for_runtime_values(self):
        def checksum(values):
            return resources(values)['Deployment']['spec']['template']['metadata']['annotations']['checksum/config']
        changed = copy.deepcopy(BASE)
        changed['HUB_SERVER_EXTRA_ENV']['HORIZON_ALLOWED_IPS'] = '198.51.100.0/24'
        self.assertNotEqual(checksum(BASE), checksum(changed))
        changed = copy.deepcopy(BASE)
        changed['APP_KEY'] = 'base64:' + base64.b64encode(bytes(range(1, 33))).decode()
        self.assertNotEqual(checksum(BASE), checksum(changed))

    def test_fail_closed(self):
        for overrides in ({'APP_KEY': 'x'}, {'HORIZON_PREFIX': 'x'}, {'invalid-key': 'x'},
                          {'API_EXPECTED_REQUEST_SECRET': "can't"}, {'API_EXPECTED_REQUEST_SECRET': 'first\nsecond'}, {'API_EXPECTED_REQUEST_SECRET': 'first\rsecond'}):
            with self.subTest(overrides=overrides):
                values = copy.deepcopy(BASE)
                values['HUB_SERVER_EXTRA_ENV'] = overrides
                self.assertNotEqual(render(values).returncode, 0)
        values = copy.deepcopy(BASE)
        del values['APP_KEY']
        self.assertNotEqual(render(values).returncode, 0)

    def test_control_and_metadata_overrides_rejected(self):
        for name in ['HUB_SERVER_PATH', 'HUB_SERVER_REPO_URL', 'IMAGE_VERSION',
                     'APP_ENV', 'APP_URL', 'VIRTUAL_HOST', 'PATH', 'BASH_ENV',
                     'ENV', 'IFS', 'SHELLOPTS', 'LD_PRELOAD', 'GITHUB_TOKEN',
                     'UNREVIEWED_APPLICATION_FLAG']:
            with self.subTest(name=name):
                values = copy.deepcopy(BASE)
                values['HUB_SERVER_EXTRA_ENV'] = {name: 'synthetic'}
                self.assertNotEqual(render(values).returncode, 0)

    def test_key_format_and_exact_preservation(self):
        for key in ["synthetic'key", 'base64:short', ' ' + SYNTHETIC_KEY,
                    SYNTHETIC_KEY + '\n', 'base64:' + 'A' * 42 + 'B=',
                    'base64:' + base64.b64encode(bytes(16)).decode()]:
            with self.subTest(key=key):
                values = copy.deepcopy(BASE)
                values['APP_KEY'] = key
                self.assertNotEqual(render(values).returncode, 0)
        # Every valid byte sequence is accepted without decoding/re-encoding it.
        for payload in [bytes(32), bytes([255]) * 32, bytes(range(32))]:
            values = copy.deepcopy(BASE)
            key = 'base64:' + base64.b64encode(payload).decode()
            values['APP_KEY'] = key
            self.assertIn("APP_KEY='" + key + "'", resources(values)['Secret']['stringData']['.env'])


    def test_prepare_preserves_entire_baseline_deployment(self):
        values = copy.deepcopy(BASE)
        values.update(RECONCILE_RUNTIME_CONFIG=False, ADOPT_STAGING_RUNTIME_INIT=False)
        prepared = resources(values)['Deployment']
        with tempfile.TemporaryDirectory() as directory:
            baseline = Path(directory) / 'chart'
            shutil.copytree(CHART, baseline)
            original = subprocess.check_output(
                ['git', 'show', 'a4991f3121b9a17f8bf502e90bb403b0f3249968:charts/hub-server/templates/hub-server.yml'],
                cwd=CHART, text=True)
            (baseline / 'templates/hub-server.yml').write_text(original)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as handle:
                yaml.safe_dump(values, handle)
                handle.flush()
                output = subprocess.check_output([HELM, 'template', 'hub-server', str(baseline),
                                                  '--namespace', 'dd-app', '-f', handle.name], text=True)
                old = next(item for item in yaml.safe_load_all(output) if item and item['kind'] == 'Deployment')
        self.assertEqual(prepared, old)

    def test_nonstring_extra_values_fail(self):
        for value in [False, 12, None, ['x']]:
            values = copy.deepcopy(BASE)
            values['HUB_SERVER_EXTRA_ENV']['APP_DEBUG'] = value
            self.assertNotEqual(render(values).returncode, 0)



    def test_existing_mode_is_available(self):
        values = copy.deepcopy(BASE)
        values.update(RECONCILE_RUNTIME_CONFIG=False, ADOPT_STAGING_RUNTIME_INIT=False)
        init = resources(values)['Deployment']['spec']['template']['spec']['initContainers']
        self.assertEqual(len(init), 1)
        self.assertEqual(init[0]['command'], ['/etc/cont-init.d/init'])


if __name__ == '__main__':
    unittest.main()
