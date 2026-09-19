"""Exercise temporary observer rollback without mounts or a speaker."""
import hashlib
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'device/endpoint_probe/run.sh').read_text()


class EndpointProbeTest(unittest.TestCase):
    def test_timer_survives_hangup_and_honors_ownership(self):
        for replaced in (False, True):
            with self.subTest(replaced=replaced), tempfile.TemporaryDirectory() as temp:
                d = Path(temp)
                (d / 'rollback.armed').write_text('original')
                (d / 'run.sh').write_text('#!/bin/sh\ntouch ' + shlex.quote(str(d / 'restored')) + '\n')
                prefix = SCRIPT.split('case "${1:-}" in', 1)[0]
                prefix = prefix.replace('/tmp/xiaomi_endpoint_probe', temp).replace('sleep 300', 'sleep 2')
                script = prefix + '\nstart_rollback_timer original\nprintf "%s" "$timer_pid" > "$D/pid"\n'
                run = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=5)
                self.assertEqual(run.returncode, 0, run.stderr)
                pid = int((d / 'pid').read_text())
                if replaced:
                    (d / 'rollback.armed').write_text('new-session')
                os.kill(pid, signal.SIGHUP)
                # Wait for the bounded timer, not the already exited launcher.
                import time
                time.sleep(2.2)
                self.assertEqual((d / 'restored').exists(), not replaced)

    def restore(self, mode):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            pns, probe, binaries = d / 'pns', d / 'probe', d / 'bin'
            probe.mkdir(); binaries.mkdir()
            original = '#!/bin/sh\necho restart >> "$TRACE"\n'
            overlay = original + '# XIAOMI_ENDPOINT_OBSERVER\n'
            pns.write_text(overlay if mode != 'unrelated' else original)
            pns.chmod(0o700)
            (probe / 'pns.before').write_text(original)
            (probe / 'overlay.sha256').write_text(hashlib.sha256(overlay.encode()).hexdigest())
            (probe / 'before.sha256').write_text(hashlib.sha256(original.encode()).hexdigest())
            (probe / 'rollback.armed').touch()
            if mode == 'changed':
                pns.write_text(overlay + '# changed after setup\n')
            # Portable stand-ins. All paths are confined to the temporary fixture.
            (binaries / 'sha256sum').write_text('#!/usr/bin/env python3\nimport sys,hashlib\n'
                'print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest(),sys.argv[1])\n')
            (binaries / 'umount').write_text('#!/bin/sh\necho unmount >> "$TRACE"\n'
                'cp ' + shlex.quote(str(probe / 'pns.before')) + ' "$1"\n')
            for binary in binaries.iterdir(): binary.chmod(0o700)
            script = SCRIPT.replace('/tmp/xiaomi_endpoint_probe', str(probe)).replace('/etc/init.d/pns', str(pns))
            run = subprocess.run(['sh', '-c', script, 'sh', 'restore'], text=True,
                                 capture_output=True, timeout=5,
                                 env={**os.environ, 'PATH': str(binaries) + ':' + os.environ['PATH'],
                                      'TRACE': str(d / 'trace')})
            actions = (d / 'trace').read_text().splitlines() if (d / 'trace').exists() else []
            return run.returncode, actions, (probe / 'rollback.armed').exists()

    def test_exact_owned_overlay_restores_once(self):
        self.assertEqual(self.restore('owned'), (0, ['unmount', 'restart'], False))

    def test_changed_overlay_is_not_unmounted(self):
        self.assertEqual(self.restore('changed'), (1, [], True))

    def test_unrelated_overlay_is_not_unmounted(self):
        self.assertEqual(self.restore('unrelated'), (0, [], False))

    def test_invalid_capture_window_cannot_start_recording(self):
        for seconds in ('0', '31', 'nan', '-1', '2;echo bad'):
            run = subprocess.run(['sh', str(ROOT / 'device/endpoint_probe/run.sh'), 'capture', seconds],
                                 text=True, capture_output=True, timeout=5)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn('CAPTURE_READY', run.stdout)
