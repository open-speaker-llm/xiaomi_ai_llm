"""
流式语音对话流水线
LLM 流式输出 → 实时句子检测 → 逐句 TTS → 边生成边下发音频
"""
import re
from typing import AsyncIterator, Optional


class StreamingPipeline:
    """
    LLM → TTS 真流式流水线

    关键设计:
    - 不等待 LLM 全部完成，边收 token 边检测句子边界
    - 检测到一个完整句子就立刻发起 TTS 请求
    - TTS 音频 PCM 数据逐块 yield 给调用方
    - 用状态机过滤 MiniMax-M2.7 的 <think> 思考标签
    """

    THINK_START = re.compile(r'<\s*think\s*>', re.IGNORECASE)
    THINK_END = re.compile(r'<\s*/\s*think\s*>', re.IGNORECASE)

    def __init__(self, llm_client, tts_client, sample_rate: int = 32000, speed: float = 1.0, volume: float = 1.0):
        self.llm = llm_client
        self.tts = tts_client
        self.sample_rate = sample_rate
        self.speed = speed
        self.volume = volume

    async def process(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list] = None,
    ) -> AsyncIterator[dict]:
        """
        流式处理用户消息

        Yields:
            {"type": "text",    "content": "..."}
            {"type": "audio",   "data": b"..."}   # PCM (无 WAV 头)
            {"type": "done"}
        """
        llm_stream = self.llm.chat_stream(
            message=message,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
        )

        in_think = False
        clean_buf = ""  # 已确认不在 think 内的文本，等待提取句子

        try:
            async for token in llm_stream:
                chunk = clean_buf + token

                if in_think:
                    # 在 think 标签内部，找结束标签
                    m = self.THINK_END.search(chunk)
                    if m:
                        in_think = False
                        clean_buf = chunk[m.end():]  # 结束标签之后的文本
                        for item in self._extract_and_tts(clean_buf):
                            if isinstance(item, str):
                                yield {"type": "text", "content": item}
                            elif isinstance(item, tuple) and item[0] == "audio":
                                async for ac in self._tts_stream(item[1]):
                                    yield ac
                            elif isinstance(item, tuple) and item[0] == "done":
                                clean_buf = item[1]
                    else:
                        clean_buf = chunk  # 继续等待 </think>
                else:
                    # 正常文本，检查是否出现 <think>
                    m = self.THINK_START.search(chunk)
                    if m:
                        # think 开始 → 先处理前面的正常文本
                        pre_text = chunk[:m.start()]
                        for item in self._extract_and_tts(pre_text):
                            if isinstance(item, str):
                                yield {"type": "text", "content": item}
                            elif isinstance(item, tuple) and item[0] == "audio":
                                async for ac in self._tts_stream(item[1]):
                                    yield ac
                            elif isinstance(item, tuple) and item[0] == "done":
                                clean_buf = item[1]
                        in_think = True
                        clean_buf = chunk[m.end():]  # 跳过 <think> 标签
                    else:
                        # 没有 think 标签，正常提取句子
                        for item in self._extract_and_tts(chunk):
                            if isinstance(item, str):
                                yield {"type": "text", "content": item}
                            elif isinstance(item, tuple) and item[0] == "audio":
                                async for ac in self._tts_stream(item[1]):
                                    yield ac
                            elif isinstance(item, tuple) and item[0] == "done":
                                clean_buf = item[1]
        except Exception as e:
            yield {"type": "error", "content": f"LLM: {e}"}
            return

        # 流结束，处理剩余缓冲
        if not in_think and clean_buf.strip():
            sentences = self._split_sync(clean_buf)
            for s in sentences:
                yield {"type": "text", "content": s}
                async for chunk in self._tts_stream(s):
                    yield chunk

        yield {"type": "done"}

    def _extract_and_tts(self, text: str):
        """从文本中提取完整句子，对每个句子生成 TTS。
        返回值:
          str → 完整句子文本
          ("audio", async_generator) → 该句子的 TTS 音频块
          ("done", str) → 未完成的剩余文本缓冲
        """
        if not text:
            return

        # 找最后一个句子边界
        last_end = 0
        completed = []
        for i, ch in enumerate(text):
            if ch in '。！？\n':
                s = text[last_end:i + 1].strip()
                if len(s) >= 2:
                    completed.append(s)
                last_end = i + 1

        # 输出完成句子 + TTS
        for s in completed:
            yield s
            yield ("audio", s)

        # 返回未完成缓冲
        yield ("done", text[last_end:])

    async def _tts_stream(self, sentence: str) -> AsyncIterator[dict]:
        """TTS 流生成器"""
        import time as _t
        _t0 = _t.time()
        try:
            wav = await self.tts.synthesize_pcm(sentence, sample_rate=self.sample_rate, speed=self.speed, volume=self.volume)
        except Exception as e:
            yield {"type": "error", "content": f"TTS: {e}"}
            return
        _t1 = _t.time()
        pcm = self._trim_pcm_tail(wav[44:])
        before_sec = max(0.0, (len(wav) - 44) / max(self.sample_rate * 2, 1))
        after_sec = len(pcm) / max(self.sample_rate * 2, 1)
        trim_note = f", audio={before_sec:.1f}->{after_sec:.1f}s" if before_sec - after_sec > 0.15 else ""
        print(f"    🔊 TTS({_t1-_t0:.1f}s{trim_note}): {sentence[:60]}{'...' if len(sentence)>60 else ''}", flush=True)

        # 跳过 WAV 头 (44 字节)，逐块输出纯 PCM
        chunk_size = 1024
        for offset in range(0, len(pcm), chunk_size):
            yield {"type": "audio", "data": pcm[offset:offset + chunk_size]}

    def _trim_pcm_tail(self, pcm: bytes, threshold: int = 96, pad_ms: int = 120) -> bytes:
        """Trim trailing near-silence from 16-bit mono PCM while keeping a small pad."""
        if len(pcm) < 2:
            return pcm

        pad_bytes = int(self.sample_rate * pad_ms / 1000) * 2
        last_active = -1
        end = len(pcm) - (len(pcm) % 2)

        for i in range(end - 2, -1, -2):
            sample = int.from_bytes(pcm[i:i + 2], "little", signed=True)
            if abs(sample) > threshold:
                last_active = i + 2
                break

        if last_active < 0:
            return b""

        keep = min(len(pcm), last_active + pad_bytes)
        # Avoid over-trimming very short utterances where natural decay matters.
        min_keep = min(len(pcm), int(self.sample_rate * 0.5) * 2)
        keep = max(keep, min_keep)
        return pcm[:keep]

    def _split_sync(self, text: str) -> list:
        """同步分句"""
        result = []
        current = []
        for ch in text:
            current.append(ch)
            if ch in '。！？\n':
                s = "".join(current).strip()
                if len(s) >= 2:
                    result.append(s)
                current = []
        remain = "".join(current).strip()
        if remain:
            result.append(remain)
        return result
