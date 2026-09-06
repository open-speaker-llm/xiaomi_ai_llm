import fcntl
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
FORMAT = struct.Struct('<12I80s4096s')


@unittest.skipUnless(shutil.which('cc'), 'C compiler needed')
class NativeAsrControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name) / 'state-dir'
        cls.binary = Path(cls.temp.name) / 'ctl'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DCONTROL_DIR="' + str(cls.directory) + '"',
                        str(ROOT / 'device/native_asr/native_asr_ctl.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        shutil.rmtree(self.directory, ignore_errors=True)
        subprocess.run([str(self.binary), 'init'], check=True)
        self.state = self.directory / 'state'
        self.update({2: os.getpid(), 3: os.getpid()})

    def update(self, changes):
        with self.state.open('r+b') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            values = list(FORMAT.unpack(f.read()))
            for key, value in changes.items():
                values[key] = value
            f.seek(0)
            f.write(FORMAT.pack(*values))

    def read(self):
        with self.state.open('rb') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            return FORMAT.unpack(f.read())

    def listen(self):
        p = subprocess.Popen([str(self.binary), 'listen', str(os.getpid()), '5'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def stop():
            if p.poll() is None:
                p.terminate()
            p.communicate(timeout=2)
        self.addCleanup(stop)
        until = time.monotonic() + 2
        while self.read()[7] != 1:
            if p.poll() is not None or time.monotonic() > until:
                p.kill()
                self.fail('request was not created')
            time.sleep(.01)
        return p

    def test_text_is_returned_literally_and_only_after_owned_final(self):
        self.update({13: b'previous-turn'})
        p = self.listen()
        self.assertEqual(self.read()[13].rstrip(b'\0'), b'')
        text = '那什么时候去？ $(touch /do-not-execute) "引号"\n第二行'.encode()
        self.update({7: 6, 10: 1, 11: 1, 12: b'new-dialog', 13: text})
        stdout, _ = p.communicate(timeout=2)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(stdout, text)
        self.assertEqual(self.read()[7], 0)

    def test_empty_final_is_silent_timeout(self):
        p = self.listen()
        self.update({7: 6, 10: 1, 11: 1})
        stdout, _ = p.communicate(timeout=2)
        self.assertEqual(p.returncode, 124)
        self.assertEqual(stdout, b'')

    def test_concurrent_request_is_rejected_and_cancel_releases_lease(self):
        p = self.listen()
        rejected = subprocess.run([str(self.binary), 'listen', str(os.getpid()), '5'], capture_output=True)
        self.assertEqual(rejected.returncode, 1)
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=2)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.read()[7], 7)
        next_request = self.listen()
        next_request.terminate()
        next_request.communicate(timeout=2)

    def test_superseded_reader_does_not_clear_new_request(self):
        p = self.listen()
        self.update({4: self.read()[4] + 1, 7: 4, 12: b'next-dialog'})
        p.communicate(timeout=2)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.read()[7], 4)

    def test_invalid_arguments_missing_daemon_and_corrupt_state_fail(self):
        for value in ['5junk', '-1', '0', '31', '4294967296']:
            r = subprocess.run([str(self.binary), 'listen', str(os.getpid()), value], capture_output=True)
            self.assertEqual(r.returncode, 2)
        self.update({3: 0})
        r = subprocess.run([str(self.binary), 'listen', str(os.getpid()), '5'], capture_output=True)
        self.assertEqual(r.returncode, 1)
        self.state.write_bytes(b'corrupt')
        r = subprocess.run([str(self.binary), 'status'], capture_output=True)
        self.assertEqual(r.returncode, 1)
