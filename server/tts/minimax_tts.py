"""
MiniMax TTS 语音合成模块
"""

import os
import json
import struct
from typing import Optional
import requests


class MiniMaxTTS:
    """MiniMax TTS 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "male-qn-qingse",
        model: str = "speech-2.8-hd",
        base_url: str = "https://api.minimax.chat/v1",
    ):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not self.api_key:
            raise ValueError("MINIMAX_API_KEY environment variable is required")

        self.voice_id = voice_id
        self.model = model
        self.base_url = base_url

    def _post(self, payload: dict) -> dict:
        """发送请求并解析 JSON 响应"""
        url = f"{self.base_url}/t2a_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            raise Exception(f"MiniMax TTS API error: {response.status_code} - {response.text}")
        result = response.json()
        base_resp = result.get("base_resp", {})
        if base_resp.get("status_code", -1) != 0:
            raise Exception(f"MiniMax TTS error: {base_resp.get('status_msg', 'unknown')}")
        return result

    def _extract_audio(self, result: dict) -> bytes:
        """从 JSON 响应中提取 hex 编码的音频数据"""
        hex_audio = result["data"]["audio"]
        return bytes.fromhex(hex_audio)

    async def synthesize(self, text: str) -> bytes:
        """将文字转换为语音，返回 MP3 音频"""
        payload = {
            "model": self.model,
            "text": text,
            "voice_setting": {"voice_id": self.voice_id},
            "audio_setting": {
                "sample_rate": 24000,
                "bitrate": 128000,
                "format": "mp3",
            },
        }
        result = self._post(payload)
        return self._extract_audio(result)

    async def synthesize_pcm(
        self,
        text: str,
        sample_rate: int = 32000,
        speed: float = 0.85,
        volume: float = 1.0,
    ) -> bytes:
        """将文字转换为 WAV 格式音频 (PCM → WAV header)"""
        payload = {
            "model": self.model,
            "text": text,
            "voice_setting": {
                "voice_id": self.voice_id,
                "speed": speed,
                "volume": volume,
            },
            "audio_setting": {
                "sample_rate": sample_rate,
                "bitrate": 128000,
                "format": "pcm",
            },
        }
        result = self._post(payload)
        pcm_data = self._extract_audio(result)
        return self._pcm_to_wav(pcm_data, sample_rate)

    async def synthesize_streaming(self, text: str, chunk_size: int = 1024):
        """流式合成语音"""
        url = f"{self.base_url}/t2a_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "text": text,
            "voice_setting": {"voice_id": self.voice_id},
            "audio_setting": {
                "sample_rate": 24000,
                "bitrate": 128000,
                "format": "mp3",
            },
        }
        response = requests.post(
            url, json=payload, headers=headers, stream=True, timeout=30,
        )
        if response.status_code != 200:
            raise Exception(f"MiniMax TTS API error: {response.status_code}")
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk

    @staticmethod
    def _pcm_to_wav(
        pcm_data: bytes,
        sample_rate: int = 32000,
        bits_per_sample: int = 16,
        channels: int = 1,
    ) -> bytes:
        """将原始 PCM 数据封装为 WAV 格式"""
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        data_size = len(pcm_data)
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            36 + data_size,
            b'WAVE',
            b'fmt ',
            16, 1, channels, sample_rate,
            byte_rate, block_align, bits_per_sample,
            b'data', data_size,
        )
        return header + pcm_data

    @staticmethod
    def list_available_voices() -> list:
        """获取可用音色列表"""
        return [
            {"id": "male-qn-qingse", "name": "青涩男声", "language": "zh"},
            {"id": "male-qn-daShu", "name": "大叔男声", "language": "zh"},
            {"id": "female-qn-tianmei", "name": "甜美女声", "language": "zh"},
            {"id": "female-qn-yicheng", "name": "逸城女声", "language": "zh"},
            {"id": "female-qn-lingli", "name": "伶俐女声", "language": "zh"},
            {"id": "male-shaonian", "name": "少年男声", "language": "zh"},
            {"id": "female-shaonian", "name": "少女声音", "language": "zh"},
        ]
