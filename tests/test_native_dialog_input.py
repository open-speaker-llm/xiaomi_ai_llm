"""Input repair at the native-live LLM boundary, using real shell flow."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def functions(*names):
    source = (ROOT / 'device/native_first_client.sh').read_text()
    return '\n'.join(m.group() for n in names
                     if (m := re.search(r'^' + n + r'\(\) \{.*?^\}', source, re.M | re.S)))


class NativeDialogInputTest(unittest.TestCase):
    def dialog(self, first, followups=(), *, enabled='1', boot1=True, prompt_failure=False, llm_failure=False):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'inputs').write_text('\n'.join(followups) + '\n')
            code = functions('native_dialog_compact', 'classify_native_dialog_text',
                             'collect_native_dialog_text', 'handle_llm_dialog') + r'''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=native_live
SUPPRESS_DUP_SECONDS=5; calls=0; NATIVE_DIALOG_INPUT_MAX_REPROMPTS=2
is_system1_root() { [ "$BOOT1" = 1 ]; }
log() { :; }; set_state() { :; }; pause_native_asr() { :; }; resume_native_asr() { :; }
led_feedback_llm_accept() { :; }; led_feedback_followup_asr_ok() { :; }; led_off() { :; }
finish_llm_playback() { echo CLEAN; }
send_text_and_play() { printf 'LLM|%s|%s\n' "$1" "$2"; [ "$LLM_FAIL" != 1 ]; }
play_native_dialog_prompt() { printf 'PROMPT|%s\n' "$1"; [ "$PROMPT_FAIL" != 1 ]; }
wait_native_live_asr() {
    calls=$((calls+1))
    FOLLOWUP_TEXT=$(sed -n "${calls}p" "$TEST_DIR/inputs")
    [ -n "$FOLLOWUP_TEXT" ] || return 124
}
wait_or_run_followup_vad() { return 124; }
led_feedback_error() { :; }; sleep() { :; }
handle_llm_dialog same-session "$FIRST"
echo "END|calls=$calls|dedup=$SUPPRESS_DUP_SECONDS|sid=$CURRENT_SESSION_ID"
'''
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                    env={**os.environ, 'LC_ALL': 'C', 'FIRST': first, 'TEST_DIR': temp,
                                         'NATIVE_DIALOG_INPUT_GUARD': enabled, 'BOOT1': str(int(boot1)),
                                         'PROMPT_FAIL': str(int(prompt_failure)), 'LLM_FAIL': str(int(llm_failure))})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            return result.stdout.splitlines()

    def test_normal_followup_is_unchanged(self):
        self.assertEqual(self.dialog('介绍西湖', ['什么时候去']),
                         ['LLM|same-session|介绍西湖', 'LLM|same-session|什么时候去', 'CLEAN',
                          'END|calls=2|dedup=5|sid='])

    def test_wake_only_gets_ack_and_reopens_without_llm_turn(self):
        self.assertEqual(self.dialog('介绍西湖', ['小爱同学', '什么时候去']),
                         ['LLM|same-session|介绍西湖', 'PROMPT|我在，请说。',
                          'LLM|same-session|什么时候去', 'CLEAN', 'END|calls=3|dedup=5|sid='])

    def test_punctuated_wake_is_still_wake_only(self):
        result = self.dialog('介绍西湖', ['小爱同学！', '什么时候去'])
        self.assertIn('PROMPT|我在，请说。', result)
        self.assertNotIn('LLM|same-session|小爱同学！', result)

    def test_wake_with_question_is_not_discarded(self):
        result = self.dialog('介绍西湖', ['小爱同学，什么时候去'])
        self.assertIn('LLM|same-session|小爱同学，什么时候去', result)
        self.assertFalse(any(x.startswith('PROMPT') for x in result))

    def test_incomplete_first_question_waits_then_combines(self):
        self.assertEqual(self.dialog('呼叫DEEPSEEK帮我查一下', ['查询OKX这家公司']),
                         ['PROMPT|请继续说，要查什么？',
                          'LLM|same-session|呼叫DEEPSEEK帮我查一下，查询OKX这家公司',
                          'CLEAN', 'END|calls=2|dedup=5|sid='])

    def test_incomplete_followup_keeps_session(self):
        result = self.dialog('介绍西湖', ['帮我查一下', '明天的天气'])
        self.assertIn('LLM|same-session|帮我查一下，明天的天气', result)
        self.assertNotIn('LLM|same-session|帮我查一下', result)

    def test_complete_short_questions_and_references_are_not_delayed(self):
        for value in ['为什么', '那它呢', '解释一下', '帮我查一下天气', 'OK的创始人是', 'AGI是什么']:
            with self.subTest(value=value):
                result = self.dialog(value)
                self.assertIn('LLM|same-session|' + value, result)
                self.assertFalse(any(x.startswith('PROMPT') for x in result))

    def test_silence_after_prompt_exits_without_submitting_fragment(self):
        self.assertEqual(self.dialog('呼叫DeepSeek帮我查一下'),
                         ['PROMPT|请继续说，要查什么？', 'CLEAN', 'END|calls=1|dedup=5|sid='])

    def test_repeated_wake_is_bounded(self):
        result = self.dialog('介绍西湖', ['小爱同学'] * 5)
        self.assertEqual(sum(x.startswith('PROMPT') for x in result), 2)
        self.assertEqual(sum(x.startswith('LLM') for x in result), 1)
        self.assertIn('END|calls=3|dedup=5|sid=', result)

    def test_prompt_failure_does_not_start_capture(self):
        result = self.dialog('帮我查一下', ['明天的天气'], prompt_failure=True)
        self.assertIn('END|calls=0|dedup=5|sid=', result)
        self.assertFalse(any(x.startswith('LLM') for x in result))

    def test_llm_failure_does_not_start_capture(self):
        result = self.dialog('介绍西湖', ['下一句'], llm_failure=True)
        self.assertIn('END|calls=0|dedup=5|sid=', result)

    def test_switch_off_preserves_original_behavior(self):
        result = self.dialog('帮我查一下', enabled='0')
        self.assertIn('LLM|same-session|帮我查一下', result)
        self.assertFalse(any(x.startswith('PROMPT') for x in result))

    def test_boot0_does_not_apply_new_guard(self):
        result = self.dialog('帮我查一下', boot1=False)
        self.assertIn('LLM|same-session|帮我查一下', result)
        self.assertFalse(any(x.startswith('PROMPT') for x in result))

    def test_shell_metacharacters_remain_literal(self):
        value = '查一下$(echo BAD);`echo WRONG`'
        result = self.dialog('帮我查一下', [value])
        self.assertIn('LLM|same-session|帮我查一下，' + value, result)

    def test_pending_fragment_survives_one_wake_only_interruption(self):
        result = self.dialog('帮我查一下', ['小爱同学', 'OKX这家公司'])
        self.assertIn('LLM|same-session|帮我查一下，OKX这家公司', result)
        self.assertEqual(sum(x.startswith('PROMPT') for x in result), 2)

    def test_repeated_incomplete_fragments_do_not_accumulate(self):
        result = self.dialog('帮我查一下', ['帮我查询一下', 'OKX这家公司'])
        self.assertIn('LLM|same-session|帮我查询一下，OKX这家公司', result)
        self.assertEqual(sum(x.startswith('LLM') for x in result), 1)

    def test_silence_does_not_leak_fragment_to_later_session(self):
        code = functions('native_dialog_compact', 'classify_native_dialog_text',
                         'collect_native_dialog_text') + '''
NATIVE_DIALOG_INPUT_GUARD=1
log() { :; }; play_native_dialog_prompt() { :; }; wait_native_live_asr() { return 124; }
collect_native_dialog_text '帮我查一下'
echo "first=$?"
collect_native_dialog_text '介绍西湖'
printf 'next=%s\\n' "$NATIVE_DIALOG_TEXT"
'''
        result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout.splitlines(), ['first=124', 'next=介绍西湖'])

    def test_literal_prompt_does_not_call_llm_or_write_conversation(self):
        with tempfile.TemporaryDirectory() as temp:
            code = functions('play_native_dialog_prompt').replace('/tmp/native_first_input_prompt', temp) + r'''
set_state() { :; }; set_busy() { :; }; apply_llm_master_volume() { :; }
freeze_native_player() { :; }; led_feedback_llm_playing() { :; }; log() { :; }
TTS_ENGINE=device
stream_play_worker() {
    while [ ! -f "$1/done" ]; do sleep 0.01; done
    cat "$1/sentence"
}
stream_synthesize_sentence() { printf '%s\n' "$3" > "$1/sentence"; }
llm_build_messages() { echo UNEXPECTED_LLM; return 1; }
play_native_dialog_prompt '我在，请说。'
echo "rc=$?"
'''
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['我在，请说。', 'rc=0'])
