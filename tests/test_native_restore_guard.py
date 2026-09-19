from pathlib import Path
import subprocess,tempfile,time,unittest,os
ROOT=Path(__file__).resolve().parents[1]
class NativeRestoreGuardTest(unittest.TestCase):
    def test_competing_restore_refused_and_lock_released_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);script=p/'runner.sh'
            script.write_text('test "$NATIVE_RESTORE_GUARDED" = 1 || exit 9\necho started >> "'+str(p/'calls')+'"\nsleep 1\n')
            exe=p/'guard';subprocess.run(['cc','-Wall','-Wextra','-Werror','-DNW_DIR="'+tmp+'"','-DROUTE_RUNNER="'+str(script)+'"','-DWAKE_RUNNER="'+str(script)+'"',str(ROOT/'device/endpoint_probe/native_restore_guard.c'),'-o',str(exe)],check=True,capture_output=True)
            first=subprocess.Popen([str(exe),'route'])
            try:
                until=time.monotonic()+2
                while not (p/'calls').exists() and time.monotonic()<until:time.sleep(.01)
                self.assertEqual(subprocess.run([str(exe),'native'],timeout=2).returncode,3)
                self.assertEqual(first.wait(timeout=3),0)
                self.assertEqual((p/'calls').read_text(),'started\n')
                self.assertEqual(subprocess.run([str(exe),'native'],timeout=3).returncode,0)
                # No stale owner-file needs deleting before the next restore.
                self.assertEqual((p/'calls').read_text(),'started\nstarted\n')
            finally:
                if first.poll() is None:first.terminate();first.wait(timeout=3)
