"""
Whisper ASR 模块
支持本地部署的开源语音识别
"""

import io
import os
from typing import Any, Optional
import numpy as np
import soundfile as sf
import whisper


class WhisperASR:
    """Whisper 语音识别客户端"""

    def __init__(
        self,
        model_name: str = "base",
        language: str = "zh",
        device: Optional[str] = None,
    ):
        """
        初始化 Whisper ASR

        Args:
            model_name: 模型大小 (tiny, base, small, medium, large)
            language: 识别语言
            device: 运行设备 (cpu, cuda)
        """
        self.model_name = model_name
        self.language = language

        if device is None:
            device = "cuda" if os.path.exists("/dev/nvidia0") else "cpu"
        self.device = device

        print(f"Loading Whisper model: {model_name} on {device}")
        self.model = whisper.load_model(model_name, device=device)

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> str:
        """
        将音频数据转换为文字

        Args:
            audio_data: WAV 格式音频数据
            sample_rate: 采样率

        Returns:
            识别的文字
        """
        info = await self.transcribe_with_info(audio_data, sample_rate)
        return info["text"]

    async def transcribe_with_info(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> dict[str, Any]:
        """识别语音并返回 Whisper 置信度指标，用于追问链路过滤幻觉。"""
        audio_np, decode_info = self._decode_audio(audio_data, sample_rate)

        audio_np = self._preprocess_pdm(audio_np, decode_info["sample_rate"], decode_info["is_pdm"])
        stats = self._audio_stats(audio_np)
        audio_np, trim_info = self._trim_silence(audio_np, decode_info["sample_rate"])
        speech_stats = self._audio_stats(audio_np)
        audio_np = self._normalize_for_asr(audio_np)

        audio_np = audio_np.astype("float32")
        result = self.model.transcribe(
            audio_np,
            language=self.language,
            fp16=False,
            temperature=0.0,
            beam_size=5,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
        )

        text = result["text"].strip()
        try:
            import zhconv
            text = zhconv.convert(text, 'zh-cn')
        except ImportError:
            pass

        segments = result.get("segments") or []
        if segments:
            total_duration = 0.0
            weighted_logprob = 0.0
            max_no_speech = 0.0
            for segment in segments:
                duration = max(0.01, float(segment.get("end", 0.0)) - float(segment.get("start", 0.0)))
                total_duration += duration
                weighted_logprob += float(segment.get("avg_logprob", -10.0)) * duration
                max_no_speech = max(max_no_speech, float(segment.get("no_speech_prob", 0.0)))
            avg_logprob = weighted_logprob / max(total_duration, 0.01)
        else:
            avg_logprob = -10.0
            max_no_speech = 1.0

        return {
            "text": text,
            "avg_logprob": avg_logprob,
            "no_speech_prob": max_no_speech,
            "decode_channel": decode_info.get("channel", -1),
            "decode_channel_score": decode_info.get("channel_score", 0.0),
            "decode_channel_peak": decode_info.get("channel_peak", 0.0),
            "decode_channel_rms": decode_info.get("channel_rms", 0.0),
            "decode_channel_active_ratio": decode_info.get("channel_active_ratio", 0.0),
            "speech_duration": speech_stats["duration"],
            "speech_rms": speech_stats["rms"],
            "speech_peak": speech_stats["peak"],
            "speech_active_ratio": speech_stats["active_ratio"],
            **trim_info,
            **stats,
        }

    def _audio_stats(self, audio: np.ndarray, sample_rate: int = 16000) -> dict[str, float]:
        """返回未增益音频的基础统计，辅助判断静音/噪声误触发。"""
        if len(audio) == 0:
            return {
                "duration": 0.0,
                "rms": 0.0,
                "peak": 0.0,
                "active_ratio": 0.0,
            }

        abs_audio = np.abs(audio.astype(np.float32))
        peak = float(np.max(abs_audio))
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        threshold = max(0.01, peak * 0.08)
        active_ratio = float(np.mean(abs_audio > threshold)) if peak > 1e-5 else 0.0
        return {
            "duration": float(len(audio) / sample_rate),
            "rms": rms,
            "peak": peak,
            "active_ratio": active_ratio,
        }

    def _preprocess_pdm(self, audio: np.ndarray, sr: int, is_pdm: bool) -> np.ndarray:
        """PDM 麦克风音频预处理: 跳过开头 PDM 稳定期"""
        if not is_pdm:
            return audio

        skip_seconds = 0.2  # 跳过前 200ms 让 CIC 滤波器稳定
        skip_samples = int(skip_seconds * sr)
        if len(audio) > skip_samples:
            audio = audio[skip_samples:]
        return audio

    def _trim_silence(
        self,
        audio: np.ndarray,
        sr: int,
        frame_ms: int = 30,
        pad_ms: int = 250,
    ) -> tuple[np.ndarray, dict[str, float]]:
        """裁剪长静音，保留少量前后文，降低短追问被 Whisper 幻觉识别的概率。"""
        if len(audio) == 0:
            return audio, {"trim_start": 0.0, "trim_end": 0.0, "trim_ratio": 1.0}

        frame = max(1, int(sr * frame_ms / 1000))
        pad = int(sr * pad_ms / 1000)
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-5 or len(audio) < frame * 4:
            return audio, {"trim_start": 0.0, "trim_end": float(len(audio) / sr), "trim_ratio": 1.0}

        threshold = max(0.0008, min(0.025, peak * 0.06))
        active_indexes = []
        for start in range(0, len(audio), frame):
            chunk = audio[start:start + frame]
            if len(chunk) == 0:
                continue
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            if rms >= threshold:
                active_indexes.append(start)

        if not active_indexes:
            return audio, {"trim_start": 0.0, "trim_end": float(len(audio) / sr), "trim_ratio": 1.0}

        start = max(0, active_indexes[0] - pad)
        end = min(len(audio), active_indexes[-1] + frame + pad)
        trimmed = audio[start:end]
        ratio = len(trimmed) / max(len(audio), 1)
        return trimmed, {
            "trim_start": float(start / sr),
            "trim_end": float(end / sr),
            "trim_ratio": float(ratio),
        }

    def _normalize_for_asr(self, audio: np.ndarray) -> np.ndarray:
        """对偏小的人声做受限增益，避免低音量导致 Whisper 识别不稳。"""
        if len(audio) == 0:
            return audio

        peak = float(np.max(np.abs(audio)))
        if peak < 1e-4:
            return audio

        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        if rms < 1e-5:
            return audio

        target_rms = 0.03
        max_gain = 10.0
        gain = min(max_gain, target_rms / rms)
        if gain <= 1.0:
            return audio

        return np.clip(audio * gain, -1.0, 1.0)

    def _select_capture_channel(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """Select a usable channel from Xiaomi's 8ch Capture stream.

        Picking the largest RMS channel is fragile: clipped echo/noise channels
        can be louder than the near-field microphone. Score channels by
        non-clipped energy and active ratio, and heavily penalize clipping.
        """
        usable = audio[:, : min(audio.shape[1], 6)].astype(np.float32)
        best_channel = 0
        best_score = -1.0
        best_stats: dict[str, float] = {}

        for channel in range(usable.shape[1]):
            ch = usable[:, channel]
            abs_ch = np.abs(ch)
            peak = float(np.max(abs_ch)) if len(ch) else 0.0
            rms = float(np.sqrt(np.mean(ch.astype(np.float64) ** 2))) if len(ch) else 0.0
            threshold = max(0.0008, peak * 0.06)
            active_ratio = float(np.mean(abs_ch > threshold)) if peak > 1e-9 else 0.0

            if peak < 1e-6 or rms < 1e-6:
                score = 0.0
            else:
                score = rms * max(active_ratio, 0.001)
                if peak >= 0.98:
                    score *= 0.08

            if score > best_score:
                best_channel = channel
                best_score = score
                best_stats = {
                    "channel_peak": peak,
                    "channel_rms": rms,
                    "channel_active_ratio": active_ratio,
                }

        info: dict[str, Any] = {
            "channel": best_channel,
            "channel_score": best_score,
            **best_stats,
        }
        return usable[:, best_channel], info

    def _decode_audio(
        self,
        audio_data: bytes,
        expected_sample_rate: int = 16000,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """解码音频数据为 numpy 数组，处理 A113 PDM 8ch S32_LE 格式"""
        is_s32le = False
        try:
            # 判断 WAV 文件的位深度 (S32_LE vs S16_LE)
            is_s32le = len(audio_data) > 34 and audio_data[34] == 32

            # 尝试作为 WAV 解析
            audio_np, sr = sf.read(io.BytesIO(audio_data))

            # A113 PDM 8ch S32_LE 48kHz.
            # ALSA Capture already exposes valid 32-bit PCM. Older code shifted
            # by 8 bits, which can clip low-level speech into full-scale noise
            # and trigger Whisper prompt hallucinations.
            channel_info: dict[str, Any] = {}
            if is_s32le:
                if len(audio_np.shape) > 1:
                    audio_np, channel_info = self._select_capture_channel(audio_np)
        except Exception:
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            audio_np = audio_np.astype(np.float32) / 32768.0
            sr = expected_sample_rate
            channel_info = {}

        # 转换为单声道
        if len(audio_np.shape) > 1:
            audio_np = audio_np.mean(axis=1)

        # Whisper 的 ndarray 输入约定为 16kHz，所有路径都统一到 16kHz。
        if sr != 16000:
            import librosa
            audio_np = librosa.resample(
                audio_np,
                orig_sr=sr,
                target_sr=16000,
            )
            sr = 16000

        return audio_np, {"sample_rate": sr, "is_pdm": is_s32le, **channel_info}


class AzureASR:
    """Azure Cognitive Services 语音识别 (备选)"""

    def __init__(
        self,
        api_key: str,
        region: str = "eastus",
        language: str = "zh-CN",
    ):
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            raise ImportError("azure-cognitiveservices-speech is required")

        self.api_key = api_key
        self.region = region
        self.language = language

        self.speech_config = speechsdk.SpeechConfig(
            subscription=api_key,
            region=region,
        )
        self.speech_config.speech_recognition_language = language

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> str:
        """使用 Azure 进行语音识别"""
        import azure.cognitiveservices.speech as speechsdk

        audio_config = speechsdk.audio.AudioConfig(
            stream=speechsdk.audio.PullAudioInputStream(
                stream=lambda: audio_data,
                stream_size=len(audio_data),
            )
        )

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self.speech_config,
            audio_config=audio_config,
        )

        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text
        else:
            return ""
