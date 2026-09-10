import json
import re
import subprocess
import unittest
import tempfile
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.llm.minimax_client import MiniMaxClient

ROOT = Path(__file__).resolve().parents[1]


class NativeMiniMaxTest(unittest.TestCase):
    def test_template_switches_provider_with_backend_only(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        setup = source.split('LLM_THINKING=')[0]
        template = (ROOT / 'device/native_first.env.example').read_text()
        providers = {
            'deepseek': ('https://api.deepseek.com', 'deepseek-flash'),
            'minimax': ('https://api.minimaxi.com/v1', 'MiniMax-M2.7'),
            'glm': ('https://open.bigmodel.cn/api/paas/v4', 'glm-5.3-flash'),
            'kimi': ('https://api.moonshot.cn/v1', 'kimi-k2.6'),
        }
        for backend, (url, model) in providers.items():
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as td:
                config = template.replace('BACKEND=deepseek\n', f'BACKEND={backend}\n')
                for name in providers:
                    config = config.replace(f'{name.upper()}_API_KEY=\n', f'{name.upper()}_API_KEY={name}-dummy\n')
                path = Path(td) / 'config.env'
                path.write_text(config)
                script = 'unset LLM_API_BASE LLM_MODEL LLM_API_KEY; CONFIG_FILE=' + shlex.quote(str(path)) + '\n'
                script += setup + '\nprintf "%s|%s|%s" "$LLM_API_BASE" "$LLM_MODEL" "$LLM_API_KEY"'
                result = subprocess.run(['sh', '-c', script], text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout, f'{url}|{model}|{backend}-dummy')

    def function(self, name):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        return re.search(r'^' + name + r'\(\) \{.*?^\}', source, re.M | re.S).group()

    def test_provider_requests(self):
        for model in ('MiniMax-M2.7', 'deepseek-flash', 'glm-5.3-flash', 'kimi-k2.6'):
            result = subprocess.run(
                ['sh', '-c', self.function('llm_build_request') +
                 '\nLLM_MODEL=$1; LLM_THINKING=disabled; LLM_REASONING_EFFORT=low; llm_build_request "$2"',
                 'test', model, '{"role":"user","content":"你好"}'],
                text=True, capture_output=True, check=True,
            )
            request = json.loads(result.stdout)
            self.assertEqual(request['messages'][0]['content'], '你好')
            if model.startswith('MiniMax-'):
                self.assertTrue(request['reasoning_split'])
                self.assertNotIn('thinking', request)
            elif model == 'kimi-k2.6':
                self.assertEqual(request['thinking'], {'type': 'disabled'})
                self.assertEqual(request['temperature'], 0.6)
                self.assertNotIn('reasoning_effort', request)
            elif model == 'glm-5.3-flash':
                self.assertEqual(request['thinking'], {'type': 'enabled'})
                self.assertEqual(request['reasoning_effort'], 'low')
                self.assertNotIn('reasoning_split', request)
            else:
                self.assertEqual(request['thinking'], {'type': 'disabled'})
                self.assertNotIn('reasoning_split', request)

    def test_sse_ignores_reasoning_and_decodes_answer(self):
        chunks = [
            {'choices': [{'delta': {'reasoning_content': '不要播报思考'}}]},
            {'choices': [{'delta': {'content': '\n你好，"朋友"。'}}]},
            {'choices': [{'delta': {'content': '路径 C:\\test\t完成。'}}]},
            {'choices': [], 'usage': {'completion_tokens': 20}},
        ]
        for separators in ((',', ':'), (', ', ': ')):
            data = '\n'.join('data: ' + json.dumps(c, ensure_ascii=False, separators=separators)
                             for c in chunks) + '\ndata: [DONE]\n'
            result = subprocess.run(['sh', '-c', self.function('llm_sse_content') + '\nllm_sse_content'],
                                    input=data, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, ' 你好，"朋友"。\n路径 C:\\test 完成。\n')

    def test_minimax_config_defaults_and_explicit_override(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        setup = source[source.index('if [ "$BACKEND" = "minimax" ]; then'):source.index('LLM_THINKING=')]
        for explicit in ('', 'LLM_API_BASE=https://example.test/v1; LLM_MODEL=custom; LLM_API_KEY=explicit;'):
            result = subprocess.run(['sh', '-c', 'BACKEND=minimax; MINIMAX_API_KEY=dummy; ' + explicit +
                                     setup + '\nprintf "%s|%s|%s" "$LLM_API_BASE" "$LLM_MODEL" "$LLM_API_KEY"'],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, 'https://example.test/v1|custom|explicit' if explicit else
                             'https://api.minimaxi.com/v1|MiniMax-M2.7|dummy')

    def test_glm_uses_its_own_key_and_defaults(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        setup = source[source.index('if [ "$BACKEND" = "minimax" ]; then'):source.index('LLM_THINKING=')]
        result = subprocess.run(['sh', '-c', 'BACKEND=glm; GLM_API_KEY=glm-dummy; '
                                 'MINIMAX_API_KEY=minimax-dummy; DEEPSEEK_API_KEY=deepseek-dummy; ' + setup +
                                 '\nprintf "%s|%s|%s" "$LLM_API_BASE" "$LLM_MODEL" "$LLM_API_KEY"'],
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, 'https://open.bigmodel.cn/api/paas/v4|glm-5.3-flash|glm-dummy')

    def test_kimi_uses_its_own_key_and_defaults(self):
        source = (ROOT / 'device/native_first_client.sh').read_text()
        setup = source[source.index('if [ "$BACKEND" = "minimax" ]; then'):source.index('LLM_THINKING=')]
        result = subprocess.run(['sh', '-c', 'BACKEND=kimi; KIMI_API_KEY=kimi-dummy; GLM_API_KEY=glm-dummy; '
                                 'MINIMAX_API_KEY=minimax-dummy; DEEPSEEK_API_KEY=deepseek-dummy; ' + setup +
                                 '\nprintf "%s|%s|%s" "$LLM_API_BASE" "$LLM_MODEL" "$LLM_API_KEY"'],
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, 'https://api.moonshot.cn/v1|kimi-k2.6|kimi-dummy')


class ServerMiniMaxTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_and_stream_split_reasoning_only_for_minimax(self):
        for model in ('MiniMax-M2.7', 'deepseek-flash', 'glm-5.3-flash', 'kimi-k2.6'):
            client = MiniMaxClient(api_key='dummy', model=model)
            await client.client.close()
            create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='你好'))]))
            client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            self.assertEqual(await client.chat('你好'), '你好')
            if model.startswith('MiniMax-'):
                self.assertEqual(create.call_args.kwargs['extra_body'], {'reasoning_split': True})
            elif model == 'kimi-k2.6':
                self.assertEqual(create.call_args.kwargs['extra_body'], {'thinking': {'type': 'disabled'}})
                self.assertEqual(create.call_args.kwargs['temperature'], 0.6)
            elif model == 'glm-5.3-flash':
                self.assertEqual(create.call_args.kwargs['extra_body'], {
                    'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'})
            else:
                self.assertNotIn('extra_body', create.call_args.kwargs)

            async def chunks():
                yield SimpleNamespace(choices=[])
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='你好'))])

            create.return_value = chunks()
            self.assertEqual([part async for part in client.chat_stream('你好')], ['你好'])
            self.assertEqual('extra_body' in create.call_args.kwargs, model != 'deepseek-flash')

    async def test_glm_reasoning_effort_is_configurable(self):
        client = MiniMaxClient(api_key='dummy', model='glm-5.3-flash', reasoning_effort='high')
        await client.client.close()
        self.assertEqual(client.request_options['extra_body']['reasoning_effort'], 'high')


if __name__ == '__main__':
    unittest.main()
