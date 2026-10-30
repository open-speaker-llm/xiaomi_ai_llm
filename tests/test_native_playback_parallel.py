"""Run the installed hook's actual dispatch with fake native endpoints."""
import os
import shutil
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
            # Newly created executables have a large first-exec cost on macOS.
            # Source dependency fakes through the hook's actual config path so
            # this dispatch test does not time host first-exec overhead.
            config = temp / 'config'
            config.write_text('''unexpected_helper() {
    printf '%s\\n' "$*" >> "$UNEXPECTED_HELPER"
    return 99
}
awk() {
    case "$2" in
        /proc/mounts) printf '/dev/mtdblock5\\n';;
        /proc/uptime) printf '000\\n';;
        *) unexpected_helper awk "$@";;
    esac
}
fixture_native_asr_ctl() {
    [ "$#" = 1 ] && [ "$1" = status ] || { unexpected_helper ctl "$@"; return 99; }
    [ "$PHASE" != unavailable ] || return 1
    printf 'phase=%s sequence=7\\n' "$PHASE"
}
sleep() { unexpected_helper sleep "$@"; }
ubus() { unexpected_helper ubus "$@"; }
''')
            original = shutil.which('echo')
            self.assertIsNotNone(original, 'an installed echo executable is required')
            busy = temp / 'busy'; busy.touch()
            log = temp / 'log'; unexpected = temp / 'unexpected'
            env = dict(os.environ, CONFIG_FILE=str(config), EVENT_LOG=str(log),
                       EVENT_FIFO=str(temp / 'no-fifo'), ORIG_WAKEUP=original,
                       BUSY_MARKER=str(busy), NATIVE_ASR_CTL='fixture_native_asr_ctl',
                       UNEXPECTED_HELPER=str(unexpected),
                       LED_FEEDBACK_ENABLED='0', SYSTEM1_FOLLOWUP_RECORD_MODE='native_live',
                       NATIVE_REPLAY_CANCEL_MARKER=str(temp / 'no-cancel'))
            for phase in ['0', '1', '2', '3', '4', '5', '6', '7', '8', 'unavailable']:
                for event in ['ready', 'WuW', 'multirounds']:
                    with self.subTest(phase=phase, event=event):
                        log.write_text(''); unexpected.write_text('')
                        result = subprocess.run(['sh', str(hookfile), event], env=dict(env, PHASE=phase),
                                                check=True, capture_output=True, text=True, timeout=3)
                        self.assertEqual(result.stderr, '')
                        self.assertEqual(unexpected.read_text(), '')
                        if phase in ['1', '2', '3', '4', '5', '6']:
                            self.assertEqual(result.stdout, '')
                            self.assertIn('NATIVE_FOLLOWUP_CUE_SUPPRESSED', log.read_text())
                        else:
                            self.assertEqual(result.stdout, event+'\n')
                            self.assertNotIn('NATIVE_FOLLOWUP_CUE_SUPPRESSED', log.read_text())
