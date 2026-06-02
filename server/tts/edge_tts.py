"""
Edge TTS 语音合成模块 (免费)
使用 Microsoft Edge 的 TTS 服务，无需 API Key
"""
import os
import sys
import subprocess
import tempfile


class EdgeTTS:
    """Edge TTS 客户端 (免费)"""

    VOICES = {
        "zh-CN-XiaoxiaoNeural": "晓晓 (女, 温柔)",
        "zh-CN-YunxiNeural": "云希 (男, 活泼)",
        "zh-CN-YunyangNeural": "云扬 (男, 专业)",
        "zh-CN-XiaoyiNeural": "晓伊 (女, 可爱)",
    }

    def __init__(self, voice: str = "zh-CN-YunyangNeural"):
        self.voice = voice
        self._python = sys.executable

    async def synthesize_pcm(self, text: str, sample_rate: int = 32000) -> bytes:
        """使用 edge-tts 生成 PCM 并封装为 WAV"""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            subprocess.run(
                [
                    self._python, "-m", "edge_tts",
                    "--voice", self.voice,
                    "--text", text,
                    "--write-media", tmp_path,
                ],
                capture_output=True,
                timeout=30,
            )

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", tmp_path,
                    "-ar", str(sample_rate),
                    "-ac", "1",
                    "-sample_fmt", "s16",
                    "-f", "wav",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=30,
            )

            return result.stdout

        finally:
            os.unlink(tmp_path)
