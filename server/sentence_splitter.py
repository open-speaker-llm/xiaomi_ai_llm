"""
流式文本句子边界检测器
累积 LLM 流式 token，在句子边界处切分输出完整句子。
"""
import re
from typing import AsyncIterator


class SentenceBoundaryDetector:
    """累积流式文本 token，检测到句子边界时输出完整句子"""

    # 中文句子结束标点 + 换行
    SENTENCE_END = re.compile(r'[。！？\n]')

    def __init__(self, min_length: int = 2):
        self._buffer = []
        self._min_length = min_length

    async def split(self, token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """
        从 LLM 流式 token 迭代器中提取完整句子

        Yields:
            完整的句子文本（含标点）
        """
        async for token in token_stream:
            self._buffer.append(token)
            accumulated = "".join(self._buffer)

            # 找最后一个句子边界位置
            boundaries = [m.end() for m in self.SENTENCE_END.finditer(accumulated)]
            if boundaries and len(accumulated[:boundaries[-1]].strip()) >= self._min_length:
                complete = accumulated[:boundaries[-1]]
                self._buffer = [accumulated[boundaries[-1]:]]
                text = complete.strip()
                if text:
                    yield text

        # 流结束时输出剩余文本
        remaining = "".join(self._buffer).strip()
        if remaining:
            yield remaining
