"""Rollback sequencing and real log archival; no speaker/service manipulation."""
from pathlib import Path
import subprocess,tempfile,unittest,shlex
ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/'device/endpoint_probe/native_route_restore.sh'
class NativeRouteRestoreTest(unittest.TestCase):
    def test_service_readiness_waits_and_times_out(self):
        for wanted in ['stopped', 'healthy']:
            for ready_after in [3, 99]:
                with self.subTest(wanted=wanted, ready_after=ready_after):
                    code='. '+shlex.quote(str(LIB))+'''\ncount=0
sleep() { count=$((count+1)); }
route_native_pids() { [ "$count" -ge '''+str(ready_after)+''' ] || echo 123; }
route_native_status() { [ "$count" -ge '''+str(ready_after)+''' ]; }
route_wait_native '''+wanted+'''\nresult=$?
echo "$result $count"
'''
                    r=subprocess.run(['sh'],input=code,capture_output=True,text=True,timeout=5)
                    self.assertEqual(r.stdout.strip(), '0 3' if ready_after == 3 else '1 50')
    def run_restore(self,failure='',symlink=False,existing=True):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'armed').write_text('experiment');(p/'original').write_text('original')
            if existing:(p/'instruction.log').write_text('old cancelled final\n')
            if symlink:
                (p/'instruction.log').unlink(missing_ok=True);(p/'instruction.log').symlink_to(p/'original')
            code='''set -eu
. '''+shlex.quote(str(LIB))+'''
D='''+shlex.quote(temp)+'''
original=$D/original; trial=$D/trial; ORIGINAL_ROUTE_SHA256=known; ROUTE_INSTRUCTION_LOG=$D/instruction.log
FAILURE='''+shlex.quote(failure)+'''
hash() { echo known; }
step() { echo "$1" >> "$D/order"; [ "$FAILURE" != "$1" ]; }
route_stop_session() { step session; }
stop_route_client() { step client; }
route_stop_native() { step native; }
route_restore_overlays_stopped() { step overlay; }
route_native_pids() { if [ "$FAILURE" = writers ]; then echo 123; fi; }
route_start_native() { step start || return 1; printf 'new native result\\n' > "$ROUTE_INSTRUCTION_LOG"; }
launch_client() { step launch || return 1; cp "$ROUTE_INSTRUCTION_LOG" "$D/read-by-original"; }
if route_restore_legacy; then echo ok; else echo refused; fi
'''
            r=subprocess.run(['sh'],input=code,capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,0,r.stderr)
            archives=[x.read_text() for x in p.glob('rollback.*/instruction.log')]
            read=(p/'read-by-original').read_text() if (p/'read-by-original').exists() else None
            return r.stdout, (p/'order').read_text().splitlines(), (p/'armed').exists(), archives,read
    def test_old_reader_starts_only_after_new_native_epoch(self):
        out,order,armed,archives,read=self.run_restore()
        self.assertEqual(order,['session','client','native','overlay','start','launch'])
        self.assertFalse(armed);self.assertEqual(archives,['old cancelled final\n'])
        self.assertEqual(read,'new native result\n');self.assertIn('ORIGINAL_CLIENT_RESTORED',out)
    def test_each_failed_boundary_preserves_retry_marker_and_never_launches(self):
        for failure in ['session','client','native','overlay','writers','start']:
            out,order,armed,_,read=self.run_restore(failure)
            self.assertIn('refused',out);self.assertTrue(armed);self.assertNotIn('launch',order);self.assertIsNone(read)
    def test_symlink_source_is_preserved_and_refuses_start(self):
        out,order,armed,archives,read=self.run_restore(symlink=True)
        self.assertIn('refused',out);self.assertNotIn('start',order);self.assertTrue(armed);self.assertEqual(archives,[])
    def test_missing_old_log_needs_no_fabricated_evidence(self):
        out,order,armed,archives,read=self.run_restore(existing=False)
        self.assertFalse(armed);self.assertEqual(archives,[]);self.assertEqual(read,'new native result\n')
