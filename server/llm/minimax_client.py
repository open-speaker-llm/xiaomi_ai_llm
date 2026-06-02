"""
MiniMax API 对接模块
支持 MiniMax 大模型服务
"""

import os
from typing import AsyncIterator, Optional
from openai import AsyncOpenAI


class MiniMaxClient:
    """MiniMax API 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "MiniMax-Text-01",
        base_url: str = "https://api.minimax.chat/v1",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 45.0,
        max_retries: int = 1,
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY environment variable is required")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> str:
        """
        发送对话请求，返回完整响应

        Args:
            message: 用户消息
            system_prompt: 系统提示词
            conversation_history: 对话历史

        Returns:
            模型回复文本
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=messages,
        )

        return response.choices[0].message.content

    async def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        """
        流式对话请求

        Args:
            message: 用户消息
            system_prompt: 系统提示词
            conversation_history: 对话历史

        Yields:
            逐步返回的文本片段
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        from datetime import datetime
        t0 = datetime.now()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌐 LLM 请求 → {self.model} (历史{len(conversation_history or [])}轮)", flush=True)

        stream = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=messages,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def list_models(self) -> list:
        """列出可用模型"""
        models = await self.client.models.list()
        return [m.id for m in models.data]
