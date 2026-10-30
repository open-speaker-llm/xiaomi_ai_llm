"""Exercise client failure exits with real curl/FIFOs and isolated shell state."""
import contextlib
import http.server
import json
import os
import re
import signal
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def functions(*names):
    source = (ROOT / 'device/native_first_client.sh').read_text()
    return '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', source, re.M | re.S).group()
                     for name in names)


def shell(code, env, timeout=6):
    proc = subprocess.Popen(['sh', '-c', code], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env={**os.environ, **env}, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return proc.returncode, out, err


@contextlib.contextmanager
def audio_server(mode):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            body = b'R' * (44 if mode == 'header' else 80)
            if mode == '502':
                self.send_response(502)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(body) + (100 if mode == 'partial' else 0)))
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class HttpPlaybackFailureTest(unittest.TestCase):
    def run_tts(self, url, player='exec cat > "$PLAYED"', fallback='1', download_timeout=1):
        with tempfile.TemporaryDirectory() as temp:
            player_file = Path(temp, 'player')
            player_file.write_text('#!/bin/sh\necho $$ > "$TEST_DIR/player_pid"\n' + player + '\n')
            player_file.chmod(0o700)
            curl_file = Path(temp, 'curl')
            curl_file.write_text('#!/bin/sh\necho $$ > "$TEST_DIR/curl_pid"\nexec ' +
                                 shlex.quote(shutil.which('curl')) + ' "$@"\n')
            curl_file.chmod(0o700)
            code = functions('http_stream_play', 'tts_play_text') + r'''
TTS_ENGINE=server; STREAM_TIMEOUT=$TEST_STREAM_TIMEOUT; TTS_NATIVE_STATUS_MAX_SECONDS=1; LLM_VOLUME=1
log() { echo "$*"; }; tts_service_online() { return 0; }
resume_native_player() { :; }
native_tts_speak() { echo "NATIVE:$1"; [ "$NATIVE_FAIL" != 1 ]; }
wait_native_tts_playback() { echo NATIVE_DONE; }
tts_play_text answer
echo "RESULT=$?:BYTES=$HTTP_STREAM_BYTES:CURL=$CURL_PID:PLAYER=$APLAY_PID"
test ! -e "$HTTP_STREAM_DIR/fifo" || echo LEAKED_FIFO
'''
            env = {'TTS_SERVER': url, 'TTS_FALLBACK_NATIVE': fallback,
                   'TEST_DIR': temp, 'TEST_STREAM_TIMEOUT': str(download_timeout),
                   'PATH': temp + os.pathsep + os.environ['PATH'],
                   'HTTP_STREAM_DIR': temp + '/http', 'DIRAC_APLAY': str(player_file),
                   'DIRAC_PLAYBACK_LOG': temp + '/player.log', 'PLAYED': temp + '/played',
                   'NO_PROXY': '*', 'http_proxy': '', 'https_proxy': '', 'ALL_PROXY': ''}
            rc, out, err = shell(code, env)
            self.assertEqual(rc, 0, err)
            self.assertNotIn('LEAKED_FIFO', out)
            self.assertIn('CURL=:PLAYER=', out)
            for name in ('curl_pid', 'player_pid'):
                marker = Path(temp, name)
                if marker.exists():
                    with self.assertRaises(ProcessLookupError, msg='leaked ' + name):
                        os.kill(int(marker.read_text()), 0)
            return out

    def test_connection_refusal_after_health_check_is_bounded_and_falls_back(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        out = self.run_tts(f'http://127.0.0.1:{port}')
        self.assertIn('RESULT=0:BYTES=0', out)
        self.assertEqual(out.count('NATIVE:answer'), 1)

    def test_http_502_and_empty_wav_fall_back_once(self):
        for mode in ('502', 'header'):
            with self.subTest(mode=mode), audio_server(mode) as url:
                out = self.run_tts(url)
                self.assertIn('RESULT=0:', out)
                self.assertEqual(out.count('NATIVE:answer'), 1)

    def test_successful_http_audio_does_not_repeat_via_native(self):
        with audio_server('healthy') as url:
            out = self.run_tts(url)
        self.assertIn('RESULT=0:BYTES=80', out)
        self.assertNotIn('NATIVE:', out)

    def test_partial_audio_reports_failure_without_full_answer_replay(self):
        with audio_server('partial') as url:
            out = self.run_tts(url)
        self.assertIn('RESULT=1:BYTES=80', out)
        self.assertNotIn('NATIVE:', out)

    def test_player_failure_or_stall_is_bounded(self):
        for player in ('exit 17', 'exec sleep 10'):
            with self.subTest(player=player), audio_server('healthy') as url:
                out = self.run_tts(url, player=player, fallback='0')
                self.assertIn('RESULT=1:', out)
                self.assertNotIn('NATIVE:', out)

    def test_early_player_exit_cancels_download_without_waiting_for_network_timeout(self):
        with audio_server('healthy') as url:
            start = time.monotonic()
            out = self.run_tts(url, player='exit 17', fallback='0', download_timeout=180)
            self.assertLess(time.monotonic() - start, 2)
        self.assertIn('RESULT=1:', out)

    def test_disabled_fallback_propagates_http_error(self):
        with audio_server('502') as url:
            out = self.run_tts(url, fallback='0')
        self.assertIn('RESULT=1:', out)
        self.assertNotIn('NATIVE:', out)


class LlmCompletionTest(unittest.TestCase):
    def run_answer(self, ending='done', transport_rc=0, tts_rc=0):
        with tempfile.TemporaryDirectory() as temp:
            content = {'choices': [{'delta': {'content': '完整回答。'}}]}
            data = 'data: ' + json.dumps(content, ensure_ascii=False) + '\n'
            if ending == 'done':
                data += 'data: [DONE]\n'
            elif ending in ('stop', 'length'):
                data += 'data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': ending}]}) + '\n'
            Path(temp, 'response').write_text(data)
            code = functions('llm_direct_answer', 'llm_sse_content', 'send_text_native',
                             'cancel_followup_vad_prearm').replace('/tmp/native_first_llm_', temp + '/llm_') + r'''
LLM_API_KEY=test; LLM_API_BASE=http://unused; LLM_DIRECT_TIMEOUT=1
TTS_ENGINE=server; DEVICE_TTS_STREAM=0; FOLLOWUP_VAD_PID=; SUPPRESS_DUP_SECONDS=0
log() { echo "$*"; }; monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_build_messages() { echo request; }; llm_build_request() { echo request; }; json_escape() { cat; }
curl() { cat "$TEST_DIR/response"; return "$TRANSPORT_RC"; }
is_recent_duplicate_llm_query() { return 1; }; set_state() { :; }; record_llm_query() { :; }
set_busy() { :; }; apply_llm_master_volume() { :; }; freeze_native_player() { :; }
led_feedback_llm_playing() { :; }; led_feedback_error() { :; }; finish_llm_playback() { echo CLEAN; }; sleep() { :; }
tts_play_text() { echo "PLAY:$1"; return "$TTS_RC"; }
send_text_native session question normal
echo "RESULT=$?"
'''
            rc, out, err = shell(code, {'TEST_DIR': temp, 'LLM_HISTORY_DIR': temp + '/history',
                                       'FOLLOWUP_ARM_FILE': temp + '/arm',
                                       'TRANSPORT_RC': str(transport_rc), 'TTS_RC': str(tts_rc)})
            self.assertEqual(rc, 0, err)
            hist = Path(temp, 'history/session')
            return out, hist.read_text() if hist.exists() else ''

    def test_done_and_finish_reason_stop_are_supported(self):
        for ending in ('done', 'stop'):
            with self.subTest(ending=ending):
                out, history = self.run_answer(ending)
                self.assertIn('RESULT=0', out)
                self.assertIn('assistant\t完整回答。', history)

    def test_missing_or_truncated_completion_never_plays_or_commits(self):
        for ending, rc in (('missing', 0), ('length', 0), ('done', 28)):
            with self.subTest(ending=ending, rc=rc):
                out, history = self.run_answer(ending, rc)
                self.assertIn('RESULT=1', out)
                self.assertNotIn('PLAY:', out)
                self.assertEqual(history, '')

    def test_nonstream_playback_failure_never_commits_answer(self):
        out, history = self.run_answer(tts_rc=1)
        self.assertIn('RESULT=1', out)
        self.assertEqual(history, '')


