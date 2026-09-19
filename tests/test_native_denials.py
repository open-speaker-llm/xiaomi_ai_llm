from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
class NativeDenialsTest(unittest.TestCase):
    def test_thousands_of_exact_denials_remain_bounded_and_reject_late_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-DNW_DIR="'+str(p/'state')+'"',
                            str(ROOT/'device/endpoint_probe/test_native_denials.c'),'-o',str(p/'test')],
                           check=True,capture_output=True)
            result=subprocess.run([str(p/'test')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('old_ids=denied live_files=0',result.stdout)
