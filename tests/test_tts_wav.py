import io
import shutil
import struct
import subprocess
import unittest
import wave

from server.streaming_pipeline import StreamingPipeline
from tests.wav_fixtures import pcm_wav


PCM = (1000).to_bytes(2, "little", signed=True) * 320


class WavPcmTest(unittest.TestCase):
    def setUp(self):
        self.pipeline = StreamingPipeline(None, None, sample_rate=32000)

    def test_metadata_is_not_audio_and_matches_standard_wave_reader(self):
        for pcm in (b"", b"\0" * 640, PCM):
            with self.subTest(size=len(pcm)):
                wav = pcm_wav(pcm, metadata=True)
                with wave.open(io.BytesIO(wav), "rb") as reference:
                    self.assertEqual(reference.readframes(reference.getnframes()), pcm)
                self.assertEqual(self.pipeline._wav_pcm(wav), pcm)

    def test_pipe_wav_unknown_sizes_are_bounded_by_actual_payload(self):
        for metadata in (False, True):
            wav = pcm_wav(PCM, metadata=metadata, unknown_sizes=True)
            self.assertEqual(self.pipeline._wav_pcm(wav), PCM)

    def test_rejects_format_mismatch_and_non_pcm_codec(self):
        wrong_codec = bytearray(pcm_wav(PCM))
        struct.pack_into("<H", wrong_codec, 20, 3)
        cases = [pcm_wav(PCM, channels=2), pcm_wav(PCM, sample_rate=16000),
                 pcm_wav(PCM, sample_width=1), bytes(wrong_codec)]
        for wav in cases:
            with self.subTest(format=wav[20:36]):
                with self.assertRaises(ValueError):
                    self.pipeline._wav_pcm(wav)

    def test_rejects_truncated_container_and_data_even_if_riff_size_is_repaired(self):
        wav = pcm_wav(PCM, metadata=True)
        truncated = wav[:-2]
        repaired_riff = truncated[:4] + struct.pack("<I", len(truncated) - 8) + truncated[8:]
        unknown_odd_data = pcm_wav(PCM, unknown_sizes=True)[:-1]
        for data in (wav[:-1], truncated, repaired_riff, unknown_odd_data):
            with self.subTest(size=len(data)):
                with self.assertRaises(ValueError):
                    self.pipeline._wav_pcm(data)

    def test_accepts_extensible_pcm_with_matching_format(self):
        fmt = struct.pack("<HHIIHHHHI", 0xfffe, 1, 32000, 64000, 2, 16, 22, 16, 4)
        fmt += bytes.fromhex("0100000000001000800000aa00389b71")
        body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt
        body += b"data" + struct.pack("<I", len(PCM)) + PCM
        wav = b"RIFF" + struct.pack("<I", len(body)) + body
        self.assertEqual(self.pipeline._wav_pcm(wav), PCM)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg unavailable")
    def test_real_ffmpeg_pipe_wav_matches_standard_wave_reader(self):
        wav = subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=0.01", "-ar", "32000", "-ac", "1",
            "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10).stdout
        self.assertEqual(wav[4:8], b"\xff" * 4)
        self.assertGreater(wav.index(b"data"), 36)
        with wave.open(io.BytesIO(wav), "rb") as reference:
            expected = reference.readframes(100000)
        self.assertEqual(self.pipeline._wav_pcm(wav), expected)
        self.assertGreater(len(expected), 0)


if __name__ == "__main__":
    unittest.main()
