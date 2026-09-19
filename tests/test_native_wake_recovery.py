"""Run the actual watcher in observation mode; no microphone or cloud calls."""
from pathlib import Path
import select
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeWakeRecoveryTest(unittest.TestCase):
    def test_dead_owner_and_helper_preserve_denial_and_allow_new_dialog(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            binary = p / 'recovery'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-DNW_DIR="' + str(p / 'state') + '"',
                            str(ROOT / 'device/endpoint_probe/test_native_recovery.c'),
                            '-o', str(binary)], check=True, capture_output=True)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('PASS abandoned recovery', run.stdout)

    def test_killed_owner_can_rearm_without_erasing_route_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            binary = p / 'watch'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-DNW_DIR="' + tmp + '"',
                            str(ROOT / 'device/endpoint_probe/native_wake_watch.c'),
                            '-o', str(binary)], check=True, capture_output=True)
            first = subprocess.Popen([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            second = None
            try:
                self.assertTrue(select.select([first.stdout], [], [], 3)[0])
                self.assertIn(b'WAKE_OBSERVER_READY', first.stdout.readline())
                (p / 'routes').mkdir(mode=0o700)
                record = p / 'routes/old-dialog'
                record.write_text('NW1 123 456 ' + 'ab' * 16 + ' pending\n')
                first.kill()
                first.wait(timeout=3)
                self.assertTrue((p / 'native-wake.state').exists())
                second = subprocess.Popen([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertTrue(select.select([second.stdout], [], [], 3)[0])
                output = second.stdout.readline()
                if b'RECOVERED' in output:
                    output += second.stdout.readline()
                self.assertIn(b'WAKE_OBSERVER_READY', output)
                self.assertTrue(record.read_text().endswith(' pending\n'))
                # A competing watcher must neither steal nor erase the lease.
                before = (p / 'native-wake.state').read_bytes()
                other = subprocess.run([str(binary)], capture_output=True, timeout=3)
                self.assertNotEqual(other.returncode, 0)
                self.assertEqual(before, (p / 'native-wake.state').read_bytes())
                second.terminate()
                second.wait(timeout=3)
                self.assertFalse((p / 'native-wake.state').exists())
            finally:
                for child in (first, second):
                    if child is not None:
                        if child.poll() is None:
                            child.kill()
                        child.communicate(timeout=3)
