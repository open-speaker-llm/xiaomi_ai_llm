"""
TTS 语音合成模块
支持 ElevenLabs、Azure 等服务
"""

import io
import os
from typing import Optional
import requests


class ElevenLabsTTS:
    """ElevenLabs TTS 客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = "EXAVITQu4vr4xnSDxMaL",
        model: str = "eleven_v2",
        output_format: str = "mp3_44100_128",
    ):
        """
        初始化 ElevenLabs TTS

        Args:
            api_key: ElevenLabs API key
            voice_id: 音色ID
            model: 模型名称
            output_format: 输出格式
        """
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY environment variable is required")

        self.voice_id = voice_id
        self.model = model
        self.output_format = output_format
        self.base_url = "https://api.elevenlabs.io/v1"

    async def synthesize(self, text: str) -> bytes:
        """
        将文字转换为语音

        Args:
            text: 要合成的文字

        Returns:
            MP3 格式音频数据
        """
        url = f"{self.base_url}/text-to-speech/{self.voice_id}"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            raise Exception(f"ElevenLabs API error: {response.status_code} - {response.text}")

        return response.content

    async def synthesize_streaming(
        self,
        text: str,
        chunk_size: int = 1024,
    ):
        """
        流式合成语音

        Yields:
            音频数据块
        """
        url = f"{self.base_url}/text-to-speech/{self.voice_id}/stream"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=30,
        )

        if response.status_code != 200:
            raise Exception(f"ElevenLabs API error: {response.status_code}")

        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk


class AzureTTS:
    """Azure 语音合成 (备选)"""

    def __init__(
        self,
        api_key: str,
        region: str = "eastus",
        voice: str = "zh-CN-XiaoxiaoNeural",
    ):
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            raise ImportError("azure-cognitiveservices-speech is required")

        self.api_key = api_key
        self.region = region
        self.voice = voice

        self.speech_config = speechsdk.SpeechConfig(
            subscription=api_key,
            region=region,
        )
        self.speech_config.speech_synthesis_voice_name = voice

    async def synthesize(self, text: str) -> bytes:
        """使用 Azure 进行语音合成"""
        import azure.cognitiveservices.speech as speechsdk

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=self.speech_config,
            audio_config=None,
        )

        result = synthesizer.speak_text_async(text).get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise Exception(f"Azure TTS error: {result.reason}")

        return result.audio_data


class CoquiTTS:
    """Coqui TTS 本地合成 (开源备选)"""

    def __init__(
        self,
        model_name: str = "tts_models/zh-CN/baker/tacotron2-DDC-GST",
    ):
        try:
            from TTS.api import TTS
        except ImportError:
            raise ImportError("TTS is required: pip install TTS")

        self.tts = TTS(model_name=model_name, gpu=False)

    async def synthesize(self, text: str) -> bytes:
        """使用 Coqui TTS 合成语音"""
        import numpy as np
        import soundfile as sf

        # 生成语音
        waveform = self.tts.tts(text)

        # 转换为 bytes
        buffer = io.BytesIO()
        sf.write(buffer, waveform, 24000, format="WAV")
        buffer.seek(0)

        return buffer.read()
