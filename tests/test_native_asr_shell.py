import re
import subprocess
import unittest
import tempfile
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeAsrShellTest(unittest.TestCase):
    def functions(self, *names):
        if 'handle_llm_dialog' in names:
            names += ('native_dialog_compact', 'classify_native_dialog_text', 'collect_native_dialog_text')
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

    def test_physical_handoff_does_not_submit_or_clean_up_new_native_dialog(self):
        result = self.shell(self.functions('handle_llm_dialog') + '''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=native_live
SUPPRESS_DUP_SECONDS=5
is_system1_root() { return 0; }; log() { :; }; set_state() { :; }
pause_native_asr() { :; }; led_feedback_llm_accept() { :; }
resume_native_asr() { echo unexpected-resume; }; led_off() { echo unexpected-led-off; }
send_text_and_play() { echo "LLM:$2"; }
wait_native_live_asr() { NATIVE_DIALOG_HANDED_OFF=1; FOLLOWUP_TEXT='关灯'; return 125; }
finish_llm_playback() { echo unexpected-queue-reset; }
handle_llm_dialog session question
echo "done:session=$CURRENT_SESSION_ID:dedup=$SUPPRESS_DUP_SECONDS"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['LLM:question', 'done:session=:dedup=5'])

    def test_native_listen_restores_audio_before_capture_and_yields_without_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.shell(self.functions('wait_native_live_asr') + '\nLED_FEEDBACK_TOKEN_FILE=' +
                                shlex.quote(temp + '/token') + '''
NATIVE_ASR_CTL=fake_ctl; NATIVE_ASR_LISTEN_TIMEOUT=20; LED_FEEDBACK_PID=''
finish_llm_playback() { echo restore-old-audio; }
set_busy() { echo busy-listening; }; set_state() { :; }; log() { :; }
led_feedback_llm_followup_listening() { echo green-listen; }
clear_busy() { echo native-unblocked; }
fake_ctl() { echo 'stale query'; return 125; }
wait_native_live_asr
echo "ret=$?:handoff=$NATIVE_DIALOG_HANDED_OFF:text=$FOLLOWUP_TEXT"
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['restore-old-audio', 'busy-listening',
                             'green-listen', 'native-unblocked', 'ret=125:handoff=1:text='])

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

    def test_followup_preserves_llm_volume_but_restores_native_volume(self):
        for rc in (0, 124, 125):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as temp:
                code = self.functions('wait_native_live_asr', 'finish_llm_playback',
                                      'restore_llm_master_volume', 'apply_llm_master_volume',
                                      'calc_llm_master_volume')
                code += '\nLED_FEEDBACK_TOKEN_FILE=' + shlex.quote(temp + '/token')
                code += '\nCTL_RC=' + str(rc) + r'''
DEVICE_MASTER=155; MASTER_RESTORE_VALUE=145; LLM_SESSION_MASTER_TARGET=145
LLM_MASTER_VOLUME=auto; LLM_MASTER_SCALE=100; LLM_MASTER_CURRENT_SCALE=100
LLM_MASTER_MIN=96; LLM_MASTER_MAX=160
TTS_ENGINE=device; DEVICE_TTS_STREAM=1; DEVICE_TTS_STREAM_MASTER_BOOST=10
NATIVE_ASR_CTL=fake_ctl; NATIVE_ASR_LISTEN_TIMEOUT=20; LED_FEEDBACK_PID=''
log() { :; }; set_busy() { :; }; set_state() { :; }; clear_busy() { :; }
led_feedback_llm_followup_listening() { :; }
begin_native_queue_drain() { :; }; resume_native_player() { :; }; end_native_queue_drain() { :; }
get_master_volume() { echo "$DEVICE_MASTER"; }
set_master_volume() { DEVICE_MASTER="$1"; }
get_native_media_volume() { echo 150; }
fake_ctl() {
    [ "$DEVICE_MASTER" = 145 ] || return 99
    [ -z "$MASTER_RESTORE_VALUE" ] || return 99
    echo question
    return "$CTL_RC"
}
wait_native_live_asr
rc=$?
echo "after-listen:$rc:master=$DEVICE_MASTER:target=$LLM_SESSION_MASTER_TARGET"
if [ "$rc" = 0 ]; then
    apply_llm_master_volume
    echo "next-answer:$DEVICE_MASTER"
    finish_llm_playback
elif [ "$rc" != 125 ]; then
    finish_llm_playback
fi
echo "end:master=$DEVICE_MASTER:target=$LLM_SESSION_MASTER_TARGET"
'''
                result = self.shell(code)
                self.assertEqual(result.returncode, 0, result.stderr)
                target = '' if rc == 125 else '145'
                expected = [f'after-listen:{rc}:master=145:target={target}']
                if rc == 0:
                    expected.append('next-answer:155')
                expected.append('end:master=145:target=')
                self.assertEqual(result.stdout.splitlines(), expected)
