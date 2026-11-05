"""TTS 预连接的队列集成、失败回退和进程回收；不使用设备或云端。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_latency_trace import HELPERS, functions

PREWARM = ('tts_prewarm_init', 'tts_prewarm_start', 'tts_prewarm_take', 'tts_prewarm_stop')
FAKE = r'''
import os, pathlib, signal, sys, time
root = pathlib.Path(os.environ['TEST_DIR'])
mode = os.environ['MODE']
def event(text):
    with (root / 'events').open('a') as f: f.write(text + '\n')
if sys.argv[1] == 'prewarm':
    job = pathlib.Path(sys.argv[2])
    (root / 'worker_pid').write_text(str(os.getpid()))
    event('connect')
    if mode == 'fail':
        (job / 'done').write_text('1'); sys.exit(2)
    time.sleep(.05)  # Text may arrive before the handshake finishes.
    (job / 'ready').touch()
    while not (job / 'request').exists():
        if (job / 'cancel').exists(): sys.exit(2)
        time.sleep(.01)
    event('prewarm-turn')
    if mode == 'hang':
        while True: time.sleep(.05)
    if mode in ('partial', 'allfail'):
        print('[!] incomplete')
        (job / 'audio.part').write_bytes(b'P'*1024)
        (job / 'done').write_text('1'); sys.exit(2)
    (job / 'audio.pcm').write_bytes(b'A'*1024)
    (job / 'done').write_text('0')
else:
    event('normal-turn')
    if mode == 'allfail': sys.exit(2)
    char = b'A' if sys.argv[1] == '正常回答。' else b'B'
    pathlib.Path(sys.argv[2]).write_bytes(char*1024)
'''


class TtsPrewarmTest(unittest.TestCase):
    def pipeline(self, enabled=1, mode='ok', shell=None, body='', settings=''):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'fake-ettsc'
            binary.write_text('#!' + sys.executable + '\n' + FAKE)
            binary.chmod(0o700)
            (root / 'uptime').write_text('1.50 0\n')
            code = functions(*HELPERS, *PREWARM, 'llm_stream_answer_and_play',
                             'stream_synthesize_sentence', 'stream_play_worker')
            code = code.replace('/tmp/native_first_stream', temp + '/stream').replace('/proc/uptime', temp + '/uptime')
            code += r'''
LATENCY_TRACE_ENABLED=0; LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
DEVICE_TTS_PREWARM="$ENABLED"; LLM_API_KEY=sk-test; LLM_WEB_FILLER='搜索中，请稍等。'
DEVICE_TTS_BIN="$TEST_DIR/fake-ettsc"; DEVICE_TTS_VOICE=voice-a
DEVICE_TTS_PCM_RATE=24000; DEVICE_TTS_GAIN=1; DEVICE_TTS_TIMEOUT=1
DEVICE_TTS_STREAM_RETRIES=1; TTS_FALLBACK_NATIVE=0
log() { printf '%s\n' "$*"; }; monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_build_messages() { echo fake-request; }
llm_history_commit() { printf '%s\n' "$3" >> "$TEST_DIR/history"; }
timeout() { shift 2; "$@"; }
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
llm_sse_content() { cat; printf complete > "$1"; }
llm_open_stream() {
    # The experiment has already been launched when the model request begins.
    if [ "$DEVICE_TTS_PREWARM" = 1 ] && [ "$LLM_PIPELINE" = native ] &&
        [ "$TTS_ENGINE" = device ] && [ "$DEVICE_TTS_STREAM" = 1 ]; then
        [ -d "$TTS_PREWARM_DIR" ] || return 1
        printf launched > "$TEST_DIR/launched-before-model"
    fi
    [ "$MODE" != empty ] || { sleep .1; return 0; }
    printf '正常回答。\n第二句话。\n'
}
tts_prewarm_init
llm_stream_answer_and_play session question 1000
printf 'RESULT=%s\n' "$?"
'''
            code = code.replace('tts_prewarm_init\nllm_stream_answer_and_play', settings + '\ntts_prewarm_init\nllm_stream_answer_and_play')
            code += body
            run = subprocess.run((shell or ['sh']) + ['-c', code],
                                 env={**os.environ, 'TEST_DIR': temp, 'ENABLED': str(enabled), 'MODE': mode, 'LC_ALL': 'C'},
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            if (root / 'worker_pid').exists():
                with self.assertRaises(ProcessLookupError, msg='owned prewarm worker was not reaped'):
                    os.kill(int((root / 'worker_pid').read_text()), 0)
            self.assertEqual(list((root / 'stream').glob('prewarm.*')), [], 'private IPC directory leaked')
            read = lambda name: (root / name).read_text() if (root / name).exists() else ''
            return run.stdout, read('events').splitlines(), read('played'), read('history'), read('launched-before-model')

    def test_preconnected_first_turn_keeps_pcm_history_and_order(self):
        on = self.pipeline()
        off = self.pipeline(enabled=0)
        self.assertIn('RESULT=0', on[0])
        self.assertIn('[TTS] prewarm hit', on[0])
        self.assertEqual(on[1], ['connect', 'prewarm-turn', 'normal-turn'])
        self.assertEqual(off[1], ['normal-turn', 'normal-turn'])
        self.assertEqual(on[2:4], off[2:4])
        self.assertEqual(on[2], 'A'*1024+'B'*1024)
        self.assertEqual(on[3], '正常回答。第二句话。\n')
        self.assertEqual(on[4], 'launched')
        self.assertEqual(off[4], '')

    def test_failure_partial_and_timeout_use_original_synthesis(self):
        for mode in ('fail', 'partial', 'hang'):
            with self.subTest(mode=mode):
                out, events, audio, history, _ = self.pipeline(mode=mode)
                self.assertIn('RESULT=0', out)
                self.assertNotIn('[TTS] prewarm hit', out)
                self.assertEqual(events.count('normal-turn'), 2)
                self.assertEqual(audio, 'A'*1024+'B'*1024)
                self.assertEqual(history, '正常回答。第二句话。\n')

    def test_empty_model_result_reaps_unused_worker(self):
        out, events, audio, history, _ = self.pipeline(mode='empty')
        self.assertIn('RESULT=1', out)
        self.assertIn(events, ([], ['connect']))
        self.assertEqual((audio, history), ('', ''))

    def test_original_retries_still_apply_when_prewarm_and_normal_tts_fail(self):
        out, events, audio, history, _ = self.pipeline(mode='allfail')
        self.assertIn('RESULT=1', out)
        self.assertEqual(events.count('normal-turn'), 4)
        self.assertEqual((audio, history), ('', ''))

    def test_invalid_flag_warns_and_keeps_default_behavior(self):
        out, events, audio, history, _ = self.pipeline(enabled='bad')
        self.assertEqual(out.count('invalid DEVICE_TTS_PREWARM'), 1)
        self.assertIn('RESULT=0', out)
        self.assertEqual(events, ['normal-turn', 'normal-turn'])

    def test_zero_padded_timeout_keeps_decimal_seconds(self):
        result = self.pipeline(settings='DEVICE_TTS_TIMEOUT=08')
        self.assertIn('RESULT=0', result[0])
        self.assertIn('[TTS] prewarm hit', result[0])

    def test_other_routes_do_not_launch_a_worker(self):
        for settings in ('TTS_ENGINE=server', 'LLM_PIPELINE=server', 'DEVICE_TTS_STREAM=0'):
            with self.subTest(settings=settings):
                out, events, audio, history, _ = self.pipeline(settings=settings)
                self.assertIn('RESULT=0', out)
                self.assertEqual(events, ['normal-turn', 'normal-turn'])
                self.assertEqual(audio, 'A'*1024+'B'*1024)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash unavailable on host')
    def test_busybox_prewarm_and_cleanup(self):
        result = self.pipeline(shell=[shutil.which('busybox'), 'ash'])
        self.assertIn('RESULT=0', result[0])


if __name__ == '__main__':
    unittest.main()
