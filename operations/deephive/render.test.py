"""Regression checks for temporary recovery lifecycle and valid identities."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

RENDER = Path(__file__).with_name('render.py')


class RecoveryResources(unittest.TestCase):
    def render(self, operation):
        return subprocess.run([sys.executable, str(RENDER), 'job', operation, 'canary'],
                              capture_output=True, text=True)

    def test_recovery_has_no_unconditional_deadline(self):
        result = self.render('52548-test')
        self.assertEqual(result.returncode, 0, result.stderr)
        job = json.loads(result.stdout)
        self.assertNotIn('activeDeadlineSeconds', job['spec'])
        self.assertEqual(job['spec']['backoffLimit'], 2147483647)
        self.assertEqual(job['spec']['template']['spec']['restartPolicy'], 'OnFailure')
        self.assertEqual(job['spec']['ttlSecondsAfterFinished'], 600)

    def test_reject_identifiers_kubernetes_would_reject(self):
        for operation in ['abc-', '-abc', 'ab', 'a' * 33]:
            with self.subTest(operation=operation):
                self.assertNotEqual(self.render(operation).returncode, 0)
        for operation in ['abc', '52548-test', 'a' * 32]:
            with self.subTest(operation=operation):
                self.assertEqual(self.render(operation).returncode, 0)


if __name__ == '__main__':
    unittest.main()
