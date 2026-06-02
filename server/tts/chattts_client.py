"""
ChatTTS 本地流式语音合成
"""
import io
import struct
import numpy as np


class ChatTTSClient:
    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self._chat = None
        self._spk_emb = None  # 固定音色

    def _load(self):
        if self._chat is None:
            import os, warnings
            warnings.filterwarnings('ignore')
            os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
            from ChatTTS import Chat
            self._chat = Chat()
            self._chat.load(show_tqdm=False)
            self._spk_emb = self._chat.sample_random_speaker()
            print("ChatTTS: 音色已固定")

    async def synthesize(self, text: str) -> bytes:
        """合成 WAV"""
        self._load()
        # 固定音色 + stream=True + skip_refine 提速
        params = self._chat.InferCodeParams()
        params.spk_emb = self._spk_emb
        params.show_tqdm = False

        chunks = []
        for result in self._chat.infer(
            [text], use_decoder=True,
            skip_refine_text=True, stream=True,
            params_infer_code=params,
        ):
            chunk = np.atleast_1d(np.array(result).squeeze())
            chunks.append(chunk)

        if not chunks:
            return b""
        audio = np.concatenate(chunks).astype(np.float32)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        buf.write(struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + len(pcm) * 2, b'WAVE', b'fmt ',
            16, 1, 1, self.sample_rate,
            self.sample_rate * 2, 2, 16,
            b'data', len(pcm) * 2,
        ))
        buf.write(pcm.tobytes())
        return buf.getvalue()

    async def synthesize_pcm(
        self, text: str, sample_rate: int = 32000,
        speed: float = 1.0, volume: float = 1.0,
    ) -> bytes:
        """合成 WAV PCM，重采样到目标采样率"""
        from datetime import datetime
        t0 = datetime.now()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 TTS 合成: {text[:50]}...")
        wav = await self.synthesize(text)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔊 TTS 完成 ({(datetime.now()-t0).total_seconds():.1f}s)")
        if not wav or sample_rate == self.sample_rate:
            return wav

        # 需要重采样: 24kHz → 32kHz
        import librosa
        import io as _io
        import soundfile as sf
        audio, sr = sf.read(_io.BytesIO(wav))
        if sr != sample_rate:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)

        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        buf = _io.BytesIO()
        buf.write(struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + len(pcm) * 2, b'WAVE', b'fmt ',
            16, 1, 1, sample_rate,
            sample_rate * 2, 2, 16,
            b'data', len(pcm) * 2,
        ))
        buf.write(pcm.tobytes())
        return buf.getvalue()
