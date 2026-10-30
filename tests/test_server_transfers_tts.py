"""Exercise debug transfers and TTS failures through the actual API routes."""
import asyncio
import os
from pathlib import Path
import socket
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx
import uvicorn

from server import main
from tests.wav_fixtures import pcm_wav


PCM = (1000).to_bytes(2, "little", signed=True) * 1024
WAV = pcm_wav(PCM)


class ScriptedTTS:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def synthesize_pcm(self, sentence, **kwargs):
        self.calls.append(sentence)
        result = self.results[sentence]
        if isinstance(result, Exception):
            raise result
        return result


class DebugTransferTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="xiaomi-transfer-test-")
        self.addCleanup(self.directory.cleanup)
        self.upload_patch = patch.object(main, "_upload_directory", self.directory)
        self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_upload_download_round_trip_uses_private_directory(self):
        for method in ("put", "post"):
            filename = f"{method}-voice.wav"
            if method == "put":
                response = await self.client.put(
                    f"/api/v1/upload/{filename}", content=b"test voice"
                )
            else:
                response = await self.client.post(
                    "/api/v1/upload_file", files={"file": (filename, b"test voice")}
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "status": "ok", "size": 10,
                "path": str(Path(self.directory.name) / filename),
            })
            downloaded = await self.client.get(f"/api/v1/download/{filename}")
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.content, b"test voice")

    async def test_multipart_traversal_cannot_write_outside_upload_directory(self):
        with tempfile.TemporaryDirectory(prefix="xiaomi-transfer-outside-") as outside:
            target = Path(outside) / "escaped.bin"
            response = await self.client.post(
                "/api/v1/upload_file",
                files={"file": (".." + str(target), b"should not be written")},
            )
            self.assertEqual(response.status_code, 400)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    async def test_invalid_multipart_names_are_rejected(self):
        for filename in ("..", ".hidden", "sub/file", "sub\\file", "a" * 129):
            with self.subTest(filename=filename):
                response = await self.client.post(
                    "/api/v1/upload_file", files={"file": (filename, b"data")}
                )
                self.assertEqual(response.status_code, 400)

    async def test_existing_upload_is_not_overwritten_by_either_endpoint(self):
        path = Path(self.directory.name) / "existing.bin"
        path.write_bytes(b"original")
        put = await self.client.put("/api/v1/upload/existing.bin", content=b"replacement")
        post = await self.client.post(
            "/api/v1/upload_file", files={"file": ("existing.bin", b"replacement")}
        )
        self.assertEqual((put.status_code, post.status_code), (409, 409))
        self.assertEqual(path.read_bytes(), b"original")

    async def test_symlink_is_neither_overwritten_nor_downloaded(self):
        with tempfile.TemporaryDirectory(prefix="xiaomi-transfer-target-") as outside:
            target = Path(outside) / "target.bin"
            target.write_bytes(b"private data")
            link = Path(self.directory.name) / "link.bin"
            link.symlink_to(target)
            put = await self.client.put("/api/v1/upload/link.bin", content=b"replacement")
            post = await self.client.post(
                "/api/v1/upload_file", files={"file": ("link.bin", b"replacement")}
            )
            download = await self.client.get("/api/v1/download/link.bin")
            self.assertEqual((put.status_code, post.status_code), (409, 409))
            self.assertEqual(download.status_code, 404)
            self.assertEqual(target.read_bytes(), b"private data")

    async def test_download_rejects_missing_files_directories_and_fifos(self):
        (Path(self.directory.name) / "directory").mkdir()
        os.mkfifo(Path(self.directory.name) / "pipe")
        for filename in ("missing", "directory", "pipe"):
            with self.subTest(filename=filename):
                response = await self.client.get(f"/api/v1/download/{filename}")
                self.assertEqual(response.status_code, 404)