class FollowupFailureTest(unittest.TestCase):
    def test_boot0_failed_first_answer_cancels_prearm_and_returns_idle(self):
        with tempfile.TemporaryDirectory() as temp:
            vad = Path(temp, 'vad.sh')
            vad.write_text('echo $$ > "$TEST_DIR/recorder_pid"\n'
                           'while [ ! -f "$VAD_ARM_FILE" ]; do sleep 0.02; done\n'
                           'echo unexpected-recording\nexit 124\n')
            code = functions('handle_llm_dialog', 'send_text_native', 'start_followup_vad_prearm',
                             'cancel_followup_vad_prearm') + r'''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=window; FOLLOWUP_PREARM=1
FOLLOWUP_VAD_PID=; FOLLOWUP_WINDOW_SECONDS=1; FOLLOWUP_TIMEOUT=1; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
SUPPRESS_DUP_SECONDS=0
is_system1_root() { return 1; }; log() { :; }; set_state() { echo "STATE:$1"; }
pause_native_asr() { :; }; resume_native_asr() { echo RESUMED; }; led_feedback_llm_accept() { :; }; led_off() { :; }
led_feedback_llm_playing() { :; }; led_feedback_error() { :; }; is_recent_duplicate_llm_query() { return 1; }
record_llm_query() { :; }; set_busy() { :; }; apply_llm_master_volume() { :; }; freeze_native_player() { :; }
monotonic_ms() { echo 1000; }; finish_llm_playback() { echo CLEAN; }
llm_stream_answer_and_play() {
    for attempt in 1 2 3 4 5; do [ -s "$TEST_DIR/recorder_pid" ] && break; sleep 0.02; done
    return 1
}
send_text_and_play() { send_text_native "$@"; }
wait_or_run_followup_vad() { echo UNEXPECTED_WAIT; return 124; }
handle_llm_dialog session question
recorder=$(cat "$TEST_DIR/recorder_pid")
kill -0 "$recorder" 2>/dev/null && echo LEAKED_RECORDER
echo "END:pid=$FOLLOWUP_VAD_PID:session=$CURRENT_SESSION_ID"
'''
            rc, out, err = shell(code, {'TEST_DIR': temp, 'VAD_SCRIPT': str(vad),
                                       'FOLLOWUP_ARM_FILE': temp + '/arm'})
            self.assertEqual(rc, 0, err)
            self.assertIn('STATE:IDLE', out)
            self.assertIn('RESUMED', out)
            self.assertIn('END:pid=:session=', out)
            self.assertNotIn('LEAKED_RECORDER', out)
            self.assertNotIn('UNEXPECTED_WAIT', out)
            self.assertNotIn('unexpected-recording', out)
