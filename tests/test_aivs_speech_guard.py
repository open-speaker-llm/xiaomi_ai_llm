"""Exercise real C parsing without touching a speaker or sending process signals."""
import json
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.search(r'^UNSUPPORTED_PATTERNS="(.*)"$',
                    (ROOT / 'device/native_first.env.example').read_text(), re.M).group(1)
FAILURE_VARIANTS = [
    '这个我暂时还回答不上诶，我要再学习学习',
    '这可把我难住了，看来要更努力学习了',
    '被难住了诶，看来我还要再学习一下',
    '这可把我问住了',
    '看来我还得再学习一下',
    '我需要继续学习',
    '我还要多学学',
]


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class AivsSpeechGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.temp.name) / 'guard'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-o', str(cls.bin),
                        str(ROOT / 'device/aivs_guard/aivs_speech_guard.c')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def classify(self, rows, pattern=PATTERN):
        result = subprocess.run([str(self.bin), '--classify', pattern],
                                input='\n'.join(rows) + '\n', text=True,
                                capture_output=True, check=True, timeout=5)
        return result.stdout.splitlines()

    def record(self, text, **header):
        return {'header': {'dialog_id': 'test', 'name': 'Speak',
                           'namespace': 'SpeechSynthesizer', **header},
                'payload': {'text': text}}

    def test_failure_utf8_and_unicode_escapes(self):
        row = self.record('这个我暂时还回答不上诶，我要再学习学习')
        self.assertEqual(self.classify([json.dumps(row, ensure_ascii=False), json.dumps(row)]),
                         ['block', 'block'])

    def test_previously_missed_learning_reply(self):
        row = json.dumps(self.record('这可把我难住了，看来要更努力学习了'))
        self.assertEqual(self.classify([row]), ['block'])

    def test_learning_failure_family_utf8_and_escaped(self):
        rows = [json.dumps(self.record(text), ensure_ascii=escaped)
                for text in FAILURE_VARIANTS for escaped in [False, True]]
        self.assertEqual(self.classify(rows), ['block'] * len(rows))

    def test_shell_and_helper_share_failure_family(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        assignment = re.search(r'^UNSUPPORTED_PATTERNS=.*$', source, re.M).group()
        function = re.search(r'^is_unsupported_result\(\) \{.*?^\}', source, re.M | re.S).group()
        rows = FAILURE_VARIANTS + ['现在是上午九点', '灯已打开', '今天晴天']
        expected = ['block'] * len(FAILURE_VARIANTS) + ['pass'] * 3
        script = assignment + '\n' + function + '\nRESULT_DOMAIN=; RESULT_ACTION=;\n'
        for text in rows:
            script += 'RESULT_SPEAK=' + shlex.quote(text) + '; '
            script += 'if is_unsupported_result; then echo block; else echo pass; fi\n'
        result = subprocess.run(['sh', '-c', script], text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(self.classify([json.dumps(self.record(text)) for text in rows]), expected)

    def test_preserves_native_answers_and_other_instruction_types(self):
        rows = [self.record('现在是上午九点'), self.record('灯已打开'),
                self.record('不支持', name='RecognizeResult', namespace='SpeechRecognizer'),
                self.record('不知道', name='FinishSpeakStream'),
                self.record('暂时', dialog_id=''), self.record('正常回答🙂')]
        self.assertEqual(self.classify([json.dumps(row) for row in rows]), ['pass'] * len(rows))

    def test_only_payload_text_can_trigger(self):
        row = self.record('现在是上午九点')
        row['extra'] = {'text': '不会'}
        self.assertEqual(self.classify([json.dumps(row)]), ['pass'])

    def test_malformed_missing_and_partial_json_pass(self):
        rows = ['{"header":', '{}', 'null', json.dumps(self.record('不会'))[:-2],
                json.dumps(self.record('不会')) + ' trailing',
                json.dumps(self.record('x')).replace('"x"', '"\\uD800"')]
        self.assertEqual(self.classify(rows), ['pass'] * len(rows))

    def test_lease_releases_only_its_own_pause(self):
        # Mock kill: no real process receives a signal during this safety test.
        source = ROOT / 'device/aivs_guard/aivs_speech_guard.c'
        harness = Path(self.temp.name) / 'lease.c'
        binary = Path(self.temp.name) / 'lease'
        harness.write_text('#define kill fake_kill\n#define main guard_main\n'
                           f'#include "{source}"\n' + r'''
#undef main
static int signals;
int fake_kill(pid_t pid, int sig) {
    if (pid != 42 || sig != SIGCONT) abort();
    ++signals; return 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 9;
    FILE *f = fopen(argv[1], "w"); fputs("guard:123\n", f); fclose(f);
    release(argv[1], "guard:123\n", 42);
    if (signals != 1 || access(argv[1], F_OK) == 0) return 1;
    f = fopen(argv[1], "w"); fputs("client-owned\n", f); fclose(f);
    release(argv[1], "guard:123\n", 42);
    if (signals != 1 || access(argv[1], F_OK) != 0) return 2;
    unlink(argv[1]);
    release(argv[1], "guard:123\n", 42);
    return signals == 1 ? 0 : 3;
}
''')
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-o', str(binary),
                        str(harness)], check=True)
        subprocess.run([str(binary), str(Path(self.temp.name) / 'marker')],
                       check=True, capture_output=True, timeout=5)

    def test_escaped_quotes_surrogates_and_configured_regex(self):
        rows = [json.dumps(self.record('他说“未知答案”🙂')),
                json.dumps(self.record('quoted "unknown answer"'))]
        self.assertEqual(self.classify(rows, '未知答案|unknown answer'), ['block', 'block'])
        self.assertEqual(self.classify(rows, '^不支持$'), ['pass', 'pass'])


if __name__ == '__main__':
    unittest.main()
