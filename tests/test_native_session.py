"""Bounded native history and opt-in session reset without devices or cloud."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HISTORY_FUNCTIONS = (
    'llm_history_limits', 'llm_history_safe_dir', 'llm_history_prepare',
    'llm_history_owned', 'llm_history_filter', 'llm_history_load',
    'llm_history_commit', 'llm_history_gc', 'llm_build_messages', 'json_escape',
)
SESSION_FUNCTIONS = (
    'new_llm_session_id', 'reset_followup_session', 'is_followup_reset_command',
    'is_followup_exit_command', 'native_dialog_compact', 'classify_native_dialog_text',
    'collect_native_dialog_text', 'handle_llm_dialog', 'cancel_followup_vad_prearm',
)


def functions(*names):
    source = (ROOT / 'device/native_first_client.sh').read_text()
    return '\n'.join(match.group() for name in names
                     if (match := re.search(r'^' + name + r'\(\) \{.*?^\}', source, re.M | re.S)))


def run_shell(code, directory, **env):
    result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=10,
                            env={**os.environ, 'LC_ALL': 'C', 'TEST_DIR': str(directory),
                                 'LLM_HISTORY_DIR': str(directory / 'history'), **env})
    if result.returncode or result.stderr:
        raise AssertionError(f'rc={result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


class NativeSessionHistoryTest(unittest.TestCase):
    def history(self, code, directory, **env):
        return run_shell(functions(*HISTORY_FUNCTIONS) + '\n' + code, directory,
                         LLM_SYSTEM_PROMPT='fixture', **env)

    def test_successful_answers_save_only_complete_bounded_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            (directory / 'history').mkdir()
            code = functions(*HISTORY_FUNCTIONS, 'send_text_native') + r'''
LLM_HISTORY_TURNS=2; TTS_ENGINE=server; DEVICE_TTS_STREAM=0; LLM_MODEL=fixture
log() { :; }; set_state() { :; }; set_busy() { :; }; apply_llm_master_volume() { :; }
freeze_native_player() { :; }; finish_llm_playback() { :; }; led_feedback_llm_playing() { :; }
is_recent_duplicate_llm_query() { return 1; }; record_llm_query() { :; }
monotonic_ms() { printf '1\n'; }; elapsed_s() { printf '0\n'; }
llm_direct_answer() { LLM_DIRECT_ANSWER="回答 $2"; return 0; }
tts_play_text() { return 0; }
for question in 一 二 三 四 五; do
    send_text_native session "$question" normal || exit 1
done
'''
            run_shell(code, directory)
            path = directory / 'history/.native_first_history_v1/h_session'
            if not path.exists():
                path = directory / 'history/session'
            rows = [line for line in path.read_text().splitlines() if '\t' in line]
            self.assertEqual(rows, ['user\t四', 'assistant\t回答 四', 'user\t五', 'assistant\t回答 五'])

    def test_messages_preserve_escaped_text_and_use_only_the_selected_session(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            user = '问题"引号"\\路径\n第二行\t☃️'
            answer = '回答🙂\\ "引号"\n完整内容'
            out = self.history(r'''
llm_history_commit old "$QUESTION" "$ANSWER" || exit 1
llm_build_messages old '继续'; printf '\n'
llm_build_messages fresh '新问题'; printf '\n'
''', directory, QUESTION=user, ANSWER=answer)
            old, new = [json.loads('[' + row + ']') for row in out.splitlines()]
            self.assertEqual(old[1:3], [{'role': 'user', 'content': user}, {'role': 'assistant', 'content': answer}])
            self.assertEqual(new, [{'role': 'system', 'content': 'fixture'}, {'role': 'user', 'content': '新问题'}])
            file = directory / 'history/.native_first_history_v1/h_old'
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_cache_count_protects_current_session_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            self.history('llm_history_commit first old old\n', directory)
            store = directory / 'history/.native_first_history_v1'
            foreign = store / 'h_foreign'
            foreign.write_text('not our history\n')
            damaged = store / 'h_damaged'
            damaged.write_text('NFH1\nuser\tincomplete\n')
            legacy = directory / 'history/legacy'
            legacy.write_text('user\tlegacy\nassistant\tlegacy\n')
            target = directory / 'outside'
            target.write_text('NFH1\nuser\tprivate\nassistant\tprivate\n')
            (store / 'h_link').symlink_to(target)
            (store / 'h_directory').mkdir()
            self.history('for sid in two three four five; do llm_history_commit "$sid" "$sid" "$sid" || exit 1; done\n',
                         directory, LLM_HISTORY_MAX_SESSIONS='2')
            owned = [path for path in store.glob('h_*') if not path.is_symlink() and path.is_file()
                     and path.read_text().startswith('NFH1\n') and path != damaged]
            self.assertEqual(len(owned), 2)
            self.assertIn(store / 'h_five', owned)
            self.assertEqual(foreign.read_text(), 'not our history\n')
            self.assertEqual(damaged.read_text(), 'NFH1\nuser\tincomplete\n')
            self.assertIn('legacy', legacy.read_text())
            self.assertIn('private', target.read_text())
            self.assertTrue((store / 'h_link').is_symlink())
            self.assertTrue((store / 'h_directory').is_dir())

    def test_byte_budget_drops_whole_old_pairs_and_refuses_an_oversized_new_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            self.history(r'''
llm_history_commit session first "$ANSWER" || exit 1
llm_history_commit session second "$ANSWER" || exit 1
''', directory, ANSWER='x' * 650, LLM_HISTORY_MAX_BYTES='1024')
            file = directory / 'history/.native_first_history_v1/h_session'
            previous = file.read_bytes()
            self.assertLessEqual(len(previous), 1024)
            self.assertNotIn(b'first', previous)
            self.assertIn(b'second', previous)
            out = self.history('llm_history_commit session large "$ANSWER"; echo rc=$?\n',
                               directory, ANSWER='y' * 1200, LLM_HISTORY_MAX_BYTES='1024')
            self.assertEqual(out.strip(), 'rc=1')
            self.assertEqual(file.read_bytes(), previous)

    def test_atomic_publish_failure_preserves_previous_complete_history(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            self.history('llm_history_commit session before before\n', directory)
            file = directory / 'history/.native_first_history_v1/h_session'
            previous = file.read_bytes()
            out = self.history('mv() { return 1; }\nllm_history_commit session after after; echo rc=$?\n', directory)
            self.assertEqual(out.strip(), 'rc=1')
            self.assertEqual(file.read_bytes(), previous)
            self.assertFalse(list(file.parent.glob('.next.*')))

    def test_corrupt_or_foreign_history_is_not_loaded_or_overwritten(self):
        for content in ('foreign\n', 'NFH1\nuser\tunfinished\n', 'NFH1\nassistant\torphan\n',
                        'NFH1\nuser\tbad"quote\nassistant\tanswer\n',
                        'NFH1\nuser\tbad\0text\nassistant\tanswer\n',
                        'NFH1\0hidden\nuser\tquestion\nassistant\tanswer\n',
                        'NFH1\nuser\tquestion\nassistant\tanswer\0hidden\n',
                        'NFH1\nuser\tbad\\escape\nassistant\tanswer\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp).resolve()
                self.history('llm_history_prepare session\n', directory)
                file = directory / 'history/.native_first_history_v1/h_session'
                file.write_text(content)
                out = self.history('llm_build_messages session next; echo load=$?\n'
                                   'llm_history_commit session next next; echo commit=$?\n', directory)
                self.assertEqual(out.splitlines(), ['load=1', 'commit=1'])
                self.assertEqual(file.read_text(), content)

    def test_cache_cleanup_preserves_raw_nul_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            self.history('llm_history_prepare damaged\n', directory)
            file = directory / 'history/.native_first_history_v1/h_damaged'
            content = b'NFH1\nuser\tbad\0text\nassistant\tanswer\n'
            file.write_bytes(content)
            os.utime(file, (1, 1))
            self.history('llm_history_commit current question answer || exit 1\n', directory,
                         LLM_HISTORY_MAX_SESSIONS='1')
            self.assertTrue(file.exists(), 'raw NUL history must not become a GC candidate')
            self.assertEqual(file.read_bytes(), content)

    def test_path_traversal_and_symlink_targets_are_rejected(self):
        for kind in ('id', 'root', 'ancestor', 'store', 'marker', 'file'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp).resolve()
                target = directory / 'private'
                target.mkdir()
                secret = target / 'secret'
                secret.write_text('private fixture\n')
                history_root = directory / 'history'
                sid = 'session'
                if kind == 'id':
                    sid = '../private/secret'
                elif kind == 'root':
                    history_root.symlink_to(target)
                elif kind == 'ancestor':
                    (directory / 'alias').symlink_to(target)
                    history_root = directory / 'alias/nested'
                else:
                    self.history('llm_history_prepare session\n', directory)
                    store = history_root / '.native_first_history_v1'
                    if kind == 'store':
                        (store / '.owner').unlink()
                        store.rmdir()
                        store.symlink_to(target)
                    elif kind == 'marker':
                        (store / '.owner').unlink()
                        (store / '.owner').symlink_to(secret)
                    else:
                        (store / 'h_session').symlink_to(secret)
                out = self.history('llm_history_commit "$SID" question answer; echo rc=$?\n',
                                   directory, SID=sid, LLM_HISTORY_DIR=str(history_root))
                self.assertEqual(out.strip(), 'rc=1')
                self.assertEqual(secret.read_text(), 'private fixture\n')
                self.assertEqual(list(target.iterdir()), [secret])

    def test_unknown_existing_store_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            store = directory / 'history/.native_first_history_v1'
            store.mkdir(parents=True)
            (store / 'owner-data').write_text('untouched')
            out = self.history('llm_history_commit session question answer; echo rc=$?\n', directory)
            self.assertEqual(out.strip(), 'rc=1')
            self.assertEqual([path.name for path in store.iterdir()], ['owner-data'])

    def test_corrupt_owner_marker_does_not_adopt_existing_store(self):
        for marker in (b'NATIVE_FIRST_HISTORY_V1\0', b'NATIVE_FIRST_HISTORY_V1\n\0',
                       b'NATIVE_FIRST_HISTORY_V1', b'NATIVE_FIRST_HISTORY_V1\nextra\n'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp).resolve()
                store = directory / 'history/.native_first_history_v1'
                store.mkdir(parents=True)
                (store / '.owner').write_bytes(marker)
                (store / 'owner-data').write_text('untouched')
                out = self.history('llm_history_commit session question answer; echo rc=$?\n', directory)
                self.assertEqual(out.strip(), 'rc=1')
                self.assertEqual((store / '.owner').read_bytes(), marker)
                self.assertEqual((store / 'owner-data').read_text(), 'untouched')
                self.assertEqual(sorted(path.name for path in store.iterdir()), ['.owner', 'owner-data'])

    def test_disabled_history_does_not_send_or_store_turns(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            out = self.history('llm_history_commit session question answer || exit 1\n'
                               'llm_build_messages session next\n', directory, LLM_HISTORY_TURNS='0')
            self.assertEqual(len(json.loads('[' + out + ']')), 2)
            self.assertFalse(list((directory / 'history').rglob('h_*')))

    def test_invalid_capacity_configuration_is_rejected_before_writing(self):
        for key, value in [('LLM_HISTORY_TURNS', '-1'), ('LLM_HISTORY_TURNS', '101'),
                           ('LLM_HISTORY_MAX_SESSIONS', '0'), ('LLM_HISTORY_MAX_SESSIONS', '99999999999999'),
                           ('LLM_HISTORY_MAX_BYTES', '12'), ('LLM_HISTORY_MAX_BYTES', 'unexpected')]:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp).resolve()
                out = self.history('llm_history_commit session question answer; echo rc=$?\n',
                                   directory, **{key: value})
                self.assertEqual(out.strip(), 'rc=1')
                self.assertFalse((directory / 'history').exists())


class FollowupSessionResetTest(unittest.TestCase):
    def dialog(self, inputs, *, first='介绍西湖', route='native_live', enabled='1',
               exit_enabled='0', guard='1', prompt_failure=False, pipeline=None):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            (directory / 'inputs').write_text('\n'.join(inputs) + '\n')
            code = functions(*SESSION_FUNCTIONS) + r'''
FOLLOWUP_ENABLED=1; FOLLOWUP_MODE=local_record; FOLLOWUP_RECORD_MODE=$ROUTE
[ "$ROUTE" != native_multirounds ] || FOLLOWUP_MODE=native_multirounds
SUPPRESS_DUP_SECONDS=5; calls=0; FOLLOWUP_VAD_PID=; FOLLOWUP_ARM_FILE=$TEST_DIR/arm
NATIVE_DIALOG_INPUT_MAX_REPROMPTS=2; FOLLOWUP_TIMEOUT=1; BACKEND=deepseek
is_system1_root() { [ "$ROUTE" = native_live ]; }
log() { :; }; set_state() { STATE=$1; }; pause_native_asr() { :; }; resume_native_asr() { echo RESUME; }
led_feedback_llm_accept() { :; }; led_feedback_followup_asr_ok() { :; }; led_off() { :; }
led_feedback_llm_followup_listening() { :; }; led_feedback_error() { :; }; sleep() { :; }
finish_llm_playback() { echo CLEAN; }
send_text_and_play() { printf 'LLM|%s|%s\n' "$1" "$2"; }
play_native_dialog_prompt() { printf 'PROMPT|%s\n' "$1"; [ "$PROMPT_FAIL" != 1 ]; }
get_aivs_lab_latest_dialog_id() { echo dialog; }; native_followup_mark_multirounds() { echo MARK; }
native_followup_tts_start() { :; }; native_followup_tts_end() { :; }
next_input() {
    calls=$((calls+1)); FOLLOWUP_TEXT=$(sed -n "${calls}p" "$TEST_DIR/inputs")
    [ -n "$FOLLOWUP_TEXT" ] || return 124
}
wait_native_live_asr() { next_input; }; wait_native_followup_text() { next_input; }
wait_or_run_followup_vad() { next_input; }; transcribe_followup_voice() { return 0; }
'''
            if pipeline is not None:
                # Exercise the real request guards; only model, audio and hardware
                # boundaries are stubbed. Fixed time keeps the duplicate window open.
                code += functions('send_text_native', 'send_text_and_play',
                                  'is_recent_duplicate_llm_query', 'record_llm_query')
                code += r'''
LLM_PIPELINE=$PIPELINE; TTS_ENGINE=server; DEVICE_TTS_STREAM=0
LAST_LLM_QUERY_FILE=$TEST_DIR/last-query; LAST_LLM_TS_FILE=$TEST_DIR/last-ts
date() { printf '1000\n'; }
set_busy() { :; }; apply_llm_master_volume() { :; }; freeze_native_player() { :; }
resume_native_player() { :; }; led_feedback_llm_playing() { :; }
start_followup_vad_prearm() { :; }; arm_followup_vad() { :; }
monotonic_ms() { echo 1000; }; elapsed_s() { echo 0; }
llm_direct_answer() { printf 'LLM|%s|%s\n' "$1" "$2"; LLM_DIRECT_ANSWER=answer; }
http_stream_play() { printf 'LLM|%s|%s\n' "$session_id" "$text"; }
tts_play_text() { :; }; llm_history_commit() { :; }
'''
            code += r'''
handle_llm_dialog same-session "$FIRST"
printf 'END|state=%s|reads=%s|session=%s|dedup=%s\n' "$STATE" "$calls" "$CURRENT_SESSION_ID" "$SUPPRESS_DUP_SECONDS"
'''
            return run_shell(code, directory, ROUTE=route, FIRST=first, FOLLOWUP_RESET_ENABLED=enabled,
                             FOLLOWUP_EXIT_ENABLED=exit_enabled, NATIVE_DIALOG_INPUT_GUARD=guard,
                             PIPELINE=pipeline or '',
                             PROMPT_FAIL=str(int(prompt_failure))).splitlines()

    def test_reset_accepts_same_question_without_disabling_later_duplicate_guards(self):
        for route in ('native_live', 'native_multirounds', 'window'):
            for pipeline in ('native', 'server'):
                with self.subTest(route=route, pipeline=pipeline):
                    rows = self.dialog(['换个话题', '介绍西湖', '介绍西湖'],
                                       route=route, pipeline=pipeline)
                    requests = [row.split('|', 2) for row in rows if row.startswith('LLM|')]
                    expected = 3 if route == 'native_live' else 2
                    self.assertEqual(len(requests), expected)
                    self.assertNotEqual(requests[0][1], requests[1][1])
                    self.assertTrue(all(row[2] == '介绍西湖' for row in requests))
                    self.assertIn('END|state=IDLE|reads=4|session=|dedup=5', rows)

    def test_disabled_reset_keeps_existing_duplicate_policy(self):
        for route in ('native_live', 'native_multirounds', 'window'):
            for pipeline in ('native', 'server'):
                with self.subTest(route=route, pipeline=pipeline):
                    rows = self.dialog(['介绍西湖'], route=route, pipeline=pipeline, enabled='0')
                    requests = [row for row in rows if row.startswith('LLM|')]
                    self.assertEqual(len(requests), 2 if route == 'native_live' else 1)
                    self.assertTrue(all(row.startswith('LLM|same-session|') for row in requests))
                    self.assertIn('END|state=IDLE|reads=2|session=|dedup=5', rows)

    def test_reset_duplicate_exemption_is_used_once_by_only_the_selected_session(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            code = functions('is_recent_duplicate_llm_query', 'record_llm_query') + r'''
SUPPRESS_DUP_SECONDS=5; FOLLOWUP_RESET_QUERY_SESSION=reset-session
LAST_LLM_QUERY_FILE=$TEST_DIR/query; LAST_LLM_TS_FILE=$TEST_DIR/ts
date() { echo 1000; }
record_llm_query repeated
is_recent_duplicate_llm_query repeated unrelated-session; echo other=$?
is_recent_duplicate_llm_query repeated reset-session; echo reset=$?
is_recent_duplicate_llm_query repeated reset-session; echo next=$?
printf 'query=%s|ts=%s|dedup=%s\n' "$(cat "$LAST_LLM_QUERY_FILE")" "$(cat "$LAST_LLM_TS_FILE")" "$SUPPRESS_DUP_SECONDS"
'''
            self.assertEqual(run_shell(code, directory).splitlines(),
                             ['other=0', 'reset=1', 'next=0', 'query=repeated|ts=1000|dedup=5'])

    def test_exact_reset_changes_next_question_session_in_all_routes(self):
        for route in ('native_live', 'native_multirounds', 'window'):
            for command in ('换个话题', '重新开始'):
                with self.subTest(route=route, command=command):
                    rows = self.dialog([command, '介绍火星'], route=route)
                    requests = [row.split('|', 2) for row in rows if row.startswith('LLM|')]
                    self.assertEqual([row[2] for row in requests], ['介绍西湖', '介绍火星'])
                    self.assertNotEqual(requests[0][1], requests[1][1])
                    self.assertEqual(sum(row.startswith('PROMPT|') for row in rows), 1)
                    self.assertIn('END|state=IDLE|reads=3|session=|dedup=5', rows)

    def test_reset_is_opt_in_and_independent_of_exit_flag(self):
        for enabled in ('0', '', 'true', '2'):
            rows = self.dialog(['换个话题'], enabled=enabled, exit_enabled='1')
            self.assertIn('LLM|same-session|换个话题', rows)
        rows = self.dialog(['换个话题', '介绍火星'], exit_enabled='0')
        self.assertNotIn('LLM|same-session|换个话题', rows)

    def test_exact_matching_preserves_negation_quotes_and_discussion(self):
        for text in ('不要重新开始', '解释换个话题的意思', '“换个话题”', '"重新开始"',
                     '请换个话题', '换个话题后怎么办', '换 个话题', '小爱同学重新开始'):
            with self.subTest(text=text):
                self.assertIn('LLM|same-session|' + text, self.dialog([text]))
        for text in ('  换个话题。 ', '\t重新开始！\t', '换个话题!?'):
            with self.subTest(text=text):
                rows = self.dialog([text, '下一问'])
                self.assertEqual(sum(row.startswith('LLM|') for row in rows), 2)

    def test_first_question_and_first_completion_do_not_reset(self):
        for route in ('native_live', 'native_multirounds', 'window'):
            self.assertIn('LLM|same-session|换个话题', self.dialog([], first='换个话题', route=route))
        rows = self.dialog(['重新开始'], first='帮我查一下')
        self.assertIn('LLM|same-session|帮我查一下，重新开始', rows)
        self.assertEqual(sum(row.startswith('PROMPT|') for row in rows), 1)

    def test_followup_completion_can_reset_and_discard_pending_fragment(self):
        rows = self.dialog(['帮我查一下', '重新开始', '介绍火星'])
        self.assertEqual(sum(row.startswith('PROMPT|') for row in rows), 2)
        requests = [row.split('|', 2) for row in rows if row.startswith('LLM|')]
        self.assertEqual([row[2] for row in requests], ['介绍西湖', '介绍火星'])
        self.assertNotEqual(requests[0][1], requests[1][1])

    def test_reset_does_not_depend_on_completion_guard(self):
        rows = self.dialog(['换个话题', '介绍火星'], guard='0')
        self.assertEqual(sum(row.startswith('LLM|') for row in rows), 2)
        self.assertEqual(sum(row.startswith('PROMPT|') for row in rows), 1)

    def test_failed_confirmation_returns_idle_without_another_listen(self):
        for route in ('native_live', 'native_multirounds', 'window'):
            with self.subTest(route=route):
                rows = self.dialog(['换个话题', '不应收听'], route=route, prompt_failure=True)
                self.assertEqual([row for row in rows if row.startswith('LLM|')], ['LLM|same-session|介绍西湖'])
                self.assertIn('END|state=IDLE|reads=1|session=|dedup=5', rows)
                self.assertEqual(rows.count('CLEAN'), 1)
                self.assertEqual(rows.count('RESUME'), 1)

    def test_repeated_resets_produce_distinct_sessions_without_model_control_turns(self):
        rows = self.dialog(['换个话题', '第一问', '重新开始', '第二问'])
        requests = [row.split('|', 2) for row in rows if row.startswith('LLM|')]
        self.assertEqual([row[2] for row in requests], ['介绍西湖', '第一问', '第二问'])
        self.assertEqual(len({row[1] for row in requests}), 3)

    def test_new_wakes_get_distinct_safe_session_ids_even_in_the_same_second(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            code = functions('new_llm_session_id') + r'''
BACKEND=deepseek
date() { printf '1234\n'; }
new_llm_session_id; printf '%s\n' "$NEW_LLM_SESSION_ID"
new_llm_session_id; printf '%s\n' "$NEW_LLM_SESSION_ID"
'''
            first, second = run_shell(code, directory).splitlines()
            self.assertNotEqual(first, second)
            self.assertRegex(first, r'^native_first_deepseek_1234_[0-9]+_1$')
            self.assertRegex(second, r'^native_first_deepseek_1234_[0-9]+_2$')

    def test_reset_words_bypass_native_asr_length_gate_without_mac(self):
        for enabled in ('0', '1'):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp).resolve()
                (directory / 'voice.wav').write_bytes(b'fixture')
                code = functions('transcribe_followup_voice', 'transcribe_followup_voice_native',
                                 'is_followup_exit_command', 'is_followup_reset_command')
                code = code.replace('/tmp/voice.wav', str(directory / 'voice.wav'))
                code = code.replace('/tmp/native_followup_ai_service.json', str(directory / 'result'))
                code += r'''
FOLLOWUP_ASR_ENGINE=native; FOLLOWUP_NATIVE_ASR_FALLBACK_MAC=1; FOLLOWUP_NATIVE_MIN_QUERY_BYTES=20
FOLLOWUP_NATIVE_ASR_TIMEOUT=1
json_escape() { cat; }; log() { :; }; ubus() { echo '{"code":0}'; }
extract_ai_service_asr_query() { cat >/dev/null; printf '重新开始'; }
transcribe_followup_voice_mac() { echo UNEXPECTED_MAC; return 1; }
transcribe_followup_voice
printf 'RESULT=%s\n' "$?"
'''
                out = run_shell(code, directory, FOLLOWUP_RESET_ENABLED=enabled)
                if enabled == '1':
                    self.assertEqual(out.strip(), 'RESULT=0')
                else:
                    self.assertIn('UNEXPECTED_MAC', out)


if __name__ == '__main__':
    unittest.main()
