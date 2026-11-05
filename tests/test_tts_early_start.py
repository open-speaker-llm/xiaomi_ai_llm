"""Verify early work overlaps ASR/planning without speaking before authorization."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.native_protocol_helpers import embedded_protocol, embedded_web
from tests.test_latency_trace import HELPERS, functions
from tests.test_tts_persistent import PERSISTENT

EARLY = ('tts_early_filler_start', 'tts_early_filler_pending', 'tts_early_filler_publish')
FAKE = r'''
import os, pathlib, shutil, sys, time
root=pathlib.Path(os.environ['TEST_DIR']); mode=os.environ['MODE']
def event(v):
    with (root/'events').open('a') as f: f.write(v+'\n')
if sys.argv[1]=='serve':
    d=pathlib.Path(sys.argv[2]); event('connect-start'); time.sleep(.12)
    (d/'ready').touch(); event('connect-ready')
    if mode=='restart' and not (root/'restarted').exists():
        (root/'restarted').touch(); (d/'exited').write_text('1'); sys.exit(2)
    while True:
        for job in d.glob('job.*'):
            if not (job/'queued').exists(): continue
            (job/'queued').unlink()
            filler=(job/'request').read_text()=='搜索中，请稍等。'
            if not filler and mode=='cleanup-race':
                for old in d.glob('job.*'):
                    if (old/'started').exists(): shutil.rmtree(old)
            event('filler-start' if filler else 'answer-start')
            if filler and mode=='hang':
                while not (job/'cancel').exists(): time.sleep(.01)
                (d/'busy').unlink(missing_ok=True); shutil.rmtree(job); continue
            time.sleep(.12 if filler else .02)
            status='1' if filler and mode=='partial' else '0'
            if status=='0': (job/'audio.pcm').write_bytes((b'F' if filler else b'A')*1024)
            else: (job/'audio.part').write_bytes(b'P'*1024)
            (job/'worker.log').write_text('[T] tcp_ms=- tls_ws_ms=- first_audio_ms=1 turn_end_ms=2\n')
            (d/'busy').unlink(missing_ok=True); (job/'done').write_text(status)
            event('filler-done' if filler else 'answer-done')
        time.sleep(.01)
elif sys.argv[1]=='player':
    time.sleep(.08); event('player-open')
    with pathlib.Path(sys.argv[2]).open('rb', buffering=0) as f:
        while True:
            chunk=f.read(1024)
            if not chunk: break
            with (root/'played').open('ab') as p:p.write(chunk)
            if b'F' in chunk: event('filler-played'); (root/'filler-played').touch()
    event('player-exit')
else:
    event('ordinary-filler' if sys.argv[1]=='搜索中，请稍等。' else 'ordinary-answer')
    pathlib.Path(sys.argv[2]).write_bytes((b'F' if sys.argv[1]=='搜索中，请稍等。' else b'A')*1024)
'''


class TtsEarlyStartTest(unittest.TestCase):
    def pipeline(self, action='search', mode='ok', early=1, wake=False, native=False, shell=None, body='', cache=0):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); fake=root/'fake-ettsc'
            fake.write_text('#!'+sys.executable+'\n'+FAKE); fake.chmod(0o700)
            (root/'uptime').write_text('1.50 0\n')
            names=(*HELPERS,*PERSISTENT,*EARLY,'llm_stream_answer_and_play','stream_synthesize_sentence',
                   'stream_play_worker','new_llm_session_id')
            if wake: names+=('handle_wakeup',)
            code=embedded_protocol()+'\n'+embedded_web()+'\n'+functions(*names)
            code=code.replace('/tmp/native_first_stream',temp+'/stream').replace('/tmp/native_first_tts',temp+'/tts')
            code=code.replace('/tmp/native_first_marks.',temp+'/marks.').replace('/proc/uptime',temp+'/uptime')
            code=code.replace('/data/',temp+'/data/')
            code+=r'''
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1; BACKEND=deepseek
DEVICE_TTS_PERSISTENT=1; DEVICE_TTS_EARLY_START="$EARLY"; DEVICE_TTS_PREWARM=0; ETTSC_IDLE_SECS=20
LATENCY_TRACE_ENABLED=1; LATENCY_LOG_MAX_LINES=200
LLM_API_KEY=sk-test; LLM_WEB_SEARCH=auto; LLM_WEB_FILLER='搜索中，请稍等。'; LLM_WEB_FILLER_CACHE="$CACHE"
DEVICE_TTS_BIN="$TEST_DIR/fake-ettsc"; DEVICE_TTS_VOICE=voice; DEVICE_TTS_GAIN=1; DEVICE_TTS_PCM_RATE=24000
DEVICE_TTS_GEC_VERSION=test; DEVICE_TTS_UA=; DEVICE_TTS_ORIGIN=; DEVICE_TTS_TIMEOUT=3
[ "$MODE" != hang ] || DEVICE_TTS_TIMEOUT=1
DEVICE_TTS_STREAM_RETRIES=0; TTS_FALLBACK_NATIVE=0
mkdir -p "$TEST_DIR/data"
log() {
    printf '%s\n' "$*" >> "$TEST_DIR/client.log"
    case "$*" in '[TTS] early filler queued') printf 'filler-queued\n' >> "$TEST_DIR/events";; esac
}
monotonic_ms() { "$PYTHON" -c 'import time; print(int(time.monotonic()*1000))'; }
elapsed_s() { echo 0; }
llm_build_messages() {
    if [ "$MODE" = restart ]; then
        ticks=0
        while [ ! -f "$TTS_PERSISTENT_DIR/exited" ] && [ "$ticks" -lt 400 ]; do sleep .025; ticks=$((ticks+1)); done
        [ -f "$TTS_PERSISTENT_DIR/exited" ] || return 4
    fi
    echo fixture
}
llm_history_commit() { printf '%s\n' "$3" >> "$TEST_DIR/history"; }
timeout() { shift 2; "$@"; }
llm_aplay() { for arg do last="$arg"; done; "$DEVICE_TTS_BIN" player "$last"; }
llm_open_stream() {
    printf 'plan-start\n' >> "$TEST_DIR/events"
    # Early filler was submitted before planning, not in response to its result.
    if [ "$DEVICE_TTS_EARLY_START" = 1 ] && [ "$MODE" != restart ]; then [ -s "$TTS_EARLY_FILLER_JOB/request" ] || return 4; fi
    sleep .15
    if [ "$ACTION" = search ]; then
        llm_web_filler
        # Causal barrier: require filler playback before emitting any answer token.
        ticks=0
        while [ ! -f "$TEST_DIR/filler-played" ] && [ "$ticks" -lt 400 ]; do sleep .025; ticks=$((ticks+1)); done
        [ ! -f "$TEST_DIR/filler-played" ] || : > "$TEST_DIR/played-before-token"
    fi
    if [ "$ACTION" = empty ]; then return 1; fi
    printf 'first-token\n' >> "$TEST_DIR/events"
    printf 'data: {"choices":[{"delta":{"content":"正常回答。"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
}
tts_persistent_init
'''
            if wake:
                code+=r'''
NATIVE_WAIT_SECONDS=.1; NATIVE_POLL_INTERVAL=.01; FOLLOWUP_ENABLED=0
select_native_result_source() { echo fixture; }; set_state() { :; }; led_feedback_native_listening() { :; }
is_system1_root() { return 1; }; led_off() { :; }; resume_native_player() { :; }
handle_native_success_speak() { printf 'native-play\n' >> "$TEST_DIR/events"; }
get_native_result() {
    if [ "$DEVICE_TTS_EARLY_START" = 1 ]; then [ -n "$TTS_PERSISTENT_PID" ] || return 4; fi
    printf 'asr-result\n' >> "$TEST_DIR/events"
    RESULT_TS=1; RESULT_DOMAIN=test; RESULT_QUERY=fixture; RESULT_SOURCE=test; RESULT_ACTION=; RESULT_SPEAK=
}
is_ignored_query_result() { return 1; }; is_unsupported_result() { return 1; }
is_native_success_domain() { [ "$NATIVE" = 1 ]; }
freeze_native_player() { printf 'freeze\n' >> "$TEST_DIR/events"; sleep .05; }
handle_llm_dialog() { llm_stream_answer_and_play "$1" "$2" 1000; tts_persistent_stop; }
handle_wakeup 1
printf 'RESULT=%s\n' "$?"
'''
            else:
                code+='\nlatency_begin; latency_mark wake\ntts_early_filler_start same\n'
                code+='llm_stream_answer_and_play same fixture 1000\nprintf "RESULT=%s\\n" "$?"\n'
            code+=body+'\ntts_persistent_stop\n'
            run=subprocess.run((shell or ['sh'])+['-c',code], capture_output=True,text=True,timeout=20,
                               env={**os.environ,'TEST_DIR':temp,'PYTHON':sys.executable,'MODE':mode,
                                    'ACTION':action,'EARLY':str(early),'NATIVE':str(int(native)), 'CACHE':str(cache),'LC_ALL':'C'})
            self.assertEqual(run.returncode,0,run.stderr); self.assertEqual(run.stderr,'')
            read=lambda f:(root/f).read_text() if (root/f).exists() else ''
            result={'stdout':run.stdout,'events':read('events').splitlines(),'played':read('played'),
                    'history':read('history'),'early':(root/'played-before-token').exists(),'log':read('client.log'),
                    'marks':read('stream/marks'),'raw':read('stream/raw')}
            self.assertEqual(list(root.glob('tts.*')),[], 'private worker directories leaked')
            return result

    def test_filler_plays_before_any_answer_token_and_uses_same_worker(self):
        r=self.pipeline()
        self.assertIn('RESULT=0',r['stdout']); self.assertTrue(r['early'])
        self.assertEqual(r['played'],'F'*1024+'A'*1024)
        self.assertEqual(r['history'],'正常回答。\n'); self.assertEqual(r['raw'],'正常回答。\n')
        self.assertEqual(r['events'].count('connect-start'),1)
        self.assertLess(r['events'].index('filler-played'),r['events'].index('first-token'))
        self.assertIn('filler_commit ',r['marks']); self.assertIn('answer_commit ',r['marks'])
        self.assertIn('player_start ',r['marks']); self.assertIn('player_fifo_open ',r['marks'])

    def test_wake_launches_worker_before_asr_and_filler_before_freeze(self):
        r=self.pipeline(wake=True)
        self.assertIn('RESULT=0',r['stdout']); self.assertTrue(r['early'])
        self.assertLess(r['log'].index('persistent started'),r['log'].index('early filler queued'))
        self.assertEqual(r['events'].count('connect-start'),1)
        self.assertLess(r['events'].index('asr-result'),r['events'].index('filler-queued'))
        self.assertLess(r['events'].index('filler-queued'),r['events'].index('freeze'))
        self.assertLess(r['events'].index('filler-queued'),r['events'].index('plan-start'))

    def test_disabled_native_path_does_not_connect(self):
        r=self.pipeline(wake=True,native=True,early=0)
        self.assertNotIn('connect-start',r['events']); self.assertNotIn('persistent started',r['log'])
        self.assertEqual(r['played'],'')

    def test_native_success_reaps_connection_without_synthesizing_or_playing_filler(self):
        r=self.pipeline(wake=True,native=True)
        self.assertIn('RESULT=0',r['stdout'])
        self.assertEqual(r['played'],''); self.assertEqual(r['history'],'')
        self.assertNotIn('filler-start',r['events']); self.assertNotIn('player-open',r['events'])
        self.assertIn('native-play',r['events'])

    def test_answer_action_discards_silent_filler_and_preserves_history(self):
        r=self.pipeline(action='answer')
        self.assertEqual(r['played'],'A'*1024); self.assertEqual(r['history'],'正常回答。\n')
        self.assertNotIn('filler-played',r['events']); self.assertNotIn('filler_commit ',r['marks'])

    def test_partial_or_timed_out_speculation_falls_back_in_order(self):
        for mode in ('partial','hang'):
            with self.subTest(mode=mode):
                r=self.pipeline(mode=mode)
                self.assertIn('RESULT=0',r['stdout']); self.assertTrue(r['early'])
                self.assertEqual(r['played'],'F'*1024+'A'*1024)
                self.assertEqual(r['history'],'正常回答。\n'); self.assertIn('ordinary-filler',r['events'])
                self.assertIn('player-exit',r['events'])

    def test_restart_during_request_preparation_preserves_filler_and_body(self):
        r=self.pipeline(mode='restart')
        self.assertIn('RESULT=0',r['stdout']); self.assertEqual(r['played'],'F'*1024+'A'*1024)
        self.assertEqual(r['history'],'正常回答。\n'); self.assertEqual(r['events'].count('connect-start'),2)

    def test_completed_filler_directory_may_disappear_before_round_cleanup(self):
        r=self.pipeline(mode='cleanup-race')
        self.assertIn('RESULT=0',r['stdout']); self.assertEqual(r['played'],'F'*1024+'A'*1024)
        self.assertEqual(r['history'],'正常回答。\n')

    def test_empty_answer_never_commits_history_or_plays_unused_filler(self):
        r=self.pipeline(action='empty')
        self.assertIn('RESULT=1',r['stdout']); self.assertEqual(r['history'],''); self.assertEqual(r['played'],'')
        self.assertIn('player-exit',r['events'])

    def test_cache_switch_does_not_duplicate_filler(self):
        r=self.pipeline(cache=1)
        self.assertEqual(r['played'],'F'*1024+'A'*1024)
        self.assertEqual(r['events'].count('filler-start'),1)

    def test_invalid_flag_defaults_to_disabled(self):
        r=self.pipeline(action='answer',early='invalid')
        self.assertIn('invalid DEVICE_TTS_EARLY_START',r['log']); self.assertNotIn('early filler queued',r['log'])
        self.assertNotIn('player_start ',r['marks'])

    @unittest.skipUnless(shutil.which('busybox'),'BusyBox ash unavailable on host')
    def test_busybox_early_filler(self):
        r=self.pipeline(shell=[shutil.which('busybox'),'ash'])
        self.assertTrue(r['early']); self.assertEqual(r['played'],'F'*1024+'A'*1024)


if __name__=='__main__': unittest.main()
