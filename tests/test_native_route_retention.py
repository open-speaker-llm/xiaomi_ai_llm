"""Bounded completed-record retention; denial records never become permissive."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeRouteRetentionTest(unittest.TestCase):
    def test_many_completed_turns_keep_failures_and_stay_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-DNW_DIR="' + str(p / 'state') + '"',
                            str(ROOT / 'device/endpoint_probe/test_native_route_retention.c'),
                            '-o', str(p / 'test')], check=True, capture_output=True)
            result = subprocess.run([str(p / 'test')], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS route retention', result.stdout)
