import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeAsrShellTest(unittest.TestCase):
    def functions(self, *names):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        return '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', source, re.M | re.S).group()
                         for name in names)

    def shell(self, code):
        return subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)

    def test_native_followup_keeps_session_and_uses_no_recorder_or_mac(self):
        result = self.shell(self.functions('handle_llm_dialog') + '''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=native_live
SUPPRESS_DUP_SECONDS=5; calls=0
is_system1_root() { return 0; }
log() { :; }; set_state() { :; }; pause_native_asr() { :; }; resume_native_asr() { :; }
led_feedback_llm_accept() { :; }; led_feedback_followup_asr_ok() { :; }; led_off() { :; }
finish_llm_playback() { echo cleaned; }
send_text_and_play() { printf '%s|%s|%s|dedup=%s\\n' "$1" "$2" "$3" "$SUPPRESS_DUP_SECONDS"; }
wait_native_live_asr() {
    calls=$((calls+1)); [ "$calls" -eq 1 ] || return 1
    FOLLOWUP_TEXT='不要再讲了'; return 0
}
wait_or_run_followup_vad() { echo unexpected-recorder; return 1; }
transcribe_followup_voice() { echo unexpected-external-ASR; return 1; }
handle_llm_dialog same-session first-question
echo "restored-dedup=$SUPPRESS_DUP_SECONDS"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            'same-session|first-question|defer|dedup=5',
            'same-session|不要再讲了|defer|dedup=0', 'cleaned', 'restored-dedup=5'])

    def test_llm_error_does_not_open_microphone(self):
        result = self.shell(self.functions('handle_llm_dialog') + '''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=native_live
SUPPRESS_DUP_SECONDS=5
is_system1_root() { return 0; }; log() { :; }; set_state() { :; }
pause_native_asr() { :; }; resume_native_asr() { :; }; led_feedback_llm_accept() { :; }; led_off() { :; }
send_text_and_play() { return 1; }
wait_native_live_asr() { echo unexpected-listen; return 1; }
finish_llm_playback() { echo cleaned; }
handle_llm_dialog session question
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'cleaned')

    def test_boot0_defaults_and_capture_remain_unchanged(self):
        result = self.shell(self.functions('apply_system_defaults', 'start_followup_vad_prearm',
                                            'prepare_followup_capture', 'pause_native_asr') + '''
is_system1_root() { return 1; }
FOLLOWUP_ENABLED=1; FOLLOWUP_RECORD_MODE=window; FOLLOWUP_ASR_ENGINE=native
SYSTEM1_FOLLOWUP_ENABLED=1; SYSTEM1_FOLLOWUP_RECORD_MODE=native_live; SYSTEM1_FOLLOWUP_ASR_ENGINE=native_live
apply_system_defaults
echo "$FOLLOWUP_RECORD_MODE/$FOLLOWUP_ASR_ENGINE"
is_system1_root() { return 0; }; apply_system_defaults
echo "$FOLLOWUP_RECORD_MODE/$FOLLOWUP_ASR_ENGINE"
PAUSE_NATIVE_ASR_DURING_LLM=1; FOLLOWUP_PREARM=1; SYSTEM1_FOLLOWUP_CAPTURE_MIPNS=1
killall() { echo unexpected-kill; }; pidof() { echo 123; }
start_followup_vad_prearm; prepare_followup_capture; pause_native_asr
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['window/native', 'native_live/native_live'])

    def test_manager_refuses_unknown_firmware_before_mount(self):
        code = (ROOT / 'device/native_asr/native_asr.sh').read_text().split('\ncase "${1:-status}"')[0]
        result = self.shell(code + '''
is_boot1() { return 0; }; verified() { return 1; }; mount() { echo unexpected-mount; }
start_native_asr
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn('firmware ABI hash mismatch', result.stdout)
        self.assertNotIn('unexpected-mount', result.stdout)
