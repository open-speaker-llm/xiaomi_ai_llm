#!/usr/bin/env python3
"""
设备端音频采集程序
用于从麦克风采集音频并发送到服务器

支持两种模式:
1. 麦克风模式: 直接从系统麦克风采集
2. 网络推流模式: 从网络音频流采集 (小爱音箱DLNA推流)
"""

import os
import sys
import asyncio
import base64
import json
import argparse
import threading
from typing import Optional

# 音频处理
try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

import websockets
import requests


class AudioCapture:
    """音频采集器"""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 4096,
        channels: int = 1,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels

        if HAS_PYAUDIO:
            self.pyaudio = pyaudio.PyAudio()
            self.stream = None
        else:
            raise ImportError("pyaudio is required: pip install pyaudio")

    def start(self):
        """开始采集"""
        self.stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
        )
        print(f"Audio capture started: {self.sample_rate}Hz, {self.channels}ch")

    def read(self) -> bytes:
        """读取一块音频数据"""
        if self.stream:
            data = self.stream.read(self.chunk_size, exception_on_overflow=False)
            return data
        return b""

    def stop(self):
        """停止采集"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def close(self):
        """关闭"""
        self.stop()
        self.pyaudio.terminate()


class VoiceChatClient:
    """语音对话客户端"""

    def __init__(
        self,
        server_url: str = "ws://localhost:8080/ws/voice",
        sample_rate: int = 16000,
        silence_threshold: int = 500,
        silence_timeout: float = 2.0,
    ):
        self.server_url = server_url
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_timeout = silence_timeout

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.capture: Optional[AudioCapture] = None
        self.is_recording = False
        self.is_speaking = False

    async def connect(self):
        """连接到服务器"""
        self.websocket = await websockets.connect(self.server_url)
        print(f"Connected to {self.server_url}")

    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

    def _is_silent(self, audio_data: bytes) -> bool:
        """检测是否为静音"""
        if not HAS_NUMPY:
            return len(audio_data) < 100

        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        return np.abs(audio_np).mean() < self.silence_threshold

    async def send_audio(self, audio_data: bytes):
        """发送音频数据"""
        if self.websocket and not self.is_speaking:
            audio_b64 = base64.b64encode(audio_data).decode()
            await self.websocket.send(json.dumps({
                "type": "audio",
                "data": audio_b64,
            }))

    async def handle_server_messages(self):
        """处理服务器消息"""
        try:
            async for message in self.websocket:
                data = json.loads(message)

                if data["type"] == "text":
                    print(f"LLM: {data['content']}")

                elif data["type"] == "audio":
                    # 播放音频
                    self.is_speaking = True
                    audio_b64 = data["data"]
                    audio_data = base64.b64decode(audio_b64)
                    self._play_audio(audio_data)
                    self.is_speaking = False

                elif data["type"] == "done":
                    print("---")

                elif data["type"] == "error":
                    print(f"Error: {data['content']}")

        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")

    def _play_audio(self, audio_data: bytes):
        """播放音频"""
        try:
            import io
            import wave

            # 写入临时文件
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_data)

            buffer.seek(0)

            # 使用 pyaudio 播放
            wf = wave.open(buffer, 'rb')
            stream = self.capture.pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                output=True,
            )

            chunk_size = 1024
            while True:
                data = wf.readframes(chunk_size)
                if not data:
                    break
                stream.write(data)

            stream.close()
            wf.close()

        except Exception as e:
            print(f"Playback error: {e}")

    async def run(self):
        """运行客户端"""
        await self.connect()

        # 启动消息处理线程
        recv_task = asyncio.create_task(self.handle_server_messages())

        # 初始化音频采集
        self.capture = AudioCapture(sample_rate=self.sample_rate)
        self.capture.start()

        print("\n开始语音对话 (按 Ctrl+C 退出)...")
        print("说话后等待回复...\n")

        buffer = []
        silence_frames = 0
        max_silence_frames = int(self.silence_timeout * self.sample_rate / self.capture.chunk_size)

        try:
            while True:
                audio_data = self.capture.read()

                if self.is_speaking:
                    # 播放时跳过采集
                    continue

                if self._is_silent(audio_data):
                    silence_frames += 1

                    # 静音超时，发送录音
                    if len(buffer) > 0 and silence_frames > max_silence_frames:
                        full_audio = b"".join(buffer)
                        await self.send_audio(full_audio)
                        buffer = []
                        silence_frames = 0

                else:
                    silence_frames = 0
                    buffer.append(audio_data)

                    # 缓冲足够长也发送
                    if len(buffer) > 50:  # 约 12.5 秒
                        full_audio = b"".join(buffer)
                        await self.send_audio(full_audio)
                        buffer = []

                await asyncio.sleep(0.01)

        except KeyboardInterrupt:
            print("\nStopping...")

        finally:
            self.capture.close()
            await self.disconnect()
            recv_task.cancel()


class DLNACapture:
    """
    DLNA 音频采集器
    用于采集小爱音箱的DLNA推流
    """

    def __init__(
        self,
        dlna_url: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        self.dlna_url = dlna_url
        self.sample_rate = sample_rate
        self.response: Optional[requests.Response] = None

    def start(self):
        """开始采集 DLNA 流"""
        if not self.dlna_url:
            raise ValueError("DLNA URL is required")

        self.response = requests.get(
            self.dlna_url,
            stream=True,
            timeout=30,
            headers={
                "Accept": "*/*",
                "User-Agent": "Mozilla/5.0",
            }
        )

        print(f"DLNA stream started: {self.dlna_url}")

    def read(self) -> bytes:
        """读取音频数据"""
        if self.response:
            try:
                # 读取 HTTP 流的原始数据
                # 注意: DLNA 流通常是 MP3/LPCM 格式
                return self.response.raw.read(4096, decode_content=False)
            except Exception:
                return b""
        return b""

    def stop(self):
        """停止采集"""
        if self.response:
            self.response.close()
            self.response = None


async def test_http_api(server_url: str, message: str):
    """测试 HTTP API"""
    async with requests.Session() as session:
        # 测试文字对话
        resp = await session.post(
            f"{server_url}/api/v1/chat",
            json={"message": message},
        )
        if resp.status_code == 200:
            result = resp.json()
            print(f"LLM: {result['text']}")
            if result.get("audio"):
                print("(语音响应已生成)")
        else:
            print(f"Error: {resp.status_code} - {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="小米AI音箱 LLM 客户端")
    parser.add_argument(
        "--mode",
        choices=["mic", "dlna", "http"],
        default="mic",
        help="运行模式: mic(麦克风), dlna(DLNA推流), http(仅HTTP测试)",
    )
    parser.add_argument(
        "--server",
        default="ws://localhost:8080/ws/voice",
        help="服务器 WebSocket 地址",
    )
    parser.add_argument(
        "--dlna-url",
        help="DLNA 推流地址 (dlna模式)",
    )
    parser.add_argument(
        "--http-url",
        default="http://localhost:8080",
        help="服务器 HTTP 地址 (http模式)",
    )
    parser.add_argument(
        "--test-message",
        help="测试消息 (http模式)",
    )

    args = parser.parse_args()

    if args.mode == "http":
        if args.test_message:
            asyncio.run(test_http_api(args.http_url, args.test_message))
        else:
            print("Please provide --test-message")
        return

    # 麦克风模式
    client = VoiceChatClient(
        server_url=args.server,
        silence_threshold=500,
        silence_timeout=2.0,
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nExited")


if __name__ == "__main__":
    main()
