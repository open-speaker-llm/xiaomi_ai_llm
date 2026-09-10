"""Exercise the actual shell producer/consumer with deterministic TTS failures."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'device/native_first_client.sh').read_text()


def functions(*names):
    return '\n'.join(m.group() for name in names
                     if (m := re.search(r'^' + name + r'\(\) \{.*?^\}', SOURCE, re.M | re.S)))


class TtsSentenceRecoveryTest(unittest.TestCase):
    def run_stream(self, mode, fallback='1'):
        with tempfile.TemporaryDirectory() as temp:
            code = functions('llm_aplay', 'stream_synthesize_sentence', 'stream_play_worker',
                             'llm_stream_answer_and_play').replace('/tmp/native_first_stream', temp + '/stream')
            code += r'''
export TRACE="$TEST_DIR/trace"
DIRAC_PLAYBACK_LOG="$TEST_DIR/aplay.log"
DIRAC_APLAY="$TEST_DIR/no-helper"
mkdir -p "$TEST_DIR/history"
LLM_API_KEY=test; LLM_API_BASE=test; LLM_DIRECT_TIMEOUT=1
LLM_HISTORY_DIR="$TEST_DIR/history"
DEVICE_TTS_BIN=fake_tts; DEVICE_TTS_TIMEOUT=1; DEVICE_TTS_STREAM_RETRIES=2
DEVICE_TTS_PCM_RATE=24000; DEVICE_TTS_GAIN=1
DEVICE_TTS_GEC_VERSION=test; DEVICE_TTS_UA=; DEVICE_TTS_ORIGIN=; DEVICE_TTS_VOICE=test
log() { echo "$*"; }
monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
json_escape() { cat; }; llm_build_messages() { echo messages; }; llm_build_request() { echo request; }
curl() { printf '第一句。第二句。第三句。\n'; }; llm_sse_content() { cat; }
timeout() { shift 2; "$@"; }
fake_tts() {
    countfile="$TEST_DIR/count-$1"
    count=$(cat "$countfile" 2>/dev/null || echo 0); count=$((count+1)); echo "$count" > "$countfile"
    fail=0
    case "$MODE:$1:$count" in
        flaky:第二句。:1|permanent:第二句。:*|nativefail:第二句。:*|waitfail:第二句。:*|allfail:*|partial:第二句。:*|readerror:第二句。:*) fail=1 ;;
    esac
    if [ "$fail" = 1 ]; then
        echo '[!] injected synthesis error' >&2
        if [ "$MODE" = partial ]; then printf '残缺音频\n' > "$2"; fi
        if [ "$MODE" = readerror ]; then printf '残缺音频\n' > "$2"; echo '[!] read err: interrupted' >&2; return 0; fi
        return 3
    fi
    printf '%s\n' "$1" > "$2"
}
aplay() {
    for arg in "$@"; do fifo="$arg"; done
    while IFS= read -r line; do printf 'pcm:%s\n' "$line" >> "$TRACE"; done < "$fifo"
    echo drained >> "$TRACE"
    [ "$MODE" != playfail ]
}
resume_native_player() { echo resume >> "$TRACE"; }
freeze_native_player() { echo freeze >> "$TRACE"; }
native_tts_speak() { echo "native:$1" >> "$TRACE"; [ "$MODE" != nativefail ]; }
wait_native_tts_status() { echo native_done >> "$TRACE"; [ "$MODE" != waitfail ]; }
wait_native_tts_playback() { echo native_done >> "$TRACE"; }
llm_stream_answer_and_play session question 1000
rc=$?
echo "RESULT=$rc"
'''
            result = subprocess.run(['sh', '-c', code], text=True, capture_output=True, timeout=20,
                                    env={**os.environ, 'LC_ALL': 'C', 'TEST_DIR': temp, 'MODE': mode,
                                         'TTS_FALLBACK_NATIVE': fallback})
            self.assertEqual(result.returncode, 0, result.stderr)
            trace = Path(temp, 'trace')
            history = Path(temp, 'history/session')
            count = Path(temp, 'count-第二句。')
            return (result.stdout, trace.read_text().splitlines() if trace.exists() else [],
                    history.read_text() if history.exists() else '',
                    int(count.read_text()) if count.exists() else 0)

    def test_healthy_stream_stays_in_one_pcm_player(self):
        out, trace, history, count = self.run_stream('healthy')
        self.assertIn('RESULT=0', out)
        self.assertEqual(trace, ['pcm:第一句。', 'pcm:第二句。', 'pcm:第三句。', 'drained'])
        self.assertEqual(count, 1)
        self.assertIn('assistant\t第一句。第二句。第三句。', history)

    def test_transient_middle_sentence_is_retried_once_without_duplicate(self):
        out, trace, _, count = self.run_stream('flaky')
        self.assertEqual(count, 2)
        self.assertEqual(trace, ['pcm:第一句。', 'pcm:第二句。', 'pcm:第三句。', 'drained'])
        self.assertIn('RESULT=0', out)

    def test_exhausted_middle_sentence_drains_then_falls_back_in_order(self):
        out, trace, history, count = self.run_stream('permanent')
        self.assertEqual(count, 3)
        self.assertEqual(trace, ['pcm:第一句。', 'drained', 'resume', 'native:第二句。',
                                 'native_done', 'freeze', 'pcm:第三句。', 'drained'])
        self.assertIn('RESULT=0', out)
        self.assertIn('assistant\t第一句。第二句。第三句。', history)

    def test_all_sentences_fall_back_once_without_full_answer_replay(self):
        out, trace, _, _ = self.run_stream('allfail')
        self.assertEqual([x for x in trace if x.startswith('native:')],
                         ['native:第一句。', 'native:第二句。', 'native:第三句。'])
        self.assertIn('RESULT=0', out)

    def test_disabled_fallback_reports_failure_and_does_not_claim_answer_in_history(self):
        out, trace, history, _ = self.run_stream('permanent', fallback='0')
        self.assertIn('RESULT=1', out)
        self.assertEqual(trace, ['pcm:第一句。', 'drained'])
        self.assertEqual(history, '')

    def test_failed_native_fallback_stops_and_does_not_claim_answer_in_history(self):
        out, trace, history, _ = self.run_stream('nativefail')
        self.assertIn('RESULT=1', out)
        self.assertNotIn('pcm:第三句。', trace)
        self.assertEqual(trace[-1], 'freeze')
        self.assertEqual(history, '')

    def test_native_wait_failure_stops_before_next_sentence(self):
        out, trace, history, _ = self.run_stream('waitfail')
        self.assertIn('RESULT=1', out)
        self.assertNotIn('pcm:第三句。', trace)
        self.assertEqual(trace[-1], 'freeze')
        self.assertEqual(history, '')

    def test_pcm_player_failure_is_propagated(self):
        out, _, history, _ = self.run_stream('playfail')
        self.assertIn('RESULT=1', out)
        self.assertEqual(history, '')

    def test_partial_file_from_failed_command_is_never_played(self):
        out, trace, _, count = self.run_stream('partial')
        self.assertEqual(count, 3)
        self.assertNotIn('pcm:残缺音频', trace)
        self.assertIn('native:第二句。', trace)
        self.assertIn('RESULT=0', out)

    def test_ettsc_read_error_with_zero_exit_is_not_treated_as_success(self):
        out, trace, _, count = self.run_stream('readerror')
        self.assertEqual(count, 3)
        self.assertNotIn('pcm:残缺音频', trace)
        self.assertIn('native:第二句。', trace)
        self.assertIn('RESULT=0', out)


class NativeSentenceWaitTest(unittest.TestCase):
    def wait_status(self, statuses, end=12, strict='1'):
        with tempfile.TemporaryDirectory() as temp:
            code = functions('wait_native_tts_status') + r'''
TTS_NATIVE_WAIT_ENABLED=0; TTS_NATIVE_STATUS_WAIT_ENABLED=0
TTS_NATIVE_STATUS_START_TIMEOUT_SECONDS=2
TTS_NATIVE_STATUS_IDLE_HITS=2; TTS_NATIVE_STATUS_POLL_SECONDS=0
log() { echo "$*"; }; led_native_shut_all() { :; }; sleep() { :; }
echo 0 > "$TEST_DIR/now"
date() { cat "$TEST_DIR/now"; }
native_tts_player_status() {
    now=$(cat "$TEST_DIR/now"); now=$((now+1)); echo "$now" > "$TEST_DIR/now"
    sed -n "${now}p" "$TEST_DIR/statuses"
}
wait_native_tts_status sentence "$STRICT"
echo "RESULT=$?"
echo "STATUS_READS=$(cat "$TEST_DIR/now")"
'''
            Path(temp, 'statuses').write_text('\n'.join(statuses) + '\n')
            return subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5,
                                  env={**os.environ, 'TEST_DIR': temp, 'STRICT': strict,
                                       'TTS_NATIVE_STATUS_MAX_SECONDS': str(end)}).stdout

    def test_strict_mode_requires_observed_start_even_when_wait_switches_disabled(self):
        self.assertIn('RESULT=1', self.wait_status(['0'] * 10))

    def test_strict_mode_does_not_treat_unknown_or_paused_status_as_finished(self):
        out = self.wait_status(['1', '', '', '2', '2', '0', '0'])
        self.assertIn('finished by status', out)
        self.assertIn('STATUS_READS=7', out)
        self.assertIn('RESULT=0', out)

    def test_strict_playback_timeout_is_failure(self):
        self.assertIn('RESULT=1', self.wait_status(['1'] * 10, end=4))

    def test_strict_unknown_status_after_start_times_out(self):
        self.assertIn('RESULT=1', self.wait_status(['1', '', '', '', ''], end=4))

    def test_legacy_disabled_wait_is_unchanged(self):
        self.assertEqual(self.wait_status([], strict='0'), 'RESULT=0\nSTATUS_READS=0\n')
