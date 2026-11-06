"""S25 用真实 SSE、切句、FIFO 与可终止的 curl 桩验证规划提交边界。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.native_protocol_helpers import embedded_protocol, embedded_web
from tests.test_latency_trace import HELPERS, functions
from tests.test_native_web import JSONFILTER, plan


CURL = '''
import json, os, signal, sys, time
from pathlib import Path
root = Path(os.environ["TEST_DIR"])
def emit(text, final=False):
    event = {"choices": [{"delta": {"content": text},
                          "finish_reason": "stop" if final else None}]}
    print("data:", json.dumps(event), end="\\n\\n", flush=True)
    if final:
        print("data: [DONE]", end="\\n\\n", flush=True)
if not (root / "decision").exists():
    def cancel(*args):
        (root / "cancelled").touch()
        sys.exit(143)
    signal.signal(signal.SIGTERM, cancel)
    if os.environ["CANDIDATE_FAIL"] == "1":
        (root / "candidate").touch()
        sys.exit(28)
    emit("离线正文。")
    (root / "candidate").touch()
    for _ in range(400):
        # Keep the connection open until the approved sentence reaches playback.
        if b"offline" in (root / "played").read_bytes():
            emit("正文收尾。", final=True)
            sys.exit(0)
        time.sleep(0.01)
    sys.exit(28)
(root / "final").touch()
emit("正式正文。", final=True)
'''

CLIENT = r'''
LLM_API_KEY=sk-test; LLM_API_BASE=https://api.deepseek.com; LLM_MODEL=test
LLM_WEB_SEARCH=auto; LLM_WEB_RETRIES=0; LLM_DIRECT_TIMEOUT=5
LLM_WEB_FALLBACK="$FALLBACK"
[ "$SPEC" = default ] || LLM_WEB_SPECULATIVE="$SPEC"
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1; DEVICE_TTS_PCM_RATE=24000
LATENCY_TRACE_ENABLED=1
log() { printf '%s\n' "$*" >&2; }
monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_build_messages() { printf '{"role":"user","content":"测试"}'; }
llm_build_request() { printf '%s' "$1"; }
llm_history_commit() { printf '%s' "$3" > "$TEST_DIR/history"; }
llm_web_post() {
    case "$1" in
        */chat/completions)
            if [ "$SPEC" != 0 ]; then
                n=0
                while [ ! -f "$TEST_DIR/candidate" ] && [ "$n" -lt 60 ]; do
                    sleep 0.02; n=$((n+1))
                done
                sleep 0.15
            fi
            [ ! -s "$TEST_DIR/played" ] || : > "$TEST_DIR/early-commit"
            : > "$TEST_DIR/decision"
            if [ "$MODE" = timeout ]; then llm_web_post_state timeout 000 ''; return 10; fi
            cat "$TEST_DIR/plan";;
        *)
            [ -f "$TEST_DIR/cancelled" ] || : > "$TEST_DIR/tool-before-cancel"
            cat "$TEST_DIR/results";;
    esac
}
stream_synthesize_sentence() {
    case "$3" in
        '离线正文。') pcm=offline;;
        '正文收尾。') pcm=ending;;
        '正式正文。') pcm=grounded;;
        '搜索中，请稍等。') pcm=filler;;
        *) pcm=notice;;
    esac
    printf '%s' "$pcm" > "$1/$2.pcm"
}
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
: > "$TEST_DIR/played"
llm_stream_answer_and_play session question 1000
rc=$?
latency_report
exit "$rc"
'''


class WebSpeculativeTest(unittest.TestCase):
    def run_round(self, mode, *, fallback='answer', spec='default', candidate_fail=False, shell=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, body in (('jsonfilter', JSONFILTER), ('curl', CURL)):
                path = root / name
                path.write_text('#!' + sys.executable + '\n' + body)
                path.chmod(0o700)
            (root / 'plan').write_text(json.dumps(plan(mode, query='测试')))
            (root / 'results').write_text(json.dumps({'results': [
                {'title': '官网', 'url': 'https://example.com/news', 'summary': '正文'}]}))
            (root / 'uptime').write_text('1.00 0\n')
            code = embedded_protocol() + embedded_web() + functions(
                *HELPERS, 'llm_stream_answer_and_play', 'stream_play_worker') + '\n' + CLIENT
            for original, replacement in (('/tmp/native_first_stream', temp + '/stream'),
                                          ('/proc/uptime', temp + '/uptime'),
                                          ('/tmp/native_first_latency.log', temp + '/latency.log')):
                code = code.replace(original, replacement)
            result = subprocess.run((shell or ['sh']) + ['-c', code], capture_output=True, text=True, timeout=12,
                                    env={**os.environ, 'PATH': temp + os.pathsep + os.environ['PATH'],
                                         'TEST_DIR': temp, 'MODE': mode, 'FALLBACK': fallback,
                                         'SPEC': spec, 'LC_ALL': 'C', 'CANDIDATE_FAIL': str(int(candidate_fail))})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'early-commit').exists(), result.stderr)
            self.assertEqual(list(root.glob('stream/spec.*')), [])
            return root.joinpath('played').read_text(), {p.name for p in root.iterdir()}, result.stderr

    def test_answer_reuses_open_stream_after_approval(self):
        audio, events, log = self.run_round('answer')
        self.assertIn('candidate', events)
        self.assertNotIn('final', events)
        self.assertEqual(audio, 'offlineending')
        self.assertIn('spec=used', log)

    def test_search_closes_candidate_before_tool_and_plays_only_grounded(self):
        audio, events, log = self.run_round('search')
        self.assertIn('cancelled', events)
        self.assertNotIn('tool-before-cancel', events)
        self.assertEqual(audio, 'fillergrounded')
        self.assertIn('spec=cancelled', log)

    def test_timeout_obeys_answer_and_fail_fallback(self):
        audio, events, log = self.run_round('timeout')
        self.assertIn('candidate', events)
        self.assertNotIn('final', events)
        self.assertEqual(audio, 'offlineending')
        self.assertIn('spec=used', log)
        audio, events, log = self.run_round('timeout', fallback='fail')
        self.assertIn('cancelled', events)
        self.assertNotIn('history', events)
        self.assertEqual(audio, 'notice')
        self.assertIn('spec=cancelled', log)

    def test_disabled_keeps_plan_before_final_request(self):
        audio, events, _ = self.run_round('answer', spec='0')
        self.assertNotIn('candidate', events)
        self.assertEqual(audio, 'grounded')

    def test_candidate_failure_before_release_uses_normal_final_request(self):
        audio, events, log = self.run_round('answer', candidate_fail=True)
        self.assertIn('candidate', events)
        self.assertIn('final', events)
        self.assertEqual(audio, 'grounded')
        self.assertIn('spec=cancelled', log)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash unavailable on host')
    def test_busybox_answer_and_search(self):
        shell = [shutil.which('busybox'), 'ash']
        self.assertEqual(self.run_round('answer', shell=shell)[0], 'offlineending')
        self.assertEqual(self.run_round('search', shell=shell)[0], 'fillergrounded')
