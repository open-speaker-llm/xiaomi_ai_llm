import json
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'device/native_first_client.sh').read_text()


def functions(*names):
    return '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', SOURCE, re.M | re.S).group()
                     for name in names)


class AudioOptimizationTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_real_c_gate_handles_failure_without_touching_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp, 'gate')
            subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-DCONTROL_DIR="' + temp + '/state"',
                            str(ROOT / 'device/native_asr/test_failure_gate.c'),
                            '-lpthread', '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS: early failure gate', result.stdout)

    def route(self, marker, *, speak=None, last='', query='解释这个问题', enabled='1'):
        with tempfile.TemporaryDirectory() as temp:
            rows = [{'header': {'dialog_id': 'current', 'name': 'RecognizeResult',
                                'namespace': 'SpeechRecognizer'},
                     'payload': {'is_final': True, 'results': [{'text': query}]}}]
            if speak is not None:
                rows.append({'header': {'dialog_id': 'current', 'name': 'Speak',
                                        'namespace': 'SpeechSynthesizer'}, 'payload': {'text': speak}})
            Path(temp, 'instruction').write_text('\n'.join(json.dumps(row, ensure_ascii=False,
                                                        separators=(',', ':')) for row in rows))
            Path(temp, 'last').write_text(last)
            code = functions('reset_native_result', 'get_native_result_aivs_lab', 'is_unsupported_result')
            code += '\nDIR=' + shlex.quote(temp) + r'''
AIVS_LAB_INSTRUCTION_LOG=$DIR/instruction; AIVS_LAB_LAST_DIALOG_FILE=$DIR/last
AIVS_FAILURE_DIALOG=$DIR/failure; AIVS_LAB_LOOKBACK_LINES=40
DIRECT_LLM_QUERY_PATTERNS='呼叫DeepSeek'; UNSUPPORTED_PATTERNS='回答不上'
is_system1_root() { return 0; }; json_text_unescape() { cat; }; log() { :; }
'''
            code += '\nNATIVE_AIVS_LAB_RESULT_SYSTEM1=' + enabled + '\n'
            code += 'printf "%s\\n" "' + marker + '" > "$AIVS_FAILURE_DIALOG"\n'
            code += 'get_native_result_aivs_lab\necho "ret=$?:source=$RESULT_SOURCE:query=$RESULT_QUERY"\n'
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

    def test_missing_speak_hands_off_only_current_dialog_and_owner(self):
        self.assertEqual(self.route('$$ current'),
                         'ret=0:source=aivs_lab_early_failure:query=解释这个问题')
        for marker in ('$$ previous', '1 current', '', '$$ current extra'):
            self.assertEqual(self.route(marker), 'ret=1:source=:query=解释这个问题')
        self.assertEqual(self.route('$$ current', last='current'), 'ret=1:source=:query=')
        self.assertEqual(self.route('$$ current', query=''), 'ret=1:source=:query=')
        self.assertEqual(self.route('$$ current', enabled='0'), 'ret=1:source=:query=')

    def test_original_failure_polling_and_native_answers_still_work(self):
        self.assertEqual(self.route('', speak='这个问题回答不上'),
                         'ret=0:source=aivs_lab_instruction:query=解释这个问题')
        for text in ('灯已打开', '现在是九点', '今天晴天'):
            self.assertEqual(self.route('', speak=text), 'ret=1:source=:query=解释这个问题')

    def test_default_volume_has_no_extra_five_db_and_override_does_not_accumulate(self):
        assignment = re.search(r'^DEVICE_TTS_STREAM_MASTER_BOOST=.*$', SOURCE, re.M).group()
        for boost, expected in ((None, 145), (10, 155)):
            code = functions('calc_llm_master_volume', 'apply_llm_master_volume', 'restore_llm_master_volume')
            code += '\nunset DEVICE_TTS_STREAM_MASTER_BOOST\n'
            if boost is not None:
                code += f'DEVICE_TTS_STREAM_MASTER_BOOST={boost}\n'
            code += assignment + r'''
DEVICE_MASTER=145; MASTER_RESTORE_VALUE=; LLM_SESSION_MASTER_TARGET=
LLM_MASTER_VOLUME=auto; LLM_MASTER_SCALE=100; LLM_MASTER_CURRENT_SCALE=100
LLM_MASTER_MIN=96; LLM_MASTER_MAX=160; TTS_ENGINE=device; DEVICE_TTS_STREAM=1
log() { :; }; get_native_media_volume() { echo 170; }
get_master_volume() { echo "$DEVICE_MASTER"; }; set_master_volume() { DEVICE_MASTER=$1; }
apply_llm_master_volume; echo "$DEVICE_MASTER"
apply_llm_master_volume; echo "$DEVICE_MASTER"
restore_llm_master_volume; echo "$DEVICE_MASTER"
apply_llm_master_volume; echo "$DEVICE_MASTER"
restore_llm_master_volume; echo "$DEVICE_MASTER"
'''
            result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [str(expected), str(expected), '145',
                                                          str(expected), '145'])

    def test_auto_preserves_quiet_and_zero_master_without_media_query(self):
        code = functions('calc_llm_master_volume') + r'''
LLM_MASTER_VOLUME=auto; LLM_SESSION_MASTER_TARGET=; LLM_MASTER_CURRENT_SCALE=100
log() { :; }; get_native_media_volume() { echo unexpected-media-query >&2; echo 170; }
for value in 0 60 145 180; do MASTER_RESTORE_VALUE=$value; calc_llm_master_volume; done
'''
        result = subprocess.run(['sh', '-c', code], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['0', '60', '145', '180'])
        self.assertEqual(result.stderr, '')
