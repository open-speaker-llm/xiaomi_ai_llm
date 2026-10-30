import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from server import main as server_main
from server.followup_asr import create_app


ROOT = Path(__file__).resolve().parents[1]


class FollowupAsrServiceTest(unittest.TestCase):
    def test_asr_only_service_uses_quality_gate_without_llm_startup(self):
        class FakeAsr:
            score = -0.2
            async def transcribe_with_info(self, data, sample_rate):
                return {"text": "那它适合什么时候去", "avg_logprob": self.score,
                        "no_speech_prob": 0.1, "speech_duration": 2, "duration": 8}

        with patch('server.asr.whisper_client.WhisperASR', return_value=FakeAsr()) as model, \
                patch('torch.set_num_threads') as set_threads, \
                patch.object(server_main, 'create_llm_clients') as llm, \
                patch.object(server_main, 'create_tts_client') as tts:
            with TestClient(create_app('small', 2)) as client:
                model.assert_called_once_with(model_name='small', language='zh', device='cpu')
                set_threads.assert_called_once_with(2)
                self.assertEqual(model.return_value.quality_min_logprob, -0.75)
                self.assertEqual(client.get('/').json()['service'], 'followup-asr')
                result = client.post('/api/v1/route/asr',
                                     files={'file': ('test.wav', bytes(200), 'audio/wav')},
                                     data={'session_id': 'test-followup-service'})
                self.assertEqual(result.status_code, 200)
                self.assertIn('ROUTE=llm', result.text)
                self.assertIn('TEXT=那它适合什么时候去', result.text)
                model.return_value.score = -0.9
                rejected = client.post('/api/v1/route/asr',
                                       files={'file': ('test.wav', bytes(200), 'audio/wav')})
                self.assertIn('ROUTE=empty', rejected.text)
                self.assertIn('REASON=low_logprob:', rejected.text)
                self.assertEqual(client.post('/api/v1/stream/chat').status_code, 404)
            self.assertIsNone(server_main.asr_client)
            llm.assert_not_called()
            tts.assert_not_called()

    def test_model_initialization_failure_clears_asr_reference(self):
        with patch.object(server_main, 'asr_client', object()), \
                patch('torch.set_num_threads'), \
                patch('server.asr.whisper_client.WhisperASR', side_effect=RuntimeError('model load failed')):
            with self.assertRaisesRegex(RuntimeError, 'model load failed'):
                with TestClient(create_app('small', 2)):
                    self.fail('Failed initialization must not reach ready state')
            self.assertIsNone(server_main.asr_client)

    def test_quality_gate_setup_failure_releases_created_model(self):
        class InvalidAsr:
            @property
            def quality_min_logprob(self):
                return None

            @quality_min_logprob.setter
            def quality_min_logprob(self, value):
                raise RuntimeError('quality setup failed')

        with patch('torch.set_num_threads'), \
                patch('server.asr.whisper_client.WhisperASR', return_value=InvalidAsr()):
            with self.assertRaisesRegex(RuntimeError, 'quality setup failed'):
                with TestClient(create_app('small', 2)):
                    self.fail('Failed initialization must not reach ready state')
            self.assertIsNone(server_main.asr_client)

    def test_lifespan_exception_releases_asr_reference(self):
        class FakeAsr:
            pass

        async def fail_after_startup():
            app = create_app('local-model.pt', 3)
            async with app.router.lifespan_context(app):
                self.assertIsNotNone(server_main.asr_client)
                raise RuntimeError('lifespan interrupted')

        with patch('torch.set_num_threads'), \
                patch('server.asr.whisper_client.WhisperASR', return_value=FakeAsr()):
            with self.assertRaisesRegex(RuntimeError, 'lifespan interrupted'):
                asyncio.run(fail_after_startup())
            self.assertIsNone(server_main.asr_client)

    def test_app_creation_does_not_import_optional_model_dependencies(self):
        with tempfile.TemporaryDirectory(prefix='xiaomi-followup-import-') as directory:
            config = Path(directory, 'config.yaml')
            config.write_text('server:\n  mode: tts-only\n')
            code = r'''
import importlib.abc, sys
blocked = ('torch', 'whisper', 'numpy', 'soundfile', 'openai', 'anthropic',
           'server.asr', 'server.llm', 'server.tts', 'server.audio')
class RejectOptionalModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('optional dependency imported before startup: ' + fullname)
sys.meta_path.insert(0, RejectOptionalModels())
from server.followup_asr import create_app
app = create_app('small', 2)
assert any(route.path == '/api/v1/route/asr' for route in app.routes)
assert not any(any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)
               for name in sys.modules)
'''
            run = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True,
                                 text=True, timeout=15,
                                 env={'PATH': os.environ.get('PATH', ''),
                                      'XIAOMI_SERVER_CONFIG': str(config)})
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
