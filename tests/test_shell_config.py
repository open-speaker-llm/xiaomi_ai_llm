import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShellConfigTest(unittest.TestCase):
    def run_shell(self, script: str):
        return subprocess.run(
            ["sh", "-c", script],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )

    def test_device_shell_scripts_parse(self):
        scripts = [
            "device/native_first_client.sh",
            "device/vad_record.sh",
            "device/native_result_timing_probe.sh",
            "device/stream_client.sh",
            "device/wake_monitor.sh",
        ]
        for script in scripts:
            with self.subTest(script=script):
                result = subprocess.run(
                    ["sh", "-n", script],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_aivs_guard_stays_off_on_boot0_or_when_disabled(self):
        import re
        text = (ROOT / 'device/native_first_client.sh').read_text()
        function = re.search(r'^start_aivs_speech_guard\(\) \{.*?^\}', text, re.M | re.S).group()
        for enabled, root_status in [('1', 1), ('0', 0)]:
            script = (function + '\n' +
                      f'AIVS_GUARD_ENABLED={enabled}; FREEZE_NATIVE_PLAYER_ON_FALLBACK=1; '
                      f'is_system1_root() {{ return {root_status}; }}; '
                      'log() { echo unexpected; }; start_aivs_speech_guard')
            result = self.run_shell(script)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')

    def test_aivs_guard_missing_helper_keeps_polling(self):
        import re
        text = (ROOT / 'device/native_first_client.sh').read_text()
        function = re.search(r'^start_aivs_speech_guard\(\) \{.*?^\}', text, re.M | re.S).group()
        result = self.run_shell(function + '\n' +
                                'AIVS_GUARD_ENABLED=1; FREEZE_NATIVE_PLAYER_ON_FALLBACK=1; '
                                'AIVS_GUARD_BIN=/nonexistent/aivs_guard; '
                                'is_system1_root() { return 0; }; log() { echo "$*"; }; '
                                'start_aivs_speech_guard')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('keeping normal fallback polling', result.stdout)

    def test_native_first_env_example_is_sourceable(self):
        result = self.run_shell(
            ". device/native_first.env.example; "
            'printf "%s\\n" "$BACKEND $FOLLOWUP_START_HITS $NATIVE_REPLAY_SUCCESS_DELAY"'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "deepseek 1 0")

    def test_pcm_manager_refuses_unknown_firmware_and_foreign_overlay(self):
        text = (ROOT / 'device/pcm_tap/native_pcm_tap.sh').read_text()
        functions = text.split('\ncase "${1:-status}"')[0]
        for overrides, expected in [
            ('is_boot1() { return 1; };', 'boot0: skip'),
            ('is_boot1() { return 0; }; verified_audio() { return 1; };', 'hash mismatch'),
            ('is_boot1() { return 0; }; verified_audio() { return 0; }; '
             'TAP=/bin/sh; CAPTURE=/bin/sh; owned() { return 1; }; mounted() { return 0; };', 'foreign PNS overlay'),
        ]:
            result = self.run_shell(functions + '\n' + overrides + '\nstart_tap')
            self.assertIn(expected, result.stdout)
            self.assertEqual(result.returncode, 0 if expected == 'boot0: skip' else 1)

    def test_boot1_queue_is_drained_under_mute_and_prior_mute_is_preserved(self):
        import re
        import shlex
        import tempfile
        text = (ROOT / 'device/native_first_client.sh').read_text()
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', text, re.M | re.S).group()
                              for name in ('begin_native_queue_drain', 'end_native_queue_drain',
                                           'finish_llm_playback'))
        for root_status, prior, expected in [
            (0, 'off', ['on', 'resume', 'volume', 'off', 'idle']),
            (0, 'on', ['resume', 'volume', 'idle']),
            (1, 'off', ['resume', 'volume', 'idle']),
        ]:
            with tempfile.TemporaryDirectory() as d:
                trace = Path(d) / 'trace'
                result = self.run_shell(functions + '\n' +
                    f'trace={shlex.quote(str(trace))}; prior={prior}; NATIVE_DRAIN_MUTED=0; '
                    f'is_system1_root() {{ return {root_status}; }}; ' + '''
is_native_player_frozen() { return 0; }; is_busy() { return 0; }
amixer() { if [ "$3" = sget ]; then echo "Mono: Playback [$prior]"; else echo "$5" >> "$trace"; fi; }
log() { :; }
resume_native_player() { echo resume >> "$trace"; }
restore_llm_master_volume() { echo volume >> "$trace"; }
clear_busy() { echo idle >> "$trace"; }
finish_llm_playback
''')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(trace.read_text().splitlines(), expected)

    def test_native_pcm_leaves_native_capture_and_boot0_defaults_alone(self):
        import re
        text = (ROOT / 'device/native_first_client.sh').read_text()
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', text, re.M | re.S).group()
                              for name in ('apply_system_defaults', 'prepare_followup_capture',
                                           'start_followup_vad_prearm'))
        result = self.run_shell(functions + '''
is_system1_root() { return 1; }
FOLLOWUP_ENABLED=1; FOLLOWUP_RECORD_MODE=window; FOLLOWUP_ASR_ENGINE=native
SYSTEM1_FOLLOWUP_ENABLED=1; SYSTEM1_FOLLOWUP_RECORD_MODE=native_pcm
SYSTEM1_FOLLOWUP_ASR_ENGINE=mac
apply_system_defaults
echo "$FOLLOWUP_RECORD_MODE/$FOLLOWUP_ASR_ENGINE"
is_system1_root() { return 0; }
apply_system_defaults
echo "$FOLLOWUP_RECORD_MODE/$FOLLOWUP_ASR_ENGINE"
SYSTEM1_FOLLOWUP_CAPTURE_MIPNS=1; FOLLOWUP_PREARM=1
killall() { echo unexpected-kill; }; pidof() { echo 123; }
prepare_followup_capture
start_followup_vad_prearm
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['window/native', 'native_pcm/mac'])

    def test_env_example_tracks_key_client_defaults(self):
        env_text = (ROOT / "device/native_first.env.example").read_text()
        client_text = (ROOT / "device/native_first_client.sh").read_text()
        expected_pairs = {
            "FOLLOWUP_ARM_DELAY": "0",
            "FOLLOWUP_ARM_POLL_SECONDS": "0.03",
            "FOLLOWUP_START_HITS": "1",
            "FOLLOWUP_MIN_RAW_BYTES": "16000",
            "FOLLOWUP_WINDOW_MIN_PEAK": "120",
            "FOLLOWUP_WINDOW_MIN_RMS_THRESHOLD": "15",
            "FOLLOWUP_WINDOW_MIN_ACTIVE_PERMILLE": "2",
            "NATIVE_REPLAY_SUCCESS_DELAY": "0",
            "NATIVE_REPLAY_SUCCESS_SPEAK": "1",
            "FREEZE_NATIVE_PLAYER_ON_THINK": "1",
            "SUPPRESS_NATIVE_THINK_LED": "1",
            "LLM_VOLUME": "1.1",
            "LLM_MASTER_SCALE": "100",
            "LLM_MASTER_CURRENT_SCALE": "100",
            "LLM_MASTER_MAX": "160",
            "LLM_PIPELINE": "native",
            "LLM_MODEL": "deepseek-v4-flash",
            "LLM_THINKING": "disabled",
            "TTS_FALLBACK_NATIVE": "1",
            "TTS_NATIVE_WAIT_ENABLED": "1",
            "TTS_NATIVE_WAIT_MIN_SECONDS": "2",
            "TTS_NATIVE_WAIT_MAX_SECONDS": "30",
            "TTS_NATIVE_WAIT_BYTES_PER_SECOND": "24",
            "TTS_NATIVE_WAIT_EXTRA_SECONDS": "1",
            "TTS_NATIVE_STATUS_WAIT_ENABLED": "1",
            "TTS_NATIVE_STATUS_START_TIMEOUT_SECONDS": "4",
            "TTS_NATIVE_STATUS_MAX_SECONDS": "120",
            "TTS_NATIVE_STATUS_IDLE_HITS": "2",
            "TTS_NATIVE_STATUS_POLL_SECONDS": "0.2",
            "TTS_NATIVE_LED_SUPPRESS_INTERVAL_SECONDS": "0.3",
            "LED_FEEDBACK_ENABLED": "1",
            "LED_LLM_ACCEPT_BLINKS": "3",
            "LED_FOLLOWUP_ASR_OK_BLINKS": "3",
            "LED_ERROR_BLINKS": "3",
            "LED_BLINK_ON_SECONDS": "0.12",
            "LED_BLINK_OFF_SECONDS": "0.12",
            "LED_CHASE_DELAY_SECONDS": "0.08",
            "LED_SOLID_REFRESH_SECONDS": "0.3",
            "LED_WAKE_HOLD_SECONDS": "4",
            "LED_WAKE_HOLD_REFRESH_SECONDS": "0.1",
        }
        for key, value in expected_pairs.items():
            with self.subTest(key=key):
                self.assertIn(f"{key}={value}", env_text)
                self.assertIn(f'{key}="${{{key}:-{value}}}"', client_text)


if __name__ == "__main__":
    unittest.main()