class TtsResponseTest(unittest.IsolatedAsyncioTestCase):
    async def post_message(self, tts, message="第一句。第二句。"):
        with patch.object(main, "tts_client", tts):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=main.app), base_url="http://test"
            ) as client:
                return await client.post("/api/v1/tts/stream", data={"message": message})

    async def test_first_sentence_failure_returns_502_without_wav_header(self):
        tts = ScriptedTTS({"第一句。": RuntimeError("injected TTS failure")})
        response = await self.post_message(tts)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "TTS synthesis failed"})
        self.assertEqual(tts.calls, ["第一句。", "第一句。"])

    async def test_empty_silent_and_malformed_pcm_cannot_be_success(self):
        for wav in (b"", pcm_wav(b""), pcm_wav(b"\0" * 40), pcm_wav(b"\1")):
            with self.subTest(size=len(wav)):
                response = await self.post_message(ScriptedTTS({"第一句。": wav}))
                self.assertEqual(response.status_code, 502)
                self.assertNotEqual(response.content[:4], b"RIFF")

    async def test_success_keeps_wav_and_ordered_pcm(self):
        tts = ScriptedTTS({"第一句。": WAV, "第二句。": WAV})
        response = await self.post_message(tts)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:4], b"RIFF")
        self.assertEqual(response.content[44:], PCM * 2)
        self.assertEqual(tts.calls, ["第一句。", "第二句。"])

    async def test_metadata_cannot_turn_empty_or_silent_audio_into_success(self):
        for pcm in (b"", b"\0" * 640):
            with self.subTest(size=len(pcm)):
                tts = ScriptedTTS({"第一句。": pcm_wav(pcm, metadata=True)})
                response = await self.post_message(tts)
                self.assertEqual(response.status_code, 502)

    async def test_metadata_and_pipe_headers_are_removed_from_successful_audio(self):
        for unknown_sizes in (False, True):
            with self.subTest(unknown_sizes=unknown_sizes):
                tts = ScriptedTTS({"第一句。": pcm_wav(PCM, metadata=True, unknown_sizes=unknown_sizes)})
                response = await self.post_message(tts, message="第一句。")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content[44:], PCM)

    async def test_wrong_format_and_truncated_wav_return_502(self):
        for wav in (pcm_wav(PCM, sample_rate=16000), pcm_wav(PCM, channels=2),
                    pcm_wav(PCM, sample_width=1), WAV[:-2]):
            with self.subTest(format=wav[20:36], size=len(wav)):
                response = await self.post_message(ScriptedTTS({"第一句。": wav}))
                self.assertEqual(response.status_code, 502)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg unavailable")
    async def test_real_ffmpeg_silence_with_metadata_returns_502(self):
        wav = subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "anullsrc=r=32000:cl=mono", "-t", "0.01", "-c:a", "pcm_s16le",
            "-f", "wav", "pipe:1",
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10).stdout
        self.assertGreater(wav.index(b"data"), 36)
        response = await self.post_message(ScriptedTTS({"第一句。": wav}))
        self.assertEqual(response.status_code, 502)

    async def test_response_prefetches_only_first_audio_chunk(self):
        tts = ScriptedTTS({"第一句。": WAV, "第二句。": WAV})
        with patch.object(main, "tts_client", tts):
            response = await main.stream_tts("第一句。第二句。", speed=1.0, volume=1.0)
            self.assertEqual(tts.calls, ["第一句。"])
            data = b"".join([chunk async for chunk in response.body_iterator])
        self.assertEqual(data[44:], PCM * 2)
        self.assertEqual(tts.calls, ["第一句。", "第二句。"])

    async def test_middle_failure_aborts_iterator_before_later_sentences(self):
        tts = ScriptedTTS({
            "第一句。": WAV,
            "第二句。": RuntimeError("injected middle failure"),
            "第三句。": WAV,
        })
        received = []
        with patch.object(main, "tts_client", tts):
            response = await main.stream_tts("第一句。第二句。第三句。", speed=1.0, volume=1.0)
            with self.assertRaisesRegex(RuntimeError, "TTS sentence synthesis failed"):
                async for chunk in response.body_iterator:
                    received.append(chunk)
        self.assertEqual(b"".join(received)[44:], PCM)
        self.assertEqual(tts.calls, ["第一句。", "第二句。", "第二句。"])

    async def test_middle_failure_is_a_real_http_transport_error(self):
        tts = ScriptedTTS({"第一句。": WAV, "第二句。": RuntimeError("injected middle failure")})
        server = uvicorn.Server(uvicorn.Config(
            main.app, lifespan="off", ws="none", log_level="critical", access_log=False
        ))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with patch.object(main, "tts_client", tts):
            task = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                for _ in range(200):
                    if server.started:
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(server.started)
                received = []
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                    with self.assertRaises(httpx.RemoteProtocolError):
                        async with client.stream("POST", "/api/v1/tts/stream", data={
                            "message": "第一句。第二句。"
                        }) as response:
                            self.assertEqual(response.status_code, 200)
                            async for chunk in response.aiter_bytes():
                                received.append(chunk)
                self.assertEqual(b"".join(received)[44:], PCM)
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, timeout=5)
                sock.close()


if __name__ == "__main__":
    unittest.main()
