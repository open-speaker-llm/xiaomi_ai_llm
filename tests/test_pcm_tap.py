import mmap
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
SIZE = 32 + 256 * 324

@unittest.skipUnless(shutil.which('cc'), 'C compiler needed')
class PcmTapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temp.name) / 'capture_pcm'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2',
                        str(ROOT / 'device/pcm_tap/capture_pcm.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_missing_or_invalid_ring_fails_without_audio(self):
        with tempfile.TemporaryDirectory() as d:
            out, ring = Path(d) / 'out.wav', Path(d) / 'ring'
            for data in [None, b'bad', bytes(SIZE)]:
                if data is not None:
                    ring.write_bytes(data)
                result = subprocess.run([str(self.binary), str(out), '1', str(ring)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(out.exists())

    def test_copies_only_new_complete_pcm_frames(self):
        with tempfile.TemporaryDirectory() as d:
            out, ring = Path(d) / 'out.wav', Path(d) / 'ring'
            with ring.open('w+b') as f:
                f.truncate(SIZE)
                with mmap.mmap(f.fileno(), SIZE) as m:
                    struct.pack_into('<8I', m, 0, 0x50434d31, 1, 16000, 160, 256, os.getpid(), 100, 0)
                    for i in range(100):
                        struct.pack_into('<I160h', m, 32 + i * 324, i * 2 + 2, *([-2000] * 160))
                    p = subprocess.Popen([str(self.binary), str(out), '1', str(ring)], stderr=subprocess.PIPE)
                    self.assertIn(b'PCM_CAPTURE start', p.stderr.readline())
                    for i in range(100, 200):
                        off = 32 + (i % 256) * 324
                        struct.pack_into('<I', m, off, i * 2 + 1)
                        struct.pack_into('<160h', m, off + 4, *([1000] * 160))
                        struct.pack_into('<I', m, off, i * 2 + 2)
                        struct.pack_into('<I', m, 24, i + 1)
                        time.sleep(.001)
                    p.communicate(timeout=4)
                    self.assertEqual(p.returncode, 0)
            with wave.open(str(out)) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()),
                                 (16000, 1, 2, 16000))
                self.assertEqual(w.readframes(16000), struct.pack('<16000h', *([1000] * 16000)))

    def test_invalid_duration_rejected(self):
        for seconds in ('nan', 'inf', '-1', '0', '31', '1junk'):
            result = subprocess.run([str(self.binary), '/unused.wav', seconds], capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_stalled_producer_times_out(self):
        with tempfile.TemporaryDirectory() as d:
            out, ring = Path(d) / 'out.wav', Path(d) / 'ring'
            data = bytearray(SIZE)
            struct.pack_into('<8I', data, 0, 0x50434d31, 1, 16000, 160, 256, os.getpid(), 0, 0)
            ring.write_bytes(data)
            p = subprocess.run([str(self.binary), str(out), '1', str(ring)], capture_output=True, timeout=4)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(out.exists())
