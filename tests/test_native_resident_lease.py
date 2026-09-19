from pathlib import Path
import subprocess,tempfile,unittest,shlex
ROOT=Path(__file__).resolve().parents[1]
class NativeResidentLeaseTest(unittest.TestCase):
    def check(self,deadline,seconds,now,armed=True):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            if armed:(p/'timer.armed').write_text('token')
            (p/'timer.deadline').write_text(deadline)
            code='. '+shlex.quote(str(ROOT/'device/endpoint_probe/native_resident_lease.sh'))+'\nresident_timer_covers '+ ' '.join(shlex.quote(x) for x in (tmp,seconds,now))
            return subprocess.run(['sh'],input=code,text=True,capture_output=True).returncode
    def test_both_time_margin_and_actual_timer_required(self):
        self.assertEqual(self.check('4000','3600','300'),0)
        self.assertNotEqual(self.check('3900','3600','300'),0)
        self.assertNotEqual(self.check('4000','3600','300',False),0)
    def test_malformed_budget_is_rejected(self):
        for deadline,seconds,now in [('4000','060','300'),('bad','60','30'),('4000','-1','300'),('4000','1','300'),('9999999999999999','60','300'),('4000','60','')]:
            self.assertNotEqual(self.check(deadline,seconds,now),0)
