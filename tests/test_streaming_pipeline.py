import unittest

from server.streaming_pipeline import StreamingPipeline


class FakeLLM:
    def __init__(self, tokens):
        self.tokens = tokens

    async def chat_stream(self, message, system_prompt=None, conversation_history=None):
        for token in self.tokens:
            yield token


class FakeTTS:
    async def synthesize_pcm(self, sentence, sample_rate=32000, speed=1.0, volume=1.0):
        # 44-byte WAV header + small non-silent 16-bit PCM payload.
        return b"0" * 44 + (1000).to_bytes(2, "little", signed=True) * 20


class StreamingPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def collect_text(self, tokens):
        pipeline = StreamingPipeline(FakeLLM(tokens), FakeTTS())
        texts = []
        async for item in pipeline.process("test"):
            if item["type"] == "text":
                texts.append(item["content"])
        return texts

    async def test_filters_think_block(self):
        texts = await self.collect_text([
            "<think>内部推理不要播报</think>",
            "你好。",
            "有什么可以帮你的吗？",
        ])
        self.assertEqual(texts, ["你好。", "有什么可以帮你的吗？"])

    async def test_handles_split_think_tags(self):
        texts = await self.collect_text([
            "<thi",
            "nk>隐藏",
            "</think>可以回答。",
        ])
        self.assertEqual(texts, ["可以回答。"])

    async def test_tts_only_pipeline_without_llm(self):
        # /api/v1/tts/stream 用 llm=None 复用 _split_sync + _tts_stream（音箱直连 LLM 时端点只做 TTS）
        pipeline = StreamingPipeline(None, FakeTTS())
        sentences = pipeline._split_sync("第一句。第二句！第三句？")
        self.assertEqual(sentences, ["第一句。", "第二句！", "第三句？"])
        audio = b""
        async for chunk in pipeline._tts_stream(sentences[0]):
            if chunk["type"] == "audio":
                audio += chunk["data"]
        self.assertGreater(len(audio), 0)


if __name__ == "__main__":
    unittest.main()
