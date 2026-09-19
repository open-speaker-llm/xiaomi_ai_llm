"""Renewal uses real process CPU. Linux enforcement is also tested on the ARM device."""
from pathlib import Path
import subprocess,tempfile,unittest,sys
ROOT=Path(__file__).resolve().parents[1]
class NeuralCpuLeaseTest(unittest.TestCase):
    def run_case(self,mode):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-DNC_CPU_SECONDS=1',str(ROOT/'device/endpoint_probe/test_neural_cpu_lease.c'),'-o',str(p/'test')],check=True,capture_output=True)
            return subprocess.run([str(p/'test'),mode],check=True,capture_output=True,text=True,timeout=10).stdout
    def test_renewal_survives_total_cpu(self):
        self.assertIn('CPU_LEASE_RENEWED',self.run_case('renew'))
    def test_existing_hard_limit_is_never_raised(self):
        self.assertIn('CPU_HARD_LIMIT_PRESERVED',self.run_case('hard'))
    @unittest.skipUnless(sys.platform=='linux','Linux CPU-signal enforcement runs in the independent ARM fixture')
    def test_nonrenewing_worker_is_stopped_by_kernel(self):
        self.assertIn('CPU_STALLED_CHILD_KILLED',self.run_case('stall'))
