"""Check the client cannot start S12A native managers on an UBIFS root."""
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'device/native_first_client.sh').read_text()

def fn(name):
    return re.search(r'^' + name + r'\(\) \{.*?^\}', SOURCE, re.M | re.S).group()

class ABIGuard(unittest.TestCase):
    def test_start_managers_only_on_legacy_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / 'trace'
            manager = Path(tmp) / 'manager'
            manager.write_text('#!/bin/sh\necho start >> ' + shlex.quote(str(trace)) + '\n')
            manager.chmod(0o700)
            for root, expected in [('/dev/mtdblock5', 2), ('/dev/ubi0_0', 0), ('', 0)]:
                if trace.exists(): trace.unlink()
                script = '\n'.join(fn(n) for n in ('is_s12a_native_abi_root', 'setup_native_endpoint', 'setup_native_live_asr'))
                script += '\nroot_device() { printf "%s\\n" ' + shlex.quote(root) + '; }\nis_system1_root() { return 0; }\nlog() { :; }\n'
                script += 'NATIVE_ENDPOINT_ENABLED=1; FOLLOWUP_ENABLED=1; FOLLOWUP_RECORD_MODE=native_live\n'
                script += 'NATIVE_ENDPOINT_MANAGER=' + shlex.quote(str(manager)) + '\nNATIVE_ASR_MANAGER=' + shlex.quote(str(manager)) + '\nNATIVE_ASR_CTL=' + shlex.quote(str(manager)) + '\n'
                script += 'setup_native_endpoint; setup_native_live_asr; echo "followup=$FOLLOWUP_ENABLED"\n'
                out = subprocess.run(['sh'], input=script, capture_output=True, text=True, check=True)
                calls = len(trace.read_text().splitlines()) if trace.exists() else 0
                self.assertEqual(calls, expected, root)
                self.assertIn('followup=' + ('1' if expected else '0'), out.stdout)
