"""Run the installed hook's actual dispatch with fake native endpoints."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativePlaybackParallelTest(unittest.TestCase):
    def test_only_owned_followup_suppresses_native_callbacks(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        hook = source.split('cat > "$HOOK_WAKEUP" << \'EOF\'\n', 1)[1].split('\nEOF', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            hookfile = temp / 'hook.sh'; hookfile.write_text(hook)
            orig = temp / 'original'; orig.write_text('#!/bin/sh\necho "native:$*" >> "$TRACE"\n'); orig.chmod(0o755)
            awk = temp / 'awk'; awk.write_text('#!/bin/sh\necho /dev/mtdblock5\n'); awk.chmod(0o755)
            ctl = temp / 'ctl'; ctl.write_text('#!/bin/sh\n[ "$PHASE" != unavailable ] || exit 1\necho "phase=$PHASE sequence=7"\n'); ctl.chmod(0o755)
            busy = temp / 'busy'; busy.touch()
            trace = temp / 'trace'; log = temp / 'log'
            env = dict(os.environ, PATH=str(temp)+os.pathsep+os.environ['PATH'],
                       CONFIG_FILE=str(temp / 'no-config'), EVENT_LOG=str(log),
                       EVENT_FIFO=str(temp / 'no-fifo'), ORIG_WAKEUP=str(orig),
                       BUSY_MARKER=str(busy), TRACE=str(trace), NATIVE_ASR_CTL=str(ctl),
                       LED_FEEDBACK_ENABLED='0', SYSTEM1_FOLLOWUP_RECORD_MODE='native_live',
                       NATIVE_REPLAY_CANCEL_MARKER=str(temp / 'no-cancel'))
            for phase in ['0', '1', '2', '3', '4', '5', '6', '7', '8', 'unavailable']:
                for event in ['ready', 'WuW', 'multirounds']:
                    with self.subTest(phase=phase, event=event):
                        trace.write_text(''); log.write_text('')
                        subprocess.run(['sh', str(hookfile), event], env=dict(env, PHASE=phase),
                                       check=True, capture_output=True, timeout=3)
                        if phase in ['1', '2', '3', '4', '5', '6']:
                            self.assertEqual(trace.read_text(), '')
                            self.assertIn('NATIVE_FOLLOWUP_CUE_SUPPRESSED', log.read_text())
                        else:
                            self.assertEqual(trace.read_text(), 'native:'+event+'\n')
                            self.assertNotIn('NATIVE_FOLLOWUP_CUE_SUPPRESSED', log.read_text())
