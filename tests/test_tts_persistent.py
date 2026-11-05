"""Exercise session-owned TTS reuse across segments, followups and fallback."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_latency_trace import HELPERS, functions

PERSISTENT = ('tts_persistent_init', 'tts_persistent_ensure', 'tts_persistent_take', 'tts_persistent_stop')
FAKE = r'''
import os, pathlib, shutil, sys, time
root=pathlib.Path(os.environ['TEST_DIR']); mode=os.environ['MODE']
def event(text):
    with (root/'events').open('a') as f: f.write(text+'\n')
if sys.argv[1] == 'serve':
    directory=pathlib.Path(sys.argv[2]); event('connect')
    (root/('pid-'+str(os.getpid()))).touch(); (directory/'ready').touch()
    if mode == 'fail':
        (directory/'exited').write_text('1'); sys.exit(2)
    while True:
        if (directory/'expire').exists():
            (directory/'exited').write_text('0'); sys.exit(0)
        for job in directory.glob('job.*'):
            if not (job/'queued').exists(): continue
            (job/'queued').unlink(); event('persistent-turn')
            text=(job/'request').read_text()
            if mode == 'hang':
                while not (job/'cancel').exists(): time.sleep(.01)
                (directory/'busy').unlink(missing_ok=True); shutil.rmtree(job); continue
            if mode in ('partial','allfail'):
                (job/'audio.part').write_bytes(b'P'*1024); status='1'
            else:
                (job/'audio.pcm').write_bytes((b'A' if text=='正常回答。' else b'B')*1024); status='0'
            (job/'worker.log').write_text('[T] tcp_ms=- tls_ws_ms=- first_audio_ms=1 turn_end_ms=2\n')
            (directory/'busy').unlink(missing_ok=True); (job/'done').write_text(status)
        time.sleep(.01)
elif sys.argv[1] == 'prewarm':
    event('unexpected-prewarm'); sys.exit(2)
else:
    event('normal-turn')
    if mode == 'allfail': sys.exit(2)
    pathlib.Path(sys.argv[2]).write_bytes((b'A' if sys.argv[1]=='正常回答。' else b'B')*1024)
'''


class TtsPersistentTest(unittest.TestCase):
    def pipeline(self, ids=('same','same'), mode='ok', enabled=1, settings='', between='', shell=None, dialog=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); binary=root/'fake-ettsc'
            binary.write_text('#!'+sys.executable+'\n'+FAKE); binary.chmod(0o700)
            (root/'uptime').write_text('1.50 0\n')
            names=(*HELPERS, *PERSISTENT, 'new_llm_session_id', 'llm_stream_answer_and_play', 'stream_synthesize_sentence', 'stream_play_worker')
            if dialog: names+=('handle_llm_dialog',)
            code=functions(*names).replace('/tmp/native_first_stream',temp+'/stream').replace('/tmp/native_first_tts',temp+'/tts').replace('/proc/uptime',temp+'/uptime')
            code+=r'''
LATENCY_TRACE_ENABLED=0; LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
DEVICE_TTS_PERSISTENT="$ENABLED"; ETTSC_IDLE_SECS=20; DEVICE_TTS_PREWARM=0
DEVICE_TTS_BIN="$TEST_DIR/fake-ettsc"; DEVICE_TTS_VOICE=voice-a; DEVICE_TTS_GAIN=1
DEVICE_TTS_PCM_RATE=24000; DEVICE_TTS_TIMEOUT=1; DEVICE_TTS_STREAM_RETRIES=0
DEVICE_TTS_GEC_VERSION=test; DEVICE_TTS_UA=; DEVICE_TTS_ORIGIN=; TTS_FALLBACK_NATIVE=0
LLM_API_KEY=sk-test; LLM_WEB_FILLER='搜索中，请稍等。'
log() { printf '%s\n' "$*"; }; monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_build_messages() { echo fixture; }; llm_history_commit() { printf '%s\n' "$3" >> "$TEST_DIR/history"; }
llm_open_stream() { printf '正常回答。\n第二句话。\n'; }
llm_sse_content() { cat; printf complete > "$1"; }
timeout() { shift 2; "$@"; }
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
'''
            code+=settings+'\ntts_persistent_init\n'
            if dialog:
                code+=r'''
FOLLOWUP_ENABLED=0
set_state() { :; }; led_feedback_llm_accept() { :; }; pause_native_asr() { :; }
led_off() { :; }; resume_native_asr() { :; }
send_text_and_play() { llm_stream_answer_and_play "$1" "$2" 1000; }
handle_llm_dialog same fixture
printf 'DIALOG_CLEAN=%s\n' "${TTS_PERSISTENT_PID:-}"
'''
            else:
                for index,sid in enumerate(ids):
                    code+=f'\nllm_stream_answer_and_play {sid} fixture 1000\nprintf "RESULT=%s\\n" "$?"\n'
                    if index+1 < len(ids): code+=between+'\n'
            code+='\ntts_persistent_stop\n'
            run=subprocess.run((shell or ['sh'])+['-c',code], capture_output=True,text=True,
                               env={**os.environ,'TEST_DIR':temp,'MODE':mode,'ENABLED':str(enabled),'LC_ALL':'C'}, timeout=20)
            self.assertEqual(run.returncode,0,run.stderr); self.assertEqual(run.stderr,'')
            self.assertEqual(list(root.glob('tts.*')),[], 'worker private directories leaked')
            for pid in root.glob('pid-*'):
                with self.assertRaises(ProcessLookupError): os.kill(int(pid.name[4:]),0)
            read=lambda name:(root/name).read_text() if (root/name).exists() else ''
            return run.stdout,read('events').splitlines(),read('played'),read('history')

    def test_two_segments_and_two_followups_use_one_worker(self):
        on=self.pipeline(); off=self.pipeline(enabled=0)
        self.assertEqual(on[1],['connect']+['persistent-turn']*4)
        self.assertEqual(off[1],['normal-turn']*4)
        self.assertEqual(on[2:],off[2:])
        self.assertEqual(on[2],('A'*1024+'B'*1024)*2)
        self.assertEqual(on[3],'正常回答。第二句话。\n'*2)
        self.assertEqual(on[0].count('RESULT=0'),2)

    def test_reuse_does_not_require_cksum_on_device(self):
        result=self.pipeline(settings="cksum() { printf 'unexpected cksum call' >&2; return 127; }")
        self.assertEqual(result[1].count('connect'),1)
        self.assertEqual(result[0].count('RESULT=0'),2)

    def test_session_or_voice_change_replaces_worker(self):
        for kwargs in ({'ids':('one','two')},{'between':'DEVICE_TTS_VOICE=voice-b'}):
            result=self.pipeline(**kwargs)
            self.assertEqual(result[1].count('connect'),2)
            self.assertEqual(result[0].count('RESULT=0'),2)

    def test_new_wake_or_reset_retires_the_old_worker(self):
        result=self.pipeline(between='BACKEND=deepseek; new_llm_session_id')
        self.assertEqual(result[1].count('connect'),2)
        self.assertEqual(result[0].count('RESULT=0'),2)

    def test_idle_exit_is_reaped_and_next_round_starts_a_worker(self):
        result=self.pipeline(between=': > "$TTS_PERSISTENT_DIR/expire"; sleep .1')
        self.assertEqual(result[1].count('connect'),2)
        self.assertEqual(result[0].count('RESULT=0'),2)

    def test_persistent_has_priority_over_single_use_prewarm(self):
        result=self.pipeline(settings='DEVICE_TTS_PREWARM=1')
        self.assertNotIn('unexpected-prewarm',result[1])
        self.assertEqual(result[1].count('connect'),1)

    def test_failures_partial_and_timeout_preserve_audio_and_history(self):
        for mode in ('fail','partial','hang'):
            with self.subTest(mode=mode):
                result=self.pipeline(ids=('same',),mode=mode)
                self.assertIn('RESULT=0',result[0])
                self.assertEqual(result[2],'A'*1024+'B'*1024)
                self.assertEqual(result[3],'正常回答。第二句话。\n')
                self.assertEqual(result[1].count('normal-turn'),2)

    def test_failed_tts_never_commits_a_complete_history(self):
        result=self.pipeline(ids=('same',),mode='allfail')
        self.assertIn('RESULT=1',result[0]); self.assertEqual(result[2:],('',''))

    def test_dialog_exit_stops_worker_immediately(self):
        result=self.pipeline(dialog=True)
        self.assertIn('DIALOG_CLEAN=\n',result[0]); self.assertEqual(result[1].count('connect'),1)

    def test_invalid_config_defaults_and_zero_padded_idle(self):
        result=self.pipeline(settings='DEVICE_TTS_PERSISTENT=bad; ETTSC_IDLE_SECS=999')
        self.assertEqual(result[0].count('warning invalid'),2)
        self.assertEqual(result[1],['normal-turn']*4)
        result=self.pipeline(settings='ETTSC_IDLE_SECS=008')
        self.assertEqual(result[1].count('connect'),1)

    @unittest.skipUnless(shutil.which('busybox'),'BusyBox ash unavailable on host')
    def test_busybox_session_reuse(self):
        result=self.pipeline(shell=[shutil.which('busybox'),'ash'])
        self.assertEqual(result[1].count('connect'),1)


if __name__=='__main__': unittest.main()
