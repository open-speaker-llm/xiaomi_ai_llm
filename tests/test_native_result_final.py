"""Exercise real routing across partial/final snapshots without speaker or LLM."""
import json
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def result(text, final=False, dialog='current'):
    return {'header': {'dialog_id': dialog, 'name': 'RecognizeResult',
                       'namespace': 'SpeechRecognizer'},
            'payload': {'is_final': final, 'results': [{'text': text}]}}


def speak(text, dialog='current'):
    return {'header': {'dialog_id': dialog, 'name': 'Speak',
                       'namespace': 'SpeechSynthesizer'}, 'payload': {'text': text}}


class NativeResultFinalTest(unittest.TestCase):
    def replay(self, snapshots, marker='', endpoint=None, denial=None):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{.*?(?=^[a-zA-Z_]\w*\(\) \{|\Z)', source,
                                       re.M | re.S).group()
                              for name in ('reset_native_result', 'get_native_result_aivs_lab',
                                           'endpoint_denial_allows', 'is_unsupported_result', 'json_unicode_decode',
                                           'json_text_unescape'))
        with tempfile.TemporaryDirectory() as temp:
            for i, rows in enumerate(snapshots):
                Path(temp, str(i)).write_text('\n'.join(json.dumps(row, separators=(',', ':'))
                                                        for row in rows) + '\n')
            code = functions + '\nDIR=' + shlex.quote(temp) + r'''
NATIVE_AIVS_LAB_RESULT_SYSTEM1=1; AIVS_LAB_LOOKBACK_LINES=40
AIVS_LAB_INSTRUCTION_LOG=$DIR/instruction; AIVS_LAB_LAST_DIALOG_FILE=$DIR/last
AIVS_FAILURE_DIALOG=$DIR/failure
NATIVE_ENDPOINT_RESULT_DIR=$DIR/endpoint
mkdir "$NATIVE_ENDPOINT_RESULT_DIR"
DIRECT_LLM_QUERY_PATTERNS='DEEPSEEK'; UNSUPPORTED_PATTERNS='回答不上'
is_system1_root() { return 0; }; log() { :; }
'''
            # Deliberately allow $$ only in this fixed test fixture.
            code += 'printf "%s\\n" "' + marker + '" > "$AIVS_FAILURE_DIALOG"\n'
            if denial is not None:
                code += 'mkdir "$NATIVE_ENDPOINT_RESULT_DIR.denied"\n'
                for bucket, content in denial.items():
                    code += 'printf %s ' + shlex.quote(content) + ' > "$NATIVE_ENDPOINT_RESULT_DIR.denied/b_"' + shlex.quote(bucket) + '\n'
            for i in range(len(snapshots)):
                if endpoint is not None:
                    for dialog, status in endpoint[i].items():
                        if status is None:
                            code += 'rm -f "$NATIVE_ENDPOINT_RESULT_DIR/"' + shlex.quote(dialog) + '\n'
                            continue
                        record = 'NW1 123 456 ' + 'ab' * 16 + ' ' + status + '\n'
                        code += 'printf %s ' + shlex.quote(record) + ' > "$NATIVE_ENDPOINT_RESULT_DIR/"' + shlex.quote(dialog) + '\n'
                code += f'cp "$DIR/{i}" "$AIVS_LAB_INSTRUCTION_LOG"\n'
                code += '''get_native_result_aivs_lab
rc=$?
printf '%s|%s|%s|%s\n' "$rc" "$RESULT_QUERY" "$RESULT_SOURCE" "$(cat "$DIR/last" 2>/dev/null)"
'''
            run = subprocess.run(['sh'], input=code, text=True, capture_output=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stderr, '')
            return run.stdout.splitlines()

    def test_forced_final_never_routes_even_with_trigger_or_failure_speak(self):
        for status in ('pending', 'failed', 'limit', 'broken'):
            self.assertEqual(self.replay([[result('问问DEEPSEEK残句', True), speak('回答不上')]],
                                         '$$ current', [{'current': status}]), ['1|||'])

    def test_completed_endpoint_final_routes_once_after_pending(self):
        rows = [result('问问DEEPSEEK完整问题', True)]
        self.assertEqual(self.replay([rows, rows, rows], endpoint=[{'current': 'pending'},
                                                                 {'current': 'quiet'}, {}]),
                         ['1|||', '0|问问DEEPSEEK完整问题|aivs_lab_instruction|current', '1|||current'])

    def test_unrelated_failed_endpoint_does_not_block_native_dialog(self):
        self.assertEqual(self.replay([[result('问问DEEPSEEK新问题', True)]],
                                     endpoint=[{'old': 'failed'}]),
                         ['0|问问DEEPSEEK新问题|aivs_lab_instruction|current'])

    def test_pruned_quiet_still_requires_final_and_deduplicates(self):
        partial = [result('问问DEEPSEEK问题')]
        final = [result('问问DEEPSEEK完整问题', True)]
        self.assertEqual(self.replay([partial, partial, final, final], endpoint=[
            {'current': 'quiet'}, {'current': None}, {}, {}]), [
                '1|||', '1|||', '0|问问DEEPSEEK完整问题|aivs_lab_instruction|current', '1|||current'])

    def test_partial_then_revised_final_is_submitted_once(self):
        partial = result('问问DEEPSEEK')
        complete = result('问问DEEPSEEK为什么会发生海湾战争', True)
        self.assertEqual(self.replay([[partial], [partial, complete], [partial, complete]]),
                         ['1|||', '0|问问DEEPSEEK为什么会发生海湾战争|aivs_lab_instruction|current',
                          '1|||current'])

    def test_failure_speak_does_not_make_partial_final(self):
        self.assertEqual(self.replay([[result('请解释'), speak('这个问题回答不上')]]), ['1|||'])

    def test_early_failure_marker_cannot_make_partial_final(self):
        self.assertEqual(self.replay([[result('请解释')]], '$$ current'), ['1|||'])

    def test_empty_final_never_revives_partial(self):
        self.assertEqual(self.replay([[result('问问DEEPSEEK'), result('', True)]]), ['1|||'])

    def test_previous_dialog_final_cannot_complete_new_dialog_partial(self):
        self.assertEqual(self.replay([[result('问问DEEPSEEK旧问题', True, 'old'),
                                       result('问问DEEPSEEK新问题')]]), ['1|||'])

    def test_final_failures_route_but_native_success_stays_native(self):
        self.assertEqual(self.replay([[result('普通问题', True), speak('回答不上')]]),
                         ['0|普通问题|aivs_lab_instruction|current'])
        self.assertEqual(self.replay([[result('普通问题', True)]], '$$ current'),
                         ['0|普通问题|aivs_lab_early_failure|current'])
        self.assertEqual(self.replay([[result('现在几点', True), speak('现在九点')]]),
                         ['1|现在几点||'])

    def test_compacted_denial_rejects_late_final_after_journal_removed(self):
        rows = [result('问问DEEPSEEK旧问题', True)]
        self.assertEqual(self.replay([rows], denial={'c':'NRD1\ncurrent\n'}), ['1|||'])

    def test_compacted_lookup_is_exact_and_preserves_unrelated_native(self):
        rows = [result('问问DEEPSEEK新问题', True)]
        self.assertEqual(self.replay([rows], denial={'c':'NRD1\ncurrent-old\n'}),
                         ['0|问问DEEPSEEK新问题|aivs_lab_instruction|current'])

    def test_invalid_compacted_bucket_never_grants_permission(self):
        for data in ('', 'broken\ncurrent\n', 'NRD1\nwrong-prefix\n', 'NRD1\nbad id\n', 'NRD1\ncurrent-old', 'NRD1\n!END\n'):
            self.assertEqual(self.replay([[result('问问DEEPSEEK残句', True)]], denial={'c':data}), ['1|||'])
