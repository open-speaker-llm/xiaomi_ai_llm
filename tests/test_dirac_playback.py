"""Exercise playback gating, argument/status preservation and the client adapter."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / 'device/dirac/dirac_aplay.sh').read_text().rsplit('\ndirac_aplay_main "$@"', 1)[0]


class DiracPlaybackTest(unittest.TestCase):
    def run_wrapper(self, supported=True, helper=True, enabled='1', rc=0):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            if helper:
                (folder / 'helper.so').touch()
            player = folder / 'aplay'
            player.write_text('''#!/bin/sh
printf 'enabled=%s\npreload=%s\n' "${NATIVE_FIRST_DIRAC:-}" "${LD_PRELOAD:-}"
printf 'arg=%s\n' "$@"
exit "$PLAYER_RC"
''')
            player.chmod(0o700)
            code = WRAPPER + '\nDIRAC_SO="$TEST_DIR/helper.so"\n'
            code += 'dirac_supported() { return ' + ('0' if supported else '1') + '; }\n'
            code += 'export LD_PRELOAD=existing.so\ndirac_aplay_main -r 24000 "file with spaces.pcm"\n'
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                    env={**os.environ, 'TEST_DIR': temp, 'LLM_DIRAC_ENABLED': enabled,
                                         'PLAYER_RC': str(rc), 'PATH': temp + ':' + os.environ['PATH']})
            return result, temp

    def test_supported_player_loads_helper_and_preserves_existing_preload_and_arguments(self):
        result, temp = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('enabled=1\n', result.stdout)
        self.assertIn(f'preload={temp}/helper.so:existing.so\n', result.stdout)
        self.assertIn('arg=-r\narg=24000\narg=file with spaces.pcm\n', result.stdout)

    def test_disabled_missing_helper_and_unsupported_firmware_keep_plain_playback(self):
        for opts in [{'enabled': '0'}, {'helper': False}, {'supported': False}]:
            with self.subTest(opts=opts):
                result, _ = self.run_wrapper(**opts)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('enabled=\npreload=existing.so\n', result.stdout)
                self.assertIn('[DIRAC] bypass:', result.stderr)

    def test_player_failure_is_propagated(self):
        result, _ = self.run_wrapper(rc=17)
        self.assertEqual(result.returncode, 17)

    def test_all_firmware_assets_and_boot_partition_are_required(self):
        for failure in ['', '/etc/asound.conf', '/usr/lib/libasound.so.2.0.0',
                        '/usr/lib/libDiracAPI_SHARED.so', '/data/etc/diracmobile.config', 'boot0']:
            with self.subTest(failure=failure):
                code = WRAPPER + '''
awk() { if [ "$FAIL_ASSET" = boot0 ]; then echo /dev/mtdblock4; else echo /dev/mtdblock5; fi; }
dirac_hash_is() { [ "$1" != "$FAIL_ASSET" ]; }
dirac_supported
'''
                result = subprocess.run(['sh', '-c', code], env={**os.environ, 'FAIL_ASSET': failure},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0 if not failure else 1)

    def test_hash_mismatch_and_missing_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'asset')
            path.write_text('wrong asset')
            for name in ['asset', 'missing']:
                result = subprocess.run(['sh', '-c', WRAPPER + '\ndirac_hash_is "$ASSET" abc\n'],
                                        env={**os.environ, 'ASSET': str(Path(temp, name))},
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)

    def test_client_logs_player_stderr_and_propagates_exit_status(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        function = re.search(r'^llm_aplay\(\) \{.*?^\}', source, re.M | re.S).group()
        with tempfile.TemporaryDirectory() as temp:
            wrapper = Path(temp, 'player')
            wrapper.write_text('#!/bin/sh\necho "[DIRAC] initialize rc=0" >&2\nexit 17\n')
            wrapper.chmod(0o700)
            log = Path(temp, 'player.log')
            result = subprocess.run(['sh', '-c', function + '\nllm_aplay test.pcm\n'],
                                    env={**os.environ, 'DIRAC_APLAY': str(wrapper),
                                         'DIRAC_PLAYBACK_LOG': str(log)}, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 17)
            self.assertIn('[DIRAC] initialize rc=0', log.read_text())


if __name__ == '__main__':
    unittest.main()
