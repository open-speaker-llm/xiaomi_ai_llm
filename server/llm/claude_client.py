"""
Claude API 对接模块
支持流式响应，适合语音对话场景
"""

import os
from typing import AsyncIterator, Optional
import anthropic
from anthropic import AsyncAnthropic


class ClaudeClient:
    """Claude API 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        self.client = AsyncAnthropic(api_key=self.api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

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
            conversation_history: 对话历史 [{"role": "user", "content": "..."}]

        Returns:
            Claude 的回复文本
        """
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = system_prompt or self._default_system_prompt()

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=messages,
        )

        return response.content[0].text

    async def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        """
        流式对话请求，边生成边返回

        Args:
            message: 用户消息
            system_prompt: 系统提示词
            conversation_history: 对话历史

        Yields:
            逐步返回的文本片段
        """
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = system_prompt or self._default_system_prompt()

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def _default_system_prompt(self) -> str:
        """默认系统提示词 - 语音助手"""
        return """你是一个友好的中文语音助手，叫小爱。你的回答应该：
1. 简洁明了，适合语音播报
2. 使用口语化表达
3. 控制在2-3句话左右，除非用户要求详细说明
4. 友好、亲切的语气
5. 如果不知道答案，诚实地说不知道

请用中文回答。"""


class OpenAIClient:
    """OpenAI GPT API 客户端 (备选)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ):
        from openai import AsyncOpenAI

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> str:
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = system_prompt or "你是一个友好的中文语音助手。"

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "system", "content": system}] + messages,
        )

        return response.choices[0].message.content

    async def chat_stream(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> AsyncIterator[str]:
        messages = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": message})

        system = system_prompt or "你是一个友好的中文语音助手。"

        stream = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "system", "content": system}] + messages,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
