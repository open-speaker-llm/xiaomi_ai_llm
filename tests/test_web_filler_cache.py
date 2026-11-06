"""C3 PCM 缓存的真实切句/合成/播放队列，不调用音箱和云端。"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.native_protocol_helpers import embedded_protocol, embedded_web
from tests.test_latency_trace import HELPERS, functions


class WebFillerCacheTest(unittest.TestCase):
    def pipeline(self, cache=1, size=None, change='', shell=None, *, answer='正常回答。第二句话。',
                 search=True, settings='', answer_pcm=1024):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'uptime').write_text('1.50 0\n')
            if shell:
                (root / 'awk').symlink_to(shell[0])
            code = embedded_protocol() + '\n' + embedded_web() + '\n' + functions(
                *HELPERS, 'llm_stream_answer_and_play', 'stream_synthesize_sentence', 'stream_play_worker')
            code = code.replace('/data/', temp + '/data/')
            code = code.replace('/tmp/native_first_stream', temp + '/stream')
            code = code.replace('/tmp/native_first_latency.log', temp + '/latency.log')
            code = code.replace('/proc/uptime', temp + '/uptime')
            code += '\n' + settings + r'''
mkdir -p "$TEST_DIR/data"
LATENCY_TRACE_ENABLED=1; LATENCY_LOG_MAX_LINES=200
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
LLM_WEB_FILLER='搜索中，请稍等。'; LLM_WEB_FILLER_CACHE="$CACHE"
LLM_API_KEY=sk-test; DEVICE_TTS_VOICE=voice-a; DEVICE_TTS_GAIN=1
DEVICE_TTS_PCM_RATE=24000; DEVICE_TTS_STREAM_RETRIES=0
DEVICE_TTS_BIN=fake_ettsc; DEVICE_TTS_TIMEOUT=30; TTS_FALLBACK_NATIVE=1
log() { case "$*" in '[WARN] '*) printf '%s\n' "$*" >> "$TEST_DIR/warnings";; esac; }; monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_build_messages() { echo fake-request; }
llm_history_commit() { printf '%s\n' "$3" >> "$TEST_DIR/history"; }
timeout() { shift 2; "$@"; }
fake_ettsc() {
    printf '%s\n' "$1" >> "$TEST_DIR/tts"
    case "$1" in
        "$LLM_WEB_FILLER") char=F;;
        '正常回答。') char=A;;
        *) char=B;;
    esac
    bytes="$ANSWER_PCM"; [ "$char" != F ] || bytes=1024
    awk -v c="$char" -v n="$bytes" 'BEGIN {for(i=0;i<n;i++) printf "%s",c}' > "$2"
}
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
llm_open_stream() {
    LLM_WEB_ACTION=off
    if [ "$SEARCH" = 1 ]; then LLM_WEB_ACTION=search; llm_web_filler; fi
    printf 'data: {"choices":[{"delta":{"content":"%s"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n' \
        "$(printf '%s' "$ANSWER" | json_escape)"
}
'''
            if size is not None:
                code += '\ncache_file=$(llm_web_filler_cache_path)\n'
                code += f'awk \'BEGIN {{for(i=0;i<{size};i++) printf "C"}}\' > "$cache_file"\n'
            code += r'''
llm_stream_answer_and_play session question 1000
printf 'ROUND1=%s\n' "$?"
cp "$TEST_DIR/stream/marks" "$TEST_DIR/marks1"
'''
            code += change + '\n'
            code += r'''
llm_stream_answer_and_play session question 1000
printf 'ROUND2=%s\n' "$?"
cp "$TEST_DIR/stream/marks" "$TEST_DIR/marks2"
'''
            run = subprocess.run((shell or ['sh']) + ['-c', code],
                                 env={**os.environ, 'TEST_DIR': temp, 'CACHE': str(cache), 'LC_ALL': 'C',
                                      'PATH': temp + os.pathsep + os.environ['PATH'],
                                      'ANSWER': answer, 'SEARCH': str(int(search)), 'ANSWER_PCM': str(answer_pcm)},
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            self.assertEqual(run.stdout, 'ROUND1=0\nROUND2=0\n')
            read = lambda name: (root / name).read_text() if (root / name).exists() else ''
            return {'played': read('played'), 'history': read('history'), 'tts': read('tts'),
                    'marks1': read('marks1'), 'marks2': read('marks2'), 'warnings': read('warnings'),
                    'cached': (root / 'stream/web_filler_cached').exists(),
                    'slot0': (root / 'stream/0000.rdy').exists(),
                    'pcm': [p.stat().st_size for p in (root / 'data').glob('web_filler.pcm.*')],
                    'parts': list((root / 'data').glob('web-filler.*'))}

    def check_long_search_split(self, shell=None):
        first = '中文🙂' * 8
        rest = '没有标点的剩余正文。'
        answer = first + rest
        filler = '搜索中，请稍等。'
        # 首轮内联垫话，次轮缓存垫话。普通路径必须用同一规则。
        result = self.pipeline(answer=answer, shell=shell)
        self.assertEqual(result['tts'].splitlines(), [filler, first, rest, first, rest])
        self.assertEqual(result['history'], (answer + '\n') * 2)
        ordinary = self.pipeline(answer=answer, search=False, shell=shell)
        self.assertEqual(ordinary['tts'].splitlines(), [first, rest] * 2)

    def test_long_search_body_is_split_with_inline_and_cached_filler(self):
        self.check_long_search_split()

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash/awk unavailable on host')
    def test_busybox_long_search_body_is_split(self):
        self.check_long_search_split([shutil.which('busybox'), 'ash'])

    def test_early_punctuation_and_later_sentences(self):
        first = '短，已经超过八个字;'
        rest = '后续仍按原来切，不能提前。'
        result = self.pipeline(answer=first + rest, search=False)
        self.assertEqual(result['tts'].splitlines(), [first, rest] * 2)

    def test_max_prefers_last_space_and_disabled_keeps_legacy_output(self):
        first = '甲' * 20
        rest = '乙' * 10 + '。'
        answer = first + ' ' + rest
        result = self.pipeline(answer=answer, search=False)
        self.assertEqual(result['tts'].splitlines(), [first, rest] * 2)
        disabled = self.pipeline(answer=answer, search=False, settings='STREAM_FIRST_SPLIT_ENABLED=0')
        self.assertEqual(disabled['tts'].splitlines(), [answer] * 2)

    def test_invalid_split_config_defaults_and_warns_once(self):
        answer = '甲' * 30 + '。'
        result = self.pipeline(answer=answer, search=False,
                               settings='STREAM_FIRST_SPLIT_ENABLED=invalid; STREAM_FIRST_SPLIT_MIN_CHARS=30')
        self.assertEqual(result['tts'].splitlines(), ['甲' * 24, '甲' * 6 + '。'] * 2)
        self.assertEqual(result['warnings'].count('[WARN]'), 1)
        self.assertNotIn('invalid', result['warnings'])

    def test_custom_limits_apply_to_configured_number_of_segments(self):
        result = self.pipeline(answer='甲乙丙丁，戊己庚辛、壬癸子丑，结尾。',
                               search=False,
                               settings='STREAM_FIRST_SPLIT_MIN_CHARS=5; STREAM_FIRST_SPLIT_MAX_CHARS=6; '
                                        'STREAM_EARLY_SPLIT_SENTENCES=2')
        self.assertEqual(result['tts'].splitlines(), ['甲乙丙丁，', '戊己庚辛、', '壬癸子丑，结尾。'] * 2)

    def test_large_pcm_warns_once_per_round_for_body_only(self):
        result = self.pipeline(answer_pcm=288002)
        warnings = result['warnings'].splitlines()
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all(line.startswith('[WARN] sent1_too_long ') for line in warnings))
        self.assertTrue(all('288002' in line and '288000' in line for line in warnings))

    def test_first_synthesis_populates_cache_second_uses_slot_zero_in_order(self):
        result = self.pipeline()
        self.assertEqual(result['played'], ('F'*1024 + 'A'*1024 + 'B'*1024)*2)
        self.assertEqual(result['history'], '正常回答。第二句话。\n'*2)
        self.assertEqual(result['tts'].splitlines(), ['搜索中，请稍等。', '正常回答。', '第二句话。', '正常回答。', '第二句话。'])
        self.assertTrue(result['cached'])
        self.assertTrue(result['slot0'])
        self.assertEqual(result['pcm'], [1024])
        self.assertEqual(result['parts'], [])
        for marks in (result['marks1'], result['marks2']):
            self.assertIn('llm_first_token 1500', marks)
            self.assertIn('web_filler 1000', marks)
            self.assertEqual(marks.count('web_filler '), 1)
            self.assertIn('filler_pcm_bytes 1024', marks)
            self.assertEqual(marks.count('filler_commit '), 1)
            self.assertEqual(marks.count('answer_commit '), 1)
        self.assertIn('inline_filler 1', result['marks1'])
        self.assertNotIn('inline_filler ', result['marks2'])

    def test_disabled_keeps_sse_synthesis_and_creates_no_persistent_pcm(self):
        result = self.pipeline(cache=0)
        self.assertEqual(result['played'], ('F'*1024 + 'A'*1024 + 'B'*1024)*2)
        self.assertEqual(result['tts'].count('搜索中，请稍等。'), 2)
        self.assertFalse(result['slot0'])
        self.assertEqual(result['pcm'], [])

    def test_invalid_cache_is_deleted_then_replaced_by_complete_synthesis(self):
        for size in (0, 100, 1025, 1048578):
            with self.subTest(size=size):
                result = self.pipeline(size=size)
                self.assertTrue(result['played'].startswith('F'*1024))
                self.assertEqual(result['tts'].count('搜索中，请稍等。'), 1)
                self.assertEqual(result['pcm'], [1024])
                self.assertTrue(result['slot0'])

    def test_voice_or_filler_change_invalidates_cache(self):
        for change in ('DEVICE_TTS_VOICE=voice-b', "LLM_WEB_FILLER='搜索中，请耐心稍等。'",
                       'DEVICE_TTS_GAIN=2', 'DEVICE_TTS_PCM_RATE=16000'):
            with self.subTest(change=change):
                result = self.pipeline(change=change)
                self.assertEqual(len(result['tts'].splitlines()), 6)
                self.assertFalse(result['slot0'])
                self.assertEqual(result['history'], '正常回答。第二句话。\n'*2)

    def test_partial_synthesis_is_never_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'web_filler').touch()
            code = (embedded_web() + '\n' + functions('stream_synthesize_sentence')).replace('/data/', temp + '/data/')
            code += r'''
LLM_WEB_FILLER_CACHE=1; LLM_WEB_FILLER='搜索中，请稍等。'
DEVICE_TTS_VOICE=voice-a; DEVICE_TTS_GAIN=1; DEVICE_TTS_PCM_RATE=24000
DEVICE_TTS_STREAM_RETRIES=0; DEVICE_TTS_TIMEOUT=1; DEVICE_TTS_BIN=fake_ettsc
LATENCY_TRACE_ENABLED=0; TTS_FALLBACK_NATIVE=0
log() { :; }
timeout() { shift 2; "$@"; }
fake_ettsc() {
    awk 'BEGIN {for(i=0;i<1024;i++) printf "P"}' > "$2"
    printf '[!] incomplete audio\n'
}
stream_synthesize_sentence "$TEST_DIR" 0001 "$LLM_WEB_FILLER"
'''
            run = subprocess.run(['sh', '-c', code], env={**os.environ, 'TEST_DIR': temp},
                                 capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue((root / '0001.failed').exists())
            self.assertFalse((root / '0001.pcm').exists())
            self.assertEqual(list((root / 'data').iterdir()), [])

    def test_unwritable_cache_storage_falls_back_without_failing_speech(self):
        result = self.pipeline(change='rm -rf "$TEST_DIR/data"; : > "$TEST_DIR/data"')
        self.assertEqual(result['played'], ('F'*1024 + 'A'*1024 + 'B'*1024)*2)
        self.assertEqual(result['tts'].count('搜索中，请稍等。'), 2)
        self.assertFalse(result['slot0'])

    def test_missing_checksum_utility_falls_back_to_sse(self):
        result = self.pipeline(change='cksum() { return 1; }')
        self.assertEqual(result['played'], ('F'*1024 + 'A'*1024 + 'B'*1024)*2)
        self.assertEqual(result['tts'].count('搜索中，请稍等。'), 2)
        self.assertFalse(result['slot0'])

    def test_no_filler_with_cache_enabled_does_not_block_slot_zero(self):
        result = self.pipeline(change='LLM_WEB_FILLER=')
        self.assertEqual(result['played'], 'F'*1024 + ('A'*1024+'B'*1024)*2)
        self.assertFalse(result['slot0'])

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox ash unavailable on host')
    def test_busybox_cache_and_queue(self):
        result = self.pipeline(shell=[shutil.which('busybox'), 'ash'])
        self.assertTrue(result['slot0'])
        self.assertEqual(result['played'], ('F'*1024 + 'A'*1024 + 'B'*1024)*2)


if __name__ == '__main__':
    unittest.main()
