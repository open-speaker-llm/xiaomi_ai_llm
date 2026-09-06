import unittest

import numpy as np

from server.asr.whisper_client import WhisperASR
from server.main import (
    conversation_histories,
    is_likely_assistant_echo,
    is_low_confidence_asr,
)


class AsrQualityTest(unittest.TestCase):
    def test_empty_text_is_low_confidence(self):
        low, reason = is_low_confidence_asr({"text": ""})
        self.assertTrue(low)
        self.assertEqual(reason, "empty_text")

    def test_high_no_speech_is_low_confidence(self):
        low, reason = is_low_confidence_asr({
            "text": "请不吝点赞订阅",
            "avg_logprob": -0.2,
            "no_speech_prob": 0.86,
            "speech_duration": 1.2,
            "duration": 4.0,
            "speech_active_ratio": 0.02,
            "speech_rms": 0.01,
        })
        self.assertTrue(low)
        self.assertTrue(reason.startswith("no_speech:"))

    def test_good_speech_passes_quality_gate(self):
        low, reason = is_low_confidence_asr({
            "text": "Mac电脑怎么重启",
            "avg_logprob": -0.2,
            "no_speech_prob": 0.1,
            "speech_duration": 1.4,
            "duration": 2.0,
            "speech_active_ratio": 0.12,
            "speech_rms": 0.03,
        })
        self.assertFalse(low)
        self.assertEqual(reason, "ok")

    def test_processed_pcm_rejects_observed_low_confidence_turns(self):
        # Observed during the 2026-09-06 boot1 test. Correct contextual followups
        # scored -0.36/-0.53/-0.55; nonsense turns scored -0.80 to -0.95.
        for score, expected_low in [(-0.36, False), (-0.53, False), (-0.55, False),
                                    (-0.80, True), (-0.91, True), (-0.95, True)]:
            info = {"text": "测试语音", "avg_logprob": score, "no_speech_prob": 0.1,
                    "speech_duration": 2, "duration": 8, "speech_active_ratio": 0.1,
                    "speech_rms": 0.05}
            low, _ = is_low_confidence_asr(info, min_logprob=-0.75)
            self.assertEqual(low, expected_low)
        # Existing raw/boot0 callers retain their original threshold.
        self.assertFalse(is_low_confidence_asr(info)[0])

    def test_low_energy_but_confident_followup_passes_quality_gate(self):
        low, reason = is_low_confidence_asr({
            "text": "电脑怎么重启",
            "avg_logprob": -0.54,
            "no_speech_prob": 0.63,
            "speech_duration": 4.8,
            "duration": 4.8,
            "active_ratio": 0.0,
            "speech_active_ratio": 0.0,
            "rms": 0.00143,
            "speech_rms": 0.00143,
        })
        self.assertFalse(low)
        self.assertEqual(reason, "ok")

    def test_capture_channel_selector_avoids_clipped_loud_channel(self):
        asr = WhisperASR.__new__(WhisperASR)
        audio = np.zeros((16000, 8), dtype=np.float32)
        audio[1000:5000, 1] = 1.0
        audio[1000:5000, 5] = np.sin(np.linspace(0, 120, 4000)) * 0.35

        _, info = asr._select_capture_channel(audio)

        self.assertEqual(info["channel"], 5)

    def test_assistant_echo_substring_is_rejected(self):
        session_id = "test_echo"
        conversation_histories[session_id] = [
            {"role": "user", "content": "呼叫DeepSeek"},
            {"role": "assistant", "content": "你好，我是DeepSeek，有什么可以帮你的吗？"},
        ]
        try:
            is_echo, reason = is_likely_assistant_echo("有什么可以帮你的吗", session_id)
            self.assertTrue(is_echo)
            self.assertEqual(reason, "assistant_echo_substring")
        finally:
            conversation_histories.pop(session_id, None)

    def test_user_followup_is_not_assistant_echo(self):
        session_id = "test_not_echo"
        conversation_histories[session_id] = [
            {"role": "assistant", "content": "你好，我是DeepSeek，有什么可以帮你的吗？"},
        ]
        try:
            is_echo, reason = is_likely_assistant_echo("Mac电脑怎么关机", session_id)
            self.assertFalse(is_echo)
            self.assertEqual(reason, "not_echo")
        finally:
            conversation_histories.pop(session_id, None)


if __name__ == "__main__":
    unittest.main()
