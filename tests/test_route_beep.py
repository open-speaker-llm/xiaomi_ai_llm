"""S30 cue and answer PCM slots with a single stubbed player."""
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_latency_trace import HELPERS, functions
from tools.route_beep_calibration import difference_db, rms


class RouteBeepTest(unittest.TestCase):
    def run_round(self, mode, enabled='1', followup='0', asset=b'BB', trace='1', builtin=False, gain='1.0'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            if asset is not None:
                (root / 'beep.pcm').write_bytes(asset)
            names = ('handle_wakeup', 'handle_llm_dialog', 'send_text_native',
                     'llm_stream_answer_and_play', 'stream_play_worker', 'freeze_native_player',
                     'native_route_beep_gate', 'native_route_wait_quiet')
            beep = ('init', 'prepare', 'default_pcm', 'scale', 'worker', 'allowed',
                    'begin', 'fire', 'end', 'step', 'mix', 'write_voice')
            code = functions(*HELPERS, *names, *('route_beep_' + name for name in beep))
            for src, dst in (('/tmp/native_first_stream', '/stream'),
                             ('/tmp/native_first_latency.log', '/latency'),
                             ('/tmp/native_first_marks.', '/pending.'),
                             ('/tmp/native_first_beep.', '/cue.'), ('/proc/uptime', '/uptime')):
                code = code.replace(src, temp + dst)
            (root / 'uptime').write_text('1.00 0\n')
            code += r'''
LATENCY_TRACE_ENABLED="$TRACE"; LATENCY_LOG_MAX_LINES=200
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
LLM_API_KEY=sk-test; DEVICE_TTS_PCM_RATE=24000
[ "$BUILTIN" = 1 ] || LLM_ROUTE_BEEP_FILE="$TEST_DIR/beep.pcm"
PLAYER_FROZEN_MARKER="$TEST_DIR/frozen"; FREEZE_NATIVE_PLAYER_ON_FALLBACK=1
NATIVE_WAIT_SECONDS=0.01; NATIVE_POLL_INTERVAL=0.01
LLM_WEB_FILLER='搜索中，请稍等。'
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=native_multirounds
log() { printf '%s\n' "$*"; }
killall() {
    if [ "$MODE" = early_failure ] && [ ! -f "$TEST_DIR/frozen" ]; then
        until [ -f "$TEST_DIR/cue_received" ]; do sleep 0.01; done
    fi
    if [ "$MODE" = native_speak ] && [ ! -f "$TEST_DIR/native_finished" ]; then
        : > "$TEST_DIR/early"
    fi
    [ "$MODE" != freeze_failed ]
}
TTS_NATIVE_STATUS_START_TIMEOUT_SECONDS=3; TTS_NATIVE_STATUS_MAX_SECONDS=8
TTS_NATIVE_STATUS_IDLE_HITS=2; TTS_NATIVE_STATUS_POLL_SECONDS=0.01
native_tts_player_status() {
    if [ "$MODE" != native_speak ]; then echo 0; return; fi
    if [ ! -f "$TEST_DIR/native_started" ]; then
        : > "$TEST_DIR/native_started"
        echo 1
    else
        : > "$TEST_DIR/native_finished"
        echo 0
    fi
}
timeout() { shift 2; "$@"; }
apply_llm_master_volume() { : > "$TEST_DIR/master"; }
monotonic_ms() {
    if [ "$MODE" = builtin_pacing ]; then
        python3 -c 'import time; print(time.monotonic_ns() // 1000000)'
        return
    fi
    echo 1000
}
elapsed_s() { echo 0; }
new_llm_session_id() { NEW_LLM_SESSION_ID=stub; }
select_native_result_source() { echo stub; }
get_native_result() {
    [ "$MODE" != no_result ] || return 1
    RESULT_TS=1; RESULT_DOMAIN=stub; RESULT_QUERY=fixture
    if [ "$MODE" = early_failure ]; then
        RESULT_SOURCE=aivs_lab_early_failure
        RESULT_SPEAK='[failure Speak suppressed before dispatch]'
    elif [ "$MODE" = native_speak ]; then
        RESULT_SOURCE=aivs_lab_instruction
        RESULT_SPEAK='fixture native speech'
    fi
}
is_system1_root() { return 1; }
is_ignored_query_result() { return 1; }
is_unsupported_result() { [ "$MODE" != native ]; }
is_native_success_domain() { [ "$MODE" = native ]; }
is_recent_duplicate_llm_query() { return 1; }
is_followup_exit_command() { return 1; }
is_followup_reset_command() { return 1; }
get_aivs_lab_latest_dialog_id() { echo stub; }
wait_native_followup_text() {
    [ "$MODE" = followup ] && [ ! -f "$TEST_DIR/followup" ] || return 1
    : > "$TEST_DIR/followup"; FOLLOWUP_TEXT=followup
}
send_text_and_play() { send_text_native "$@"; }
for stub in set_state set_busy record_llm_query finish_llm_playback \
    resume_native_player pause_native_asr resume_native_asr led_feedback_native_listening \
    led_feedback_llm_followup_listening \
    led_feedback_followup_asr_ok led_feedback_error led_off handle_native_success_speak \
    native_followup_mark_multirounds; do eval "$stub() { :; }"; done
led_feedback_llm_accept() {
    [ "$LLM_ROUTE_BEEP" != 1 ] || [ -f "$TEST_DIR/master" ] || : > "$TEST_DIR/early"
    echo accept >> "$TEST_DIR/led"
}
led_feedback_llm_playing() { echo playing >> "$TEST_DIR/led"; }
llm_build_messages() { echo stub; }
llm_open_stream() {
    : > "$TEST_DIR/request"
    [ "$MODE" != builtin_pacing ] || sleep 0.80
    printf '%s\n' "$LLM_WEB_FILLER" '回答。'
}
llm_sse_content() { cat; command sleep 0.15; printf complete > "$1"; }
llm_history_commit() { :; }
stream_synthesize_sentence() {
    if [ "$MODE" = overlap ] && [ "$3" = "$LLM_WEB_FILLER" ]; then
        head -c 9600 /dev/zero > "$1/$2.pcm"
    elif [ "$3" = "$LLM_WEB_FILLER" ]; then
        printf FF > "$1/$2.pcm"
    else
        printf AA > "$1/$2.pcm"
    fi
}
llm_aplay() {
    local fifo arg
    for arg do fifo="$arg"; done
    [ -f "$TEST_DIR/master" ] || : > "$TEST_DIR/early"
    if [ "$MODE" != early_failure ]; then
        [ -f "$PLAYER_FROZEN_MARKER" ] || : > "$TEST_DIR/early"
    fi
    printf '%s\n' open >> "$TEST_DIR/players"
    exec 9<"$fifo"
    dd bs=2 count=1 <&9 >> "$TEST_DIR/played" 2>/dev/null
    : > "$TEST_DIR/cue_received"
    cat <&9 >> "$TEST_DIR/played"
}
if command -v route_beep_init >/dev/null; then
    LLM_ROUTE_BEEP="${LLM_ROUTE_BEEP:-1}"
    LLM_ROUTE_BEEP_FOLLOWUP="${LLM_ROUTE_BEEP_FOLLOWUP:-0}"
    LLM_ROUTE_BEEP_FILE="${LLM_ROUTE_BEEP_FILE:-builtin}"
    route_beep_init
fi
handle_wakeup 1
route_beep_end
exit 0
'''
            result = subprocess.run(
                ['sh', '-c', code], capture_output=True, text=True, timeout=10,
                env={**os.environ, 'TEST_DIR': temp, 'MODE': mode, 'TRACE': trace,
                     'LLM_ROUTE_BEEP': enabled, 'LLM_ROUTE_BEEP_FOLLOWUP': followup,
                     'BUILTIN': str(int(builtin)), 'LLM_ROUTE_BEEP_FILE': '',
                     'LLM_ROUTE_BEEP_GAIN': gain})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertFalse((root / 'early').exists())
            played = (root / 'played').read_bytes() if (root / 'played').exists() else b''
            led = (root / 'led').read_text().splitlines() if (root / 'led').exists() else []
            if mode == 'overlap':
                self.assertEqual((root / 'players').read_text().splitlines(), ['open'])
            return played, result.stdout, led

    def test_wake_beep_precedes_ready_filler_and_answer(self):
        audio, log, led = self.run_round('wake')
        self.assertEqual(audio, b'BBFFAA')
        self.assertEqual(led, ['accept'])
        self.assertIn('wake→led_green=0.000', log)
        self.assertIn('wake→beep=0.000 beep=played', log)

    def test_builtin_matches_generator_and_uses_default_switches(self):
        generator = Path(__file__).resolve().parents[1] / 'scripts/embed_route_beep.py'
        with tempfile.TemporaryDirectory() as temp:
            generated = Path(temp) / 'default.pcm'
            subprocess.run([sys.executable, str(generator), '--pcm', str(generated)], check=True)
            pcm = generated.read_bytes()
        self.assertEqual(len(pcm), 15840)
        self.assertEqual(pcm[:5760], pcm[10080:])
        self.assertEqual(pcm[5760:10080], bytes(4320))
        peak = max(abs(sample) for (sample,) in struct.iter_unpack('<h', pcm))
        self.assertAlmostEqual(difference_db(peak, 32767), -3, places=2)
        # RMS of two complete S28b reference answer segments at the existing
        # native TTS gain. Keep scalar measurements only, not the speech.
        for reference in (4487.61, 4257.37):
            self.assertLessEqual(abs(difference_db(rms(pcm), reference)), 3)
        audio, _, _ = self.run_round('builtin_pacing', enabled='', followup='', builtin=True)
        self.assertEqual(audio, pcm + b'FFAA')

    def test_off_preserves_pcm_sequence(self):
        audio, log, _ = self.run_round('wake', enabled='0')
        self.assertEqual(audio, b'FFAA')
        self.assertIn('wake→beep=- beep=off', log)

    def test_native_and_no_result_do_not_start_a_player(self):
        for mode in ('native', 'no_result'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_round(mode)[0], b'')

    def test_followup_defaults_off_and_can_be_enabled(self):
        self.assertEqual(self.run_round('followup')[0], b'BBFFAAFFAA')
        self.assertEqual(self.run_round('followup', followup='1')[0], b'BBFFAABBFFAA')

    def test_missing_and_invalid_assets_skip_without_losing_answer(self):
        for asset in (None, b'odd', b'RIFF' + bytes(44)):
            with self.subTest(asset=asset):
                audio, log, _ = self.run_round('wake', asset=asset)
                self.assertEqual(audio, b'FFAA')
                self.assertIn('wake→beep=- beep=skipped', log)

    def test_beep_runs_without_latency_tracing(self):
        self.assertEqual(self.run_round('wake', trace='0')[0], b'BBFFAA')

    def test_suppressed_early_failure_can_play_before_freeze(self):
        audio, log, led = self.run_round('early_failure')
        self.assertEqual(audio, b'BBFFAA')
        self.assertIn('beep=played', log)
        self.assertEqual(led, ['accept'])

    def test_gain_scales_pcm_without_changing_answer(self):
        audio, _, _ = self.run_round('wake', asset=b'\x00\x40', gain='0.5')
        self.assertEqual(audio, b'\x00\x20FFAA')

    def test_dispatched_native_speech_finishes_before_first_freeze(self):
        audio, log, led = self.run_round('native_speak')
        self.assertEqual(audio, b'BBFFAA')
        self.assertIn('beep=played', log)
        self.assertEqual(led, ['accept'])

    def test_long_cue_fades_into_first_voice_without_opening_a_second_player(self):
        cue = struct.pack('<h', 1000) * 31200
        audio, log, _ = self.run_round('overlap', asset=cue)
        self.assertIn('beep_overlap=1', log)
        self.assertLess(len(audio), len(cue) + 9602)
        self.assertTrue(audio.endswith(bytes(4800) + b'AA'))
        self.assertEqual(len(audio) % 2, 0)

    def test_failed_freeze_skips_beep(self):
        audio, log, _ = self.run_round('freeze_failed')
        self.assertEqual(audio, b'FFAA')
        self.assertIn('wake→beep=- beep=skipped', log)
