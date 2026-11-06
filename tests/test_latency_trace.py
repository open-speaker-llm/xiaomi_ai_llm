"""M03 观测、脱敏、有界日志与开关等价性；不连接设备或云端。"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'device/native_first_client.sh').read_text()
HELPERS = ('latency_init', 'latency_active', 'latency_discard', 'latency_begin',
           'latency_mark', 'latency_report')


def functions(*names):
    return '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', SOURCE, re.M | re.S).group()
                     for name in names)


MARKS = '''wake 1000
native_result 1500
route_llm 1600
freeze_done 1650
llm_req 1700
llm_first_token 2800
sent1_split 3150
sent1_tts_start 3150
sent1_tts_end 3850
sent1_pcm_bytes 86400
sent1_retries 0
fifo_commit1 3900
answer_commit 3900
sent2_tts_end 4200
sent2_retries 2
llm_done 3400
play_done 6000
'''


class LatencyTraceTest(unittest.TestCase):
    def run_shell(self, body, marks=MARKS, engine='sh'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'marks').write_text(marks)
            script = functions(*HELPERS).replace('/tmp/native_first_latency.log', temp + '/latency.log')
            script = script.replace('/tmp/native_first_marks.', temp + '/pending.')
            script += '\n' + r'''
LATENCY_TRACE_ENABLED=1; LATENCY_LOG_MAX_LINES=200; ETTSC_TIMING=0
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1; DEVICE_TTS_PCM_RATE=24000
LATENCY_MARK_DIR="$TEST_DIR"
log() { printf '%s\n' "$*"; }
monotonic_ms() { echo 10000; }
''' + body
            command = ['sh', '-c', script] if engine == 'sh' else [engine, 'ash', '-c', script]
            run = subprocess.run(command, env={**os.environ, 'TEST_DIR': temp, 'LC_ALL': 'C'},
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            log = root / 'latency.log'
            return run.stdout, log.read_text() if log.exists() else '', (root / 'marks').read_text()

    def test_report_known_marks_and_sanitized_web_fields(self):
        marks = MARKS + 'web_plan_start 1700\nweb_plan_end 2200\nweb_tool_start 2200\nweb_tool_end 2700\nweb_filler 2000\n'
        out, log, _ = self.run_shell('''
printf search > "$TEST_DIR/latency_web_action"
latency_report
''', marks + 'secret question sk-test https://example.com/?token=private\n')
        for field in ('wake→route=0.600', 'route→req=0.100', 'ttft=1.100',
                      'split1=0.350', 'tts1=0.700', 'commit1=0.050',
                      'wake→commit1=2.900', 'pcm1=1.800', 'segs=2', 'retries=2',
                      'web=search', 'plan=0.500', 'search=0.500', 'filler=0.300'):
            self.assertIn(field, out)
        self.assertEqual(out, log)
        self.assertEqual(len(log.splitlines()), 1)
        for secret in ('secret', 'question', 'sk-test', 'https:', 'token=private'):
            self.assertNotIn(secret, out)
        # 无垫话时，互不重叠的阶段之和等于 wake→FIFO。
        fields = dict(item.split('=', 1) for item in out.split()[1:])
        total = sum(float(fields[k]) for k in ('wake→route', 'route→req', 'ttft', 'split1', 'tts1', 'commit1'))
        self.assertAlmostEqual(total, float(fields['wake→commit1']), places=3)

    def test_early_player_filler_and_answer_commit_fields(self):
        marks = MARKS + ('player_start 1700\nplayer_fifo_open 2000\n'
                         'filler_commit 2500\nfiller_pcm_bytes 48000\n')
        out, _, _ = self.run_shell('latency_report', marks)
        self.assertIn('player_open=0.300', out)
        self.assertIn('wake→filler_commit=1.500', out)
        self.assertIn('wake→answer_commit=2.900', out)
        self.assertIn('filler→answer_gap=0.400 filler→answer_gap_kind=est', out)

    def test_inline_filler_uses_body_split_and_commit_in_summary(self):
        marks = MARKS + '''inline_filler 1
filler_commit 2200
fifo_commit_slot 1
filler_pcm_bytes 96000
sent2_split 3200
sent2_tts_start 3200
sent2_pcm_bytes 48000
'''
        marks = marks.replace('sent1_split 3150', 'sent1_split 2000').replace('sent1_tts_end 3850', 'sent1_tts_end 2200')
        marks = marks.replace('fifo_commit1 3900', 'fifo_commit1 2200').replace('answer_commit 3900', 'answer_commit 4250')
        out, _, _ = self.run_shell('latency_report', marks)
        for field in ('split1=0.400', 'tts1=1.000', 'commit1=0.000', 'pcm1=1.000',
                      'wake→commit1=1.200', 'wake→answer_commit=3.250',
                      'filler→answer_gap=0.050 filler→answer_gap_kind=est'):
            self.assertIn(field, out)
        out, _, _ = self.run_shell('latency_report', marks.replace('96000', '100800'))
        self.assertIn('filler→answer_gap=0.000 filler→answer_gap_kind=est', out)
        out, _, _ = self.run_shell('latency_report', marks.replace('filler_pcm_bytes 96000', ''))
        self.assertIn('filler→answer_gap=- filler→answer_gap_kind=-', out)

    def test_live_first_commit_and_prestart_wait(self):
        marks = MARKS.replace('fifo_commit1 3900', 'fifo_commit1 3600')
        marks += 'fifo_commit_slot 1\nfifo_commit_live 1\nsent1_first_pcm 3400\nplayer_fifo_open 2000\n'
        out, _, _ = self.run_shell('latency_report', marks)
        fields = dict(item.split('=', 1) for item in out.split()[1:])
        self.assertEqual(fields['commit1'], '0.200')
        self.assertEqual(fields['player_prestart_wait'], '1.600')
        self.assertEqual(fields['player_underrun'], '0')
        self.assertEqual(fields['player_underrun_ms'], '0.000')

    def test_cached_filler_uses_its_own_commit(self):
        marks = MARKS.replace('fifo_commit1 3900', 'fifo_commit1 2200')
        marks += 'fifo_commit_slot 0\nweb_filler 2100\nfiller_commit 2200\n'
        out, _, _ = self.run_shell('latency_report', marks)
        fields = dict(item.split('=', 1) for item in out.split()[1:])
        self.assertEqual(fields['commit1'], '0.100')
        self.assertEqual(fields['wake→commit1'], '1.200')

    def test_underrun_is_timestamped_before_player_exit(self):
        out, _, marks = self.run_shell(functions('llm_aplay') + r'''
STREAM_PLAY_MARK_DIR="$TEST_DIR"
DIRAC_PLAYBACK_LOG="$TEST_DIR/aplay.log"
DIRAC_APLAY="$TEST_DIR/missing-helper"
monotonic_ms() { echo 4300; }
aplay() {
    echo 'underrun!!! (at least 12.500 ms long)' >&2
    i=0
    until grep -q '^player_underrun_at 4300 12500$' "$TEST_DIR/marks"; do
        i=$((i + 1))
        [ "$i" -lt 100 ] || return 9
        sleep 0.01
    done
    echo 'underrun!!! (at least 0.500 ms long)' >&2
}
llm_aplay fixture.pcm || exit "$?"
latency_report
''')
        self.assertIn('player_underrun_at 4300 12500\nplayer_underrun_at 4300 500\n', marks)
        self.assertIn('player_underrun=2 player_underrun_ms=13.000', out)
        self.assertIn('player_underrun_at=3.300,3.300 player_underrun_first_at=3.300 player_underrun_phase=answer', out)

    def test_player_log_counts_each_invocation_and_preserves_status(self):
        out, _, _ = self.run_shell(functions('llm_aplay') + r'''
STREAM_PLAY_MARK_DIR="$TEST_DIR"
DIRAC_PLAYBACK_LOG="$TEST_DIR/aplay.log"
DIRAC_APLAY="$TEST_DIR/missing-helper"
aplay() {
    printf '%s\n' 'underrun!!! (at least 12.500 ms long)' 'xrun: underrun!!! (at least 7,250 ms long)' >&2
    return 7
}
llm_aplay test.pcm
printf 'rc=%s\n' "$?"
aplay() { echo 'underrun!!! (at least 3 ms long)' >&2; }
llm_aplay test.pcm
latency_report
aplay() { echo 'underrun!!!' >&2; }
llm_aplay test.pcm
latency_report
''')
        self.assertIn('rc=7', out)
        self.assertIn('player_underrun=3 player_underrun_ms=22.750', out)
        self.assertIn('player_underrun=4 player_underrun_ms=-', out)

    def test_first_pcm_boundary_reclassifies_without_using_duration(self):
        for first, opened, observed, duration in ((5200, 2770, 5210, 1910695),
                                                  (5170, 2780, 5190, 1874129)):
            with self.subTest(first=first):
                marks = f'''wake 1000
player_fifo_open {opened}
fifo_commit1 {first}
answer_commit {first}
player_underrun_at {observed} {duration}
player_underrun_at {first + 20} 25000
player_underrun_at {first + 101} {duration}
player_underrun_count 3
player_underrun_us {duration * 2 + 25000}
'''
                out, _, _ = self.run_shell('latency_report', marks)
                self.assertIn('player_underrun=1', out)
                self.assertIn(f'player_prestart_underrun_ms={(duration + 25000) / 1000:.3f}', out)
                self.assertIn('player_underrun_phase=prestart', out)

    def test_filler_and_answer_commit_boundary_underruns_are_excluded(self):
        marks = '''wake 1000
fifo_commit1 4200
filler_commit 4200
filler_pcm_bytes 96000
answer_commit 7860
player_underrun_at 4240 2000000
player_underrun_at 7760 1000000
player_underrun_at 7880 1700000
player_underrun_at 7961 200000
player_underrun_count 4
player_underrun_us 4900000
'''
        out, _, _ = self.run_shell('latency_report', marks)
        self.assertIn('player_underrun=1 player_underrun_ms=200.000', out)
        self.assertIn('player_prestart_underrun_ms=2000.000 player_gap_underrun_ms=2700.000', out)

    def test_missing_reversed_and_duplicate_marks(self):
        out, _, _ = self.run_shell('latency_report', 'llm_req 1100\nllm_first_token 900\nllm_req 1000\n')
        for field in ('wake→route=-', 'ttft=-', 'tts1=-', 'pcm1=-', 'plan=-', 'search=-', 'filler=-', 'web=off'):
            self.assertIn(field, out)

    def test_earliest_actual_request_wins_when_planner_and_candidate_race(self):
        marks = MARKS + 'llm_req 1680\nllm_prepare 1660\nllm_entry 1620\nnative_freeze 1610\n'
        out, _, _ = self.run_shell('latency_report', marks)
        self.assertIn('route→req=0.080', out)
        self.assertIn('freeze→llm_entry=0.010 llm_entry→prepare=0.040 llm_prepare→req=0.020', out)

    def test_web_action_cannot_echo_arbitrary_content(self):
        out, _, _ = self.run_shell('''
: > "$TEST_DIR/web_used"
printf 'secret query token' > "$TEST_DIR/latency_web_action"
latency_report
''')
        self.assertIn('web=unknown', out)
        self.assertNotIn('secret', out)

    def test_disabled_does_not_write_or_log(self):
        out, log, marks = self.run_shell('''
LATENCY_TRACE_ENABLED=0
latency_begin
latency_mark wake
latency_report
printf 'old output\n'
''')
        self.assertEqual(out, 'old output\n')
        self.assertEqual(log, '')
        self.assertEqual(marks, MARKS)

    def test_other_tts_and_server_routes_do_not_trace(self):
        for settings in ('TTS_ENGINE=server', 'LLM_PIPELINE=server', 'DEVICE_TTS_STREAM=0'):
            with self.subTest(settings=settings):
                out, log, marks = self.run_shell(settings + '\nlatency_mark wake\nlatency_report')
                self.assertEqual((out, log, marks), ('', '', MARKS))

    def test_mark_appends_numeric_values_only(self):
        _, _, marks = self.run_shell('''
latency_mark sent8_tts_start
latency_mark sent8_pcm_bytes 48000
latency_mark 'sent8 secret_tts_end' 5
latency_mark wake 'secret'
latency_mark secret 123
''', '')
        self.assertEqual(marks, 'sent8_tts_start 10000\nsent8_pcm_bytes 48000\n')

    def test_unavailable_directory_is_best_effort(self):
        out, log, _ = self.run_shell('''
LATENCY_MARK_DIR="$TEST_DIR/absent"
latency_mark wake
latency_report
printf 'rc=%s\n' "$?"
''')
        self.assertEqual(out, 'rc=0\n')
        self.assertEqual(log, '')

    def test_log_retains_last_200_lines(self):
        out, log, _ = self.run_shell('''
i=1; while [ "$i" -le 205 ]; do printf 'old-%s\n' "$i"; i=$((i+1)); done > "$TEST_DIR/latency.log"
latency_report
''')
        lines = log.splitlines()
        self.assertEqual(len(lines), 200)
        self.assertEqual(lines[0], 'old-7')
        self.assertEqual(lines[-1], out.strip())

    def test_config_bounds_and_invalid_values_warn_once(self):
        for value in ('0', '19', '2001', 'secret', '999999999999999999999999'):
            out, _, _ = self.run_shell('''
LATENCY_TRACE_ENABLED=secret; LATENCY_LOG_MAX_LINES=''' + value + '''; ETTSC_TIMING=secret
latency_init
printf 'values=%s/%s/%s\n' "$LATENCY_TRACE_ENABLED" "$LATENCY_LOG_MAX_LINES" "$ETTSC_TIMING"
''')
            self.assertEqual(out.count('[LATENCY-CONFIG]'), 3)
            self.assertIn('values=1/200/0', out)
            self.assertNotIn('secret', out)
        for value in ('20', '2000'):
            out, _, _ = self.run_shell('LATENCY_LOG_MAX_LINES=' + value + '\nlatency_init\nprintf "%s" "$LATENCY_LOG_MAX_LINES"')
            self.assertEqual(out, value)

    @unittest.skipUnless(shutil.which('busybox'), '未安装 BusyBox，ash 兼容测试未执行')
    def test_busybox_report(self):
        out, _, _ = self.run_shell('latency_mark sent8_tts_start\nlatency_report', engine=shutil.which('busybox'))
        self.assertIn('tts1=0.700', out)


class LatencyPipelineTest(unittest.TestCase):
    def run_pipeline(self, enabled):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'uptime').write_text('1.50 0\n')
            code = functions(*HELPERS, 'send_text_native', 'llm_stream_answer_and_play',
                             'stream_synthesize_sentence', 'stream_play_worker')
            code = code.replace('/tmp/native_first_stream', temp + '/stream')
            code = code.replace('/tmp/native_first_latency.log', temp + '/latency.log')
            code = code.replace('/tmp/native_first_marks.', temp + '/pending.')
            code = code.replace('/proc/uptime', temp + '/uptime')
            code += r'''
LATENCY_TRACE_ENABLED="$TRACE"; LATENCY_LOG_MAX_LINES=200; ETTSC_TIMING=1
LLM_PIPELINE=native; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
LLM_API_KEY=sk-test; LLM_MODEL=test; DEVICE_TTS_PCM_RATE=24000
LLM_WEB_FILLER='搜索中，请稍等。'; DEVICE_TTS_STREAM_RETRIES=0
DEVICE_TTS_BIN=fake_ettsc; DEVICE_TTS_TIMEOUT=30; TTS_FALLBACK_NATIVE=1
log() { printf '%s\n' "$*"; }
monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
is_recent_duplicate_llm_query() { return 1; }; record_llm_query() { :; }
set_state() { :; }; set_busy() { :; }; apply_llm_master_volume() { :; }
freeze_native_player() { :; }; led_feedback_llm_playing() { :; }
finish_llm_playback() { :; }; led_feedback_error() { :; }
llm_build_messages() { echo fake-request; }
llm_history_commit() { printf '%s\n' "$3" >> "$TEST_DIR/history"; }
llm_open_stream() { LLM_WEB_ACTION=off; printf '正常回答。\n第二句话。\n'; }
llm_sse_content() { cat; printf complete > "$1"; }
timeout() { shift 2; "$@"; }
fake_ettsc() { printf '[T] tcp_ms=1 tls_ws_ms=2 first_audio_ms=3 turn_end_ms=4\n' >&2; printf 'PCM' > "$2"; }
llm_aplay() { for arg do last="$arg"; done; cat "$last" >> "$TEST_DIR/played"; }
latency_begin
latency_mark wake 500
latency_mark native_result 700
latency_mark route_llm 800
send_text_native session '私有问题 sk-test' now
printf 'RESULT=%s\n' "$?"
# 第二轮没有物理唤醒，使用本轮追问判定时刻。
latency_begin followup
send_text_native session '第二个私有问题' now
printf 'RESULT=%s\n' "$?"
# 消费者提前失败时保留返回码，并在退出处记 play_done。
LATENCY_MARK_DIR="$TEST_DIR/failed-worker"
mkdir -p "$LATENCY_MARK_DIR"
: > "$LATENCY_MARK_DIR/0001.rdy"
: > "$LATENCY_MARK_DIR/0001.failed"
stream_play_worker "$LATENCY_MARK_DIR"
printf 'WORKER_RESULT=%s\n' "$?"
'''
            run = subprocess.run(['sh', '-c', code], env={**os.environ, 'TEST_DIR': temp, 'TRACE': str(enabled), 'LC_ALL': 'C'},
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            read = lambda name: (root / name).read_text() if (root / name).exists() else ''
            return run.stdout, read('latency.log'), read('played'), read('history'), read('stream/marks'), read('stream/0001.attempt-1.log'), read('failed-worker/marks')

    def test_switch_keeps_audio_history_and_existing_output_equal(self):
        enabled = self.run_pipeline(1)
        disabled = self.run_pipeline(0)
        clean = lambda out: '\n'.join(line for line in out.splitlines() if not line.startswith('[LATENCY]'))
        self.assertEqual(clean(enabled[0]), clean(disabled[0]))
        self.assertEqual(enabled[2:4], disabled[2:4])
        self.assertEqual(enabled[2], 'PCMPCMPCMPCM')
        self.assertEqual(enabled[3], '正常回答。第二句话。\n' * 2)
        self.assertEqual(enabled[0].count('RESULT=0'), 2)
        lines = enabled[1].splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('wake→route=0.300', lines[0])
        self.assertIn('start=wake', lines[0])
        self.assertIn('start=followup wake→route=0.000', lines[1])
        self.assertIn('wake→commit1=0.000', lines[1])
        self.assertIn('wake→answer_commit=0.000', lines[1])
        self.assertNotIn('wake ', enabled[4])
        self.assertIn('fifo_commit1 1000', enabled[4])
        self.assertIn('llm_first_token 1500', enabled[4])
        self.assertIn('sent1_pcm_bytes 3', enabled[4])
        self.assertIn('[T] tcp_ms=1', enabled[5])
        self.assertIn('WORKER_RESULT=1', enabled[0])
        self.assertEqual(enabled[6], 'play_done 1000\n')
        self.assertEqual(disabled[6], '')
        self.assertEqual(enabled[4].count('play_done '), 1)
        self.assertNotIn('[LATENCY]', disabled[0])
        self.assertEqual(disabled[1], '')
        self.assertEqual(disabled[4], '')
        for secret in ('私有', 'sk-test', '正常回答', '第二句话'):
            self.assertNotIn(secret, enabled[1])


class LatencySummaryTest(unittest.TestCase):
    def test_nearest_rank_percentiles_and_missing_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp, 'latency.log')
            log.write_text('ignored secret\n' +
                           ''.join('[LATENCY] ttft=%.3f tts1=- secret=100\n' % n for n in range(1, 11)) +
                           '[LATENCY] filler→answer_gap=0.200 filler→answer_gap_kind=est\n' +
                           '[LATENCY] filler→answer_gap=-\n')
            run = subprocess.run(['sh', str(ROOT / 'device/latency_summary.sh'), str(log)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('ttft n=10 P50=5.000 P90=9.000 max=10.000', run.stdout)
            self.assertIn('filler→answer_gap n=1 P50=0.200 P90=0.200 max=0.200', run.stdout)
            self.assertNotIn('tts1 n=', run.stdout)
            self.assertNotIn('secret', run.stdout)

    @unittest.skipUnless(shutil.which('busybox'), '未安装 BusyBox，awk 百分位测试未执行')
    def test_busybox_summary(self):
        # ash 执行脚本，并让脚本中的 awk/sort 也走 BusyBox。
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp, 'latency.log'); log.write_text('[LATENCY] ttft=1\n')
            for tool in ('awk', 'sort', 'mktemp', 'rm'):
                Path(temp, tool).symlink_to(shutil.which('busybox'))
            run = subprocess.run([shutil.which('busybox'), 'ash', str(ROOT / 'device/latency_summary.sh'), str(log)],
                                 env={**os.environ, 'PATH': temp + os.pathsep + os.environ['PATH']}, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('P50=1.000', run.stdout)


if __name__ == '__main__':
    unittest.main()
