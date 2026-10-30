"""Pure protocol contracts against both maintained source and deployed artifact."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'device/lib/native_protocol.sh'
TARGET = ROOT / 'device/native_first_client.sh'
BEGIN = '# BEGIN GENERATED NATIVE PROTOCOL\n'
END = '# END GENERATED NATIVE PROTOCOL\n'


def sources():
    client = TARGET.read_text()
    return {'source': SOURCE.read_text(),
            'artifact': client.split(BEGIN, 1)[1].split(END, 1)[0]}


def event(content=None, *, finish=None, index=0, **delta):
    if content is not None:
        delta['content'] = content
    choice = {'index': index, 'delta': delta}
    if finish is not None:
        choice['finish_reason'] = finish
    return 'data: ' + json.dumps({'choices': [choice]}) + '\n\n'


class NativeProtocolTest(unittest.TestCase):
    def run_protocol(self, code, command, data=b''):
        with tempfile.TemporaryDirectory(prefix='xiaomi-protocol-') as directory:
            result = subprocess.run(['sh', '-c', code + '\n' + command], input=data,
                                    capture_output=True, timeout=5, cwd=directory,
                                    env={**os.environ, 'LC_ALL': 'C', 'STATUS': directory + '/status'})
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b'')
            status = Path(directory, 'status')
            return result.stdout, status.read_text().strip() if status.exists() else None

    def sse(self, code, data):
        out, status = self.run_protocol(code, 'llm_sse_content "$STATUS"', data.encode())
        return out.decode(), status

    def test_loading_protocol_has_no_configuration_or_runtime_side_effects(self):
        for name, code in sources().items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                run = subprocess.run(['/bin/sh', '-c', code], cwd=directory, capture_output=True,
                                     env={'PATH': '', 'CONFIG_FILE': '/must-not-be-read'}, timeout=3)
                self.assertEqual((run.returncode, run.stdout, run.stderr), (0, b'', b''))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_json_escape_round_trips_all_control_bytes_quotes_unicode_and_final_newlines(self):
        text = ''.join(chr(i) for i in range(32)) + '"\\路径/你好😀\n\n'
        for name, code in sources().items():
            with self.subTest(name=name):
                out, _ = self.run_protocol(code, 'json_escape', text.encode())
                self.assertEqual(json.loads(b'"' + out + b'"'), text)
                self.assertNotIn(b'\n', out)
                self.assertNotIn(b'\t', out)

    def test_unicode_decoder_preserves_literal_escape_and_normalizes_speech_controls(self):
        text = '你好😀 "引号" \\u4f60 /路径\n\t\r\b\f'
        encoded = json.dumps(text)[1:-1] + '\n'
        for name, code in sources().items():
            with self.subTest(name=name):
                out, _ = self.run_protocol(code, 'json_unicode_decode', encoded.encode())
                self.assertEqual(out.decode(), '你好😀 "引号" \\u4f60 /路径   \n')

    def test_log_text_field_keeps_escaped_quotes_until_shared_decoding(self):
        text = '“引用”与"引号"😀'
        data = '[fixture] ' + json.dumps({'payload': {'text': text}}) + '\n'
        for name, code in sources().items():
            with self.subTest(name=name):
                out, _ = self.run_protocol(code, 'json_text_field | json_text_unescape', data.encode())
                self.assertEqual(out.decode(), text + '\n')

    def test_sse_unicode_and_only_choice_zero_content_are_spoken(self):
        data = event(reasoning_content='不播报')
        data += 'data: ' + json.dumps({'content': '不播报', 'choices': [
            {'index': 1, 'delta': {'content': '不播报'}},
            {'index': 0, 'delta': {'content': '你好😀，"朋友"。'}}]}) + '\n\n'
        data += event('字面量 \\u4f60；换行\n尾句。', finish='stop')
        data += 'data: {"choices":[],"usage":{"completion_tokens":7}}\n\ndata: [DONE]\n\n'
        for name, code in sources().items():
            with self.subTest(name=name):
                out, status = self.sse(code, data)
                self.assertEqual(out, '你好😀，"朋友"。\n字面量 \\u4f60；换行 尾句。\n')
                self.assertEqual(status, 'complete')

    def test_sse_supports_crlf_multiline_json_and_escaped_field_names(self):
        data = ': keepalive\r\nevent: message\r\nid: fixture\r\n'
        data += 'data: {"\\u0063hoices":[{"delta":{"content":\r\n'
        data += 'data: "\\u4f60\\u597d"},"finish_reason":"stop"}]}\r\n\r\n'
        for name, code in sources().items():
            with self.subTest(name=name):
                self.assertEqual(self.sse(code, data), ('你好\n', 'complete'))

    def test_done_or_stop_complete_but_errors_and_missing_end_remain_incomplete(self):
        cases = [
            (event('回答。') + 'data: [DONE]\n', 'complete'),
            (event('回答。', finish='stop'), 'complete'),
            (event('回答。'), 'incomplete'),
            (event('回答。', finish='length') + 'data: [DONE]\n', 'incomplete'),
            (event('回答。', finish='tool_calls') + 'data: [DONE]\n', 'incomplete'),
            (event('回答。') + 'data: {"error":{"message":"failed"}}\n\ndata: [DONE]\n', 'incomplete'),
            (event('回答。') + 'event: error\ndata: {"message":"failed"}\n\ndata: [DONE]\n', 'incomplete'),
            (event('回答。', finish='stop') + event('多余片段'), 'incomplete'),
            (event('回答。') + 'data: [DONE]\n' + event('多余片段'), 'incomplete'),
            (event('回答。') + event(finish='stop', index=1), 'incomplete'),
        ]
        for name, code in sources().items():
            for data, expected in cases:
                with self.subTest(name=name, data=data):
                    out, status = self.sse(code, data)
                    self.assertEqual(status, expected)
                    self.assertNotIn('多余片段', out)
                    self.assertNotIn('failed', out)

    def test_malformed_event_never_publishes_its_partial_text_even_before_done(self):
        valid = json.dumps({'choices': [{'delta': {'content': '不应播报'}}]})
        bad_events = [valid[:-1], valid + 'junk',
                      '{"choices":[{"delta":{"content":"bad\\x"}}]}',
                      '{"choices":[{"delta":{"content":"\\ud800"}}]}',
                      '{"choices":[{"delta":{"content":"\\ude00"}}]}',
                      '{"choices":[{"delta":{"content":"bad\ttab"}}]}',
                      '{"choices":[{"delta":{"content":"未闭合',
                      '{"choices":[{"delta":{"content":123}}]}',
                      '{"choices":[{"delta":{"content":"A"},"index":"0"}]}',
                      '{"choices":[{"delta":{"content":"A"},"index":{}}]}',
                      '{"choices":[{"delta":{"content":"A","content":"B"}}]}']
        for name, code in sources().items():
            for payload in bad_events:
                with self.subTest(name=name, payload=payload):
                    self.assertEqual(self.sse(code, 'data: ' + payload + '\n\ndata: [DONE]\n'),
                                     ('', 'incomplete'))

    def test_oversized_and_overly_nested_events_fail_without_publishing(self):
        payloads = [json.dumps({'choices': [{'delta': {'content': 'x' * 262144}}]}),
                    '{"unknown":' + '[' * 40 + '0' + ']' * 40 + '}']
        for name, code in sources().items():
            for payload in payloads:
                with self.subTest(name=name, size=len(payload)):
                    self.assertEqual(self.sse(code, 'data: ' + payload + '\n\ndata: [DONE]\n'),
                                     ('', 'incomplete'))

    def test_first_and_second_chunks_arrive_while_upstream_stays_open(self):
        for name, code in sources().items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                status = Path(directory, 'status')
                proc = subprocess.Popen(['sh', '-c', code + '\nllm_sse_content "$STATUS"'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env={**os.environ, 'STATUS': str(status)}, start_new_session=True)
                try:
                    for text in ('第一片😀。', '第二片。'):
                        proc.stdin.write(event(text).encode())
                        proc.stdin.flush()
                        self.assertTrue(select.select([proc.stdout], [], [], 2)[0], 'chunk buffered until EOF')
                        self.assertEqual(proc.stdout.readline().decode(), text + '\n')
                        self.assertFalse(status.exists())
                    proc.stdin.write(b'data: [DONE]\n\n')
                    proc.stdin.close()
                    proc.stdin = None
                    out, err = proc.communicate(timeout=3)
                    self.assertEqual((proc.returncode, out, err), (0, b'', b''))
                    self.assertEqual(status.read_text().strip(), 'complete')
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate(timeout=3)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox needed for device utility compatibility')
    def test_busybox_shell_awk_and_od_obey_the_same_unicode_contract(self):
        busybox = shutil.which('busybox')
        for name, code in sources().items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                for applet in ('awk', 'od'):
                    Path(directory, applet).symlink_to(busybox)
                data = event('你好😀，"引号"。') + 'data: [DONE]\n\n'
                run = subprocess.run([busybox, 'sh', '-c', code + '\nllm_sse_content "$STATUS"'],
                                     input=data, text=True, capture_output=True, timeout=5,
                                     env={'PATH': directory, 'STATUS': directory + '/status'})
                self.assertEqual((run.returncode, run.stdout, run.stderr), (0, '你好😀，"引号"。\n', ''))
                self.assertEqual(Path(directory, 'status').read_text().strip(), 'complete')
                run = subprocess.run([busybox, 'sh', '-c', code + '\njson_escape'],
                                     input='你好\n\t"\\\n', text=True, capture_output=True, timeout=5,
                                     env={'PATH': directory})
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(json.loads('"' + run.stdout + '"'), '你好\n\t"\\\n')


class NativeProtocolEmbedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('native_protocol_embed', ROOT / 'scripts/embed_native_protocol.py')
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def test_checked_in_artifact_matches_source_exactly(self):
        maintained, deployed = sources().values()
        self.assertEqual(maintained, deployed)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.main(['--check']), 0)

    def test_stale_check_is_read_only_and_embed_preserves_surrounding_code_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'protocol.sh')
            target = Path(directory, 'client.sh')
            source.write_text('fixture() { :; }\n')
            before, after = '#!/bin/sh\r\nunaltered_before\n', 'unaltered_after # 中文\r\n'
            old = before + BEGIN + 'stale\n' + END + after
            target.write_text(old)
            target.chmod(0o751)
            with patch.object(self.tool, 'SOURCE', source), patch.object(self.tool, 'TARGET', target), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(self.tool.main(['--check']), 1)
                self.assertEqual(target.read_bytes().decode(), old)
                self.assertEqual(self.tool.main([]), 0)
                self.assertEqual(target.read_bytes().decode(), before + BEGIN + source.read_text() + END + after)
                self.assertEqual(target.stat().st_mode & 0o777, 0o751)
                self.assertEqual(self.tool.main(['--check']), 0)
                self.assertEqual(self.tool.main([]), 0)

    def test_missing_duplicate_and_reversed_markers_are_refused(self):
        for text in ('no markers\n', BEGIN + BEGIN + END, END + BEGIN):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.tool.rendered_client(text, 'fixture\n')
