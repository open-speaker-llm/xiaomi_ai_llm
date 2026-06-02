"""
音频处理工具模块
"""

import io
import numpy as np
from typing import Optional, Tuple
import soundfile as sf


class AudioProcessor:
    """音频处理工具类"""

    @staticmethod
    def encode_wav(
        audio_data: np.ndarray,
        sample_rate: int = 16000,
    ) -> bytes:
        """将 numpy 数组编码为 WAV 格式"""
        buffer = io.BytesIO()
        sf.write(buffer, audio_data, sample_rate, format="WAV")
        buffer.seek(0)
        return buffer.read()

    @staticmethod
    def decode_wav(
        audio_bytes: bytes,
    ) -> Tuple[np.ndarray, int]:
        """解码 WAV 数据为 numpy 数组"""
        buffer = io.BytesIO(audio_bytes)
        audio_np, sample_rate = sf.read(buffer)
        return audio_np, sample_rate

    @staticmethod
    def convert_to_mono(
        audio_data: np.ndarray,
    ) -> np.ndarray:
        """转换为单声道"""
        if len(audio_data.shape) > 1:
            return audio_data.mean(axis=1)
        return audio_data

    @staticmethod
    def resample(
        audio_data: np.ndarray,
        orig_sr: int,
        target_sr: int,
    ) -> np.ndarray:
        """重采样"""
        if orig_sr == target_sr:
            return audio_data

        try:
            import librosa
            return librosa.resample(
                audio_data,
                orig_sr=orig_sr,
                target_sr=target_sr,
            )
        except ImportError:
            # 如果没有 librosa，使用简单的线性插值
            duration = len(audio_data) / orig_sr
            new_length = int(duration * target_sr)
            indices = np.linspace(0, len(audio_data) - 1, new_length)
            return np.interp(indices, np.arange(len(audio_data)), audio_data)

    @staticmethod
    def normalize(
        audio_data: np.ndarray,
        target_level: float = -20.0,
    ) -> np.ndarray:
        """音频归一化到目标分贝"""
        if len(audio_data) == 0:
            return audio_data

        # 计算当前 RMS
        rms = np.sqrt(np.mean(audio_data ** 2))
        if rms < 1e-8:
            return audio_data

        # 计算缩放因子
        current_db = 20 * np.log10(rms)
        scale = 10 ** ((target_level - current_db) / 20)

        return audio_data * scale

    @staticmethod
    def detect_silence(
        audio_data: np.ndarray,
        threshold: float = 0.01,
        min_silence_duration: float = 0.3,
        sample_rate: int = 16000,
    ) -> bool:
        """检测音频是否包含语音"""
        # 计算能量
        energy = np.abs(audio_data)

        # 平滑处理
        window_size = int(sample_rate * 0.05)
        smoothed = np.convolve(energy, np.ones(window_size) / window_size, mode='same')

        # 超过阈值的帧数
        speech_frames = np.sum(smoothed > threshold)
        speech_duration = speech_frames / sample_rate

        return speech_duration >= min_silence_duration

    @staticmethod
    def split_by_silence(
        audio_data: np.ndarray,
        threshold: float = 0.01,
        min_segment_duration: float = 0.3,
        sample_rate: int = 16000,
    ) -> list[np.ndarray]:
        """按静音分割音频"""
        energy = np.abs(audio_data)
        window_size = int(sample_rate * 0.05)
        smoothed = np.convolve(energy, np.ones(window_size) / window_size, mode='same')

        # 标记语音帧
        is_speech = smoothed > threshold

        segments = []
        current_segment = []
        min_samples = int(min_segment_duration * sample_rate)

        for i, speech in enumerate(is_speech):
            current_segment.append(audio_data[i * window_size:(i + 1) * window_size])

            if not speech and len(current_segment) * window_size >= min_samples:
                segment = np.concatenate(current_segment[:-5])  # 去掉尾部静音
                if len(segment) > 0:
                    segments.append(segment)
                current_segment = []

        if current_segment:
            segment = np.concatenate(current_segment)
            if len(segment) > 0:
                segments.append(segment)

        return segments
