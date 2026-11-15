"""Real Linux session lifecycle; no microphone, hardware, or cloud service."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / 'device/process_owner'


class ProcessOwnerWiringTest(unittest.TestCase):
    def test_missing_helper_fails_closed_for_start_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CONFIG_FILE=str(Path(tmp) / 'missing-config'),
                       NATIVE_PROCESS_OWNER=str(Path(tmp) / 'missing-helper'),
                       PID_FILE=str(Path(tmp) / 'client.pid'),
                       LOG_FILE=str(Path(tmp) / 'client.log'))
            env.pop('NATIVE_PROCESS_SUPERVISED', None)
            for action in ([], ['stop']):
                result = subprocess.run(['sh', str(ROOT / 'device/native_first_client.sh'), *action],
                                        env=env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('native process owner is missing', result.stderr)
                self.assertFalse(Path(env['PID_FILE']).exists())


@unittest.skipUnless(platform.system() == 'Linux', 'Linux /proc and sessions required')
class ProcessOwnerTest(unittest.TestCase):
    def test_stop_restart_identity_and_resistant_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'owner'
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(OWNER / 'process_owner.c'), '-o', str(binary)], check=True, timeout=60)
            result = subprocess.run(['sh', str(OWNER / 'test_owner.sh'), str(binary)],
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('stop: owned children gone', result.stdout)
            self.assertIn('restart: prior children gone', result.stdout)
            self.assertIn('unmanaged PID: rejected', result.stdout)
            self.assertIn('TERM-resistant worker: escalated', result.stdout)


if __name__ == '__main__':
    unittest.main()
