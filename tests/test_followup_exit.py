"""Opt-in followup exit commands through the real shell conversation routes."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ('结束对话', '退出对话', '停止对话', '不聊了', '退下')


def functions(*names):
    if 'is_followup_reset_command' not in names:
        names += ('is_followup_reset_command',)
    source = (ROOT / 'device/native_first_client.sh').read_text()
    return '\n'.join(re.search(r'^' + name + r'\(\) \{.*?(?=^[a-zA-Z_]\w*\(\) \{|\Z)',
                              source, re.M | re.S).group()
                     for name in names)


class FollowupExitTest(unittest.TestCase):
    def dialog(self, inputs, *, first='介绍西湖', path='native_live', enabled='1', guard='1'):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'inputs').write_text('\n'.join(inputs) + '\n')
            code = functions('handle_llm_dialog', 'collect_native_dialog_text',
                             'classify_native_dialog_text', 'native_dialog_compact',
                             'cancel_followup_vad_prearm', 'is_followup_exit_command') + r'''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=$ROUTE
if [ "$ROUTE" = native_multirounds ]; then FOLLOWUP_MODE=native_multirounds; fi
SUPPRESS_DUP_SECONDS=5; calls=0; FOLLOWUP_VAD_PID=; FOLLOWUP_ARM_FILE=$TEST_DIR/arm
NATIVE_DIALOG_INPUT_MAX_REPROMPTS=2; FOLLOWUP_TIMEOUT=1
is_system1_root() { [ "$ROUTE" = native_live ]; }
log() { :; }; set_state() { STATE=$1; }; pause_native_asr() { :; }; resume_native_asr() { echo RESUME; }
led_feedback_llm_accept() { :; }; led_feedback_followup_asr_ok() { :; }; led_off() { :; }
led_feedback_llm_followup_listening() { :; }; led_feedback_error() { :; }; sleep() { :; }
finish_llm_playback() { echo CLEAN; }
send_text_and_play() { printf 'LLM|%s|%s\n' "$1" "$2"; }
play_native_dialog_prompt() { printf 'PROMPT|%s\n' "$1"; }
get_aivs_lab_latest_dialog_id() { echo dialog; }; native_followup_mark_multirounds() { echo MARK; }
next_input() {
    calls=$((calls+1)); FOLLOWUP_TEXT=$(sed -n "${calls}p" "$TEST_DIR/inputs")
    [ -n "$FOLLOWUP_TEXT" ] || return 124
}
wait_native_live_asr() { next_input; }
wait_native_followup_text() { next_input; }
wait_or_run_followup_vad() { next_input; }
transcribe_followup_voice() { return 0; }
handle_llm_dialog same-session "$FIRST"
printf 'END|state=%s|reads=%s|session=%s|dedup=%s\n' "$STATE" "$calls" "$CURRENT_SESSION_ID" "$SUPPRESS_DUP_SECONDS"
'''
            run = subprocess.run(['sh', '-c', code], text=True, capture_output=True, timeout=5,
                                 env={**os.environ, 'LC_ALL': 'C', 'TEST_DIR': temp, 'FIRST': first,
                                      'ROUTE': path, 'FOLLOWUP_EXIT_ENABLED': enabled,
                                      'NATIVE_DIALOG_INPUT_GUARD': guard})
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            return run.stdout.splitlines()

    def test_each_command_exits_all_three_routes_without_another_request_or_listen(self):
        for path in ('native_live', 'native_multirounds', 'window'):
            for command in COMMANDS:
                with self.subTest(path=path, command=command):
                    rows = self.dialog([command, '不应再收听'], path=path)
                    self.assertEqual([r for r in rows if r.startswith('LLM|')], ['LLM|same-session|介绍西湖'])
                    self.assertFalse(any(r.startswith('PROMPT|') for r in rows))
                    self.assertEqual(rows.count('CLEAN'), 1)
                    self.assertEqual(rows.count('RESUME'), 1)
                    self.assertIn('END|state=IDLE|reads=1|session=|dedup=5', rows)
                    self.assertEqual(rows.count('MARK'), int(path == 'native_multirounds'))

    def test_only_one_explicit_flag_enables_exit(self):
        for enabled in ('', '0', 'true', '2'):
            for path in ('native_live', 'native_multirounds', 'window'):
                with self.subTest(enabled=enabled, path=path):
                    self.assertIn('LLM|same-session|结束对话', self.dialog(['结束对话'], path=path, enabled=enabled))

    def test_outer_space_and_terminal_punctuation_are_accepted(self):
        for text in (' 结束对话。 ', '\t不聊了！\t', '退下!?', '停止对话？！'):
            with self.subTest(text=text):
                rows = self.dialog([text])
                self.assertEqual(sum(r.startswith('LLM|') for r in rows), 1)

    def test_quoted_negated_or_discussed_commands_are_not_intercepted(self):
        for text in ('不要结束对话', '解释结束对话的意思', '“结束对话”', '"退下"',
                     '请结束对话', '结束对话后做什么', '结束 对话', '小爱同学结束对话'):
            with self.subTest(text=text):
                self.assertIn('LLM|same-session|' + text, self.dialog([text]))

    def test_first_question_and_first_question_completion_are_not_exit_commands(self):
        for path in ('native_live', 'native_multirounds', 'window'):
            with self.subTest(path=path):
                self.assertIn('LLM|same-session|结束对话', self.dialog([], first='结束对话', path=path))
        rows = self.dialog(['结束对话'], first='帮我查一下')
        self.assertIn('LLM|same-session|帮我查一下，结束对话', rows)

    def test_followup_completion_can_exit_before_pending_fragment_is_submitted(self):
        rows = self.dialog(['帮我查一下', '退出对话', '不应收听'])
        self.assertEqual([r for r in rows if r.startswith('LLM|')], ['LLM|same-session|介绍西湖'])
        self.assertEqual(sum(r.startswith('PROMPT|') for r in rows), 1)
        self.assertIn('END|state=IDLE|reads=2|session=|dedup=5', rows)

    def test_exit_is_independent_of_input_completion_guard(self):
        rows = self.dialog(['停止对话'], guard='0')
        self.assertEqual(sum(r.startswith('LLM|') for r in rows), 1)
        self.assertIn('END|state=IDLE|reads=1|session=|dedup=5', rows)

    def test_short_native_exit_words_bypass_length_filter_without_mac_fallback(self):
        for enabled in ('0', '1'):
            for text in ('退下', '不聊了'):
                with self.subTest(enabled=enabled, text=text), tempfile.TemporaryDirectory() as temp:
                    Path(temp, 'voice.wav').write_bytes(b'fixture')
                    code = functions('transcribe_followup_voice', 'transcribe_followup_voice_native',
                                     'is_followup_exit_command').replace('/tmp/voice.wav', temp + '/voice.wav')
                    code = code.replace('/tmp/native_followup_ai_service.json', temp + '/result.json')
                    code += r'''
FOLLOWUP_ASR_ENGINE=native; FOLLOWUP_NATIVE_ASR_FALLBACK_MAC=1; FOLLOWUP_NATIVE_MIN_QUERY_BYTES=10
FOLLOWUP_NATIVE_ASR_TIMEOUT=1
json_escape() { cat; }; log() { :; }; ubus() { echo '{"code":0}'; }
extract_ai_service_asr_query() { cat >/dev/null; printf '%s' "$TEXT"; }
transcribe_followup_voice_mac() { echo UNEXPECTED_MAC; return 1; }
transcribe_followup_voice
echo "RESULT=$?:TEXT=$FOLLOWUP_TEXT"
'''
                    run = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                         env={**os.environ, 'TEXT': text, 'FOLLOWUP_EXIT_ENABLED': enabled})
                    self.assertEqual(run.returncode, 0, run.stderr)
                    if enabled == '1':
                        self.assertNotIn('UNEXPECTED_MAC', run.stdout)
                        self.assertIn('RESULT=0:TEXT=' + text, run.stdout)
                    else:
                        self.assertIn('UNEXPECTED_MAC', run.stdout)

    def test_native_multirounds_preserves_quoted_text_before_exit_matching(self):
        with tempfile.TemporaryDirectory() as temp:
            row = {'header': {'name': 'RecognizeResult', 'dialog_id': 'new'},
                   'payload': {'is_final': True, 'results': [{'text': '"结束对话"'}]}}
            Path(temp, 'instructions').write_text(json.dumps(row, separators=(',', ':')) + '\n')
            code = functions('extract_aivs_latest_final_text_after', 'json_text_field',
                             'json_text_unescape', 'json_unicode_decode', 'is_followup_exit_command') + r'''
AIVS_LAB_LOOKBACK_LINES=40; AIVS_LAB_INSTRUCTION_LOG=$TEST_DIR/instructions
AIVS_LAB_LAST_DIALOG_FILE=$TEST_DIR/last; FOLLOWUP_EXIT_ENABLED=1
extract_aivs_latest_final_text_after old first
echo "QUERY=$FOLLOWUP_TEXT"
is_followup_exit_command "$FOLLOWUP_TEXT"
echo "EXIT_RESULT=$?"
'''
            run = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                 env={**os.environ, 'LC_ALL': 'C', 'TEST_DIR': temp})
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('QUERY="结束对话"', run.stdout)
            self.assertIn('EXIT_RESULT=1', run.stdout)

    def test_native_multirounds_exit_is_not_hidden_by_first_question_deduplication(self):
        with tempfile.TemporaryDirectory() as temp:
            row = {'header': {'name': 'RecognizeResult', 'dialog_id': 'new'},
                   'payload': {'is_final': True, 'results': [{'text': '结束对话'}]}}
            Path(temp, 'instructions').write_text(json.dumps(row, separators=(',', ':')) + '\n')
            code = functions('extract_aivs_latest_final_text_after', 'json_text_field',
                             'json_text_unescape', 'json_unicode_decode', 'is_followup_exit_command') + r'''
AIVS_LAB_LOOKBACK_LINES=40; AIVS_LAB_INSTRUCTION_LOG=$TEST_DIR/instructions
AIVS_LAB_LAST_DIALOG_FILE=$TEST_DIR/last; FOLLOWUP_EXIT_ENABLED=1
extract_aivs_latest_final_text_after old '结束对话'
echo "RESULT=$?:QUERY=$FOLLOWUP_TEXT"
'''
            run = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                 env={**os.environ, 'LC_ALL': 'C', 'TEST_DIR': temp})
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('RESULT=0:QUERY=结束对话', run.stdout)
