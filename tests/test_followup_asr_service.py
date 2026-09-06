import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from server import main as server_main
from server.followup_asr import create_app


class FollowupAsrServiceTest(unittest.TestCase):
    def test_asr_only_service_uses_quality_gate_without_llm_startup(self):
        class FakeAsr:
            score = -0.2
            async def transcribe_with_info(self, data, sample_rate):
                return {"text": "那它适合什么时候去", "avg_logprob": self.score,
                        "no_speech_prob": 0.1, "speech_duration": 2, "duration": 8}

        with patch.object(server_main, 'WhisperASR', return_value=FakeAsr()) as model:
            with TestClient(create_app('small', 2)) as client:
                model.assert_called_once_with(model_name='small', language='zh', device='cpu')
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
