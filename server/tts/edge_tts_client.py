"""
Edge TTS 免费语音合成（微软）
"""
import io
import struct
import subprocess
import tempfile
import numpy as np
import edge_tts


VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",   # 女声-活泼
    "yunxi": "zh-CN-YunxiNeural",         # 男声-温柔
    "xiaoyi": "zh-CN-XiaoyiNeural",       # 女声-清晰
    "yunyang": "zh-CN-YunyangNeural",     # 男声-新闻
}
DEFAULT_VOICE = "zh-CN-YunxiNeural"


class EdgeTTSClient:
    def __init__(self, voice: str = DEFAULT_VOICE):
        self.voice = voice

    async def _generate_mp3(self, text: str, speed: float = 1.0) -> bytes:
        rate_percent = int((speed - 1.0) * 100)
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate=f"{rate_percent:+d}%",
        )
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                buf.write(chunk['data'])
        return buf.getvalue()

    async def synthesize(
        self,
        text: str,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> bytes:
        """合成 WAV PCM"""
        mp3_data = await self._generate_mp3(text, speed=speed)
        if not mp3_data:
            return b""

        # MP3 → WAV PCM via ffmpeg
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as mp3f:
            mp3f.write(mp3_data)
            mp3_path = mp3f.name

        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as wavf:
            wav_path = wavf.name

        try:
            filters = [
                # EdgeTTS 的峰值不低，但平均响度偏低；动态归一化比单纯放大更接近音箱原生播报。
                'dynaudnorm=f=150:g=15:p=0.95:m=10',
                'loudnorm=I=-14:TP=-1.0:LRA=7',
            ]
            if volume != 1.0:
                filters.append(f'volume={volume}')
            filters.append('alimiter=limit=0.95')

            cmd = ['ffmpeg', '-y', '-i', mp3_path, '-filter:a', ','.join(filters)]
            cmd.extend([
                '-f', 'wav',
                '-acodec', 'pcm_s16le',
                '-ar', '32000',
                '-ac', '1',
                wav_path,
            ])
            subprocess.run(cmd, capture_output=True, timeout=10)
            with open(wav_path, 'rb') as f:
                return f.read()
        finally:
            import os
            os.unlink(mp3_path)
            os.unlink(wav_path)

    async def synthesize_pcm(
        self, text: str, sample_rate: int = 32000,
        speed: float = 1.0, volume: float = 1.0,
    ) -> bytes:
        return await self.synthesize(text, speed=speed, volume=volume)
