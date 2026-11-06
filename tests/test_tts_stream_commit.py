"""First-body PCM commit, ordered playback and retry safety with local stubs."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_latency_trace import HELPERS, functions


class StreamCommitTest(unittest.TestCase):
    def run_round(self, mode, enabled=1, shell=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'uptime').write_text('1.00 0\n')
            code = functions(*HELPERS, 'llm_stream_answer_and_play', 'stream_synthesize_sentence',
                             'stream_play_worker', 'stream_pcm_matches')
            for src, dst in (('/tmp/native_first_stream', temp + '/stream'),
                             ('/proc/uptime', temp + '/uptime'),
                             ('/tmp/native_first_latency.log', temp + '/latency')):
                code = code.replace(src, dst)
            code += r'''
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1; DEVICE_TTS_PCM_RATE=24000
DEVICE_TTS_STREAM_COMMIT="$ENABLED"; DEVICE_TTS_STREAM_MIN_MS=300; DEVICE_TTS_STREAM_RETRIES=1
DEVICE_TTS_BIN=fake_ettsc; DEVICE_TTS_TIMEOUT=10; TTS_FALLBACK_NATIVE=1
[ "$MODE" != warm_retry ] || DEVICE_TTS_PREWARM=1
tts_prewarm_start() { :; }
tts_prewarm_take() {
    [ -n "$live_path" ] || return 1
    live_queued=1
    ETTSC_STREAM_PCM="$live_path" fake_ettsc "$3" "$1/$2.prewarm"
}
LLM_API_KEY=sk-test; LLM_WEB_FILLER='搜索中，请稍等。'
LATENCY_TRACE_ENABLED=1; LATENCY_LOG_MAX_LINES=200
monotonic_ms() { if [ -f "$TEST_DIR/starve" ]; then echo 2000; else echo 1000; fi; }; elapsed_s() { echo 0; }
log() { printf '%s\n' "$*"; }
llm_build_messages() { echo stub; }
llm_open_stream() {
    LLM_WEB_ACTION=search
    printf '%s\n' "$LLM_WEB_FILLER" '正文第一段。' '正文第二段。'
}
llm_sse_content() { cat; echo complete > "$1"; }
llm_history_commit() { printf '%s' "$3" > "$TEST_DIR/history"; }
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
timeout() { shift 2; "$@"; }
write_pcm() { awk -v n="$1" -v c="$2" 'BEGIN {for(i=0;i<n;i++) printf "%s",c}'; }
fake_ettsc() {
    case "$1" in
        "$LLM_WEB_FILLER") [ -z "$ETTSC_STREAM_PCM" ] || return 1; printf FF > "$2";;
        '正文第二段。') [ -z "$ETTSC_STREAM_PCM" ] || return 1; printf CC > "$2";;
        *)
            if [ -z "$ETTSC_STREAM_PCM" ]; then
                char=A; [ "$MODE" != mismatch ] || char=X
                { write_pcm 14400 "$char"; printf BB; } > "$2"
                return
            fi
            echo 1000 > "${ETTSC_STREAM_PCM%.live}.first_pcm"
            write_pcm 7200 A > "$ETTSC_STREAM_PCM"
            sleep 0.13
            [ "$(wc -c < "$TEST_DIR/played")" -eq 2 ] || : > "$TEST_DIR/below-threshold"
            write_pcm 7200 A >> "$ETTSC_STREAM_PCM"
            i=0
            while [ "$i" -lt 60 ]; do
                if [ "$(wc -c < "$TEST_DIR/played")" -eq 14402 ]; then
                    : > "$TEST_DIR/early"
                    break
                fi
                sleep 0.02; i=$((i+1))
            done
            if [ "$MODE" = starve ]; then
                sleep 0.12
                : > "$TEST_DIR/starve"
                sleep 0.20
            elif [ "$MODE" != success ]; then
                return 1
            fi
            printf BB >> "$ETTSC_STREAM_PCM";;
    esac
}
native_tts_speak() { : > "$TEST_DIR/native"; }
wait_native_tts_status() { :; }
resume_native_player() { :; }
freeze_native_player() { :; }
: > "$TEST_DIR/played"
llm_stream_answer_and_play sid question 1000
rc=$?
latency_report
exit "$rc"
'''
            result = subprocess.run((shell or ['sh']) + ['-c', code], capture_output=True, text=True,
                                    env={**os.environ, 'TEST_DIR': temp, 'MODE': mode,
                                         'ENABLED': str(enabled), 'LC_ALL': 'C'}, timeout=10)
            self.assertEqual(result.stderr, '')
            return result, (root / 'played').read_text(), {p.name for p in root.iterdir()}

    def test_threshold_and_first_body_only(self):
        result, audio, events = self.run_round('success')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('below-threshold', events)
        self.assertIn('early', events)
        self.assertEqual(audio, 'FF' + 'A' * 14400 + 'BBCC')
        self.assertIn('tts1_first=0.000', result.stdout)

    def test_off_preserves_complete_segment_playback(self):
        result, audio, events = self.run_round('success', enabled=0)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('early', events)
        self.assertEqual(audio, 'FF' + 'A' * 14400 + 'BBCC')

    def test_retry_appends_only_the_unplayed_suffix(self):
        for mode in ('retry', 'warm_retry'):
            with self.subTest(mode=mode):
                result, audio, events = self.run_round(mode)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn('early', events)
                self.assertEqual(audio, 'FF' + 'A' * 14400 + 'BBCC')
                self.assertIn('stream_commit_abort', result.stdout)

    def test_mismatched_retry_never_replays_or_saves_partial_answer(self):
        result, audio, events = self.run_round('mismatch')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(audio, 'FF' + 'A' * 14400)
        self.assertIn('stream_commit_abort', result.stdout)
        self.assertNotIn('native', events)
        self.assertNotIn('history', events)

    def test_starvation_counts_once_without_injecting_pcm(self):
        result, audio, _ = self.run_round('starve')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(audio, 'FF' + 'A' * 14400 + 'BBCC')
        self.assertEqual(result.stdout.count('[TTS] player_underrun'), 1)
        self.assertIn('player_underrun=1', result.stdout)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash unavailable on host')
    def test_busybox_commit_and_retry(self):
        result, audio, events = self.run_round('retry', shell=[shutil.which('busybox'), 'ash'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(audio, 'FF' + 'A' * 14400 + 'BBCC')
        self.assertIn('early', events)
