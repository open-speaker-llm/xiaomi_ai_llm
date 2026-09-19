"""Daily lifecycle serialization and opt-in client wiring, without a speaker."""
from pathlib import Path
import os,re,subprocess,tempfile,time,unittest,shlex
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'device/native_first_client.sh').read_text()
def functions(*names):
    return '\n'.join(re.search(r'^'+name+r'\(\) \{.*?^\}',SOURCE,re.M|re.S).group() for name in names)
class EndpointServiceTest(unittest.TestCase):
    def test_native_event_trace_remains_bounded(self):
        source=(ROOT/'device/native_asr/native_asr.c').read_text()
        note=re.search(r'^static void note\(.*?^\}',source,re.M|re.S).group()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);code=p/'trace.c';exe=p/'trace'
            code.write_text('#include "control.h"\n#include <stdarg.h>\n#define NATIVE_EVENT_LOG_LIMIT 4096\n'+note+'\nint main(void) { for(int i=0;i<2000;i++)note("turn=%d",i); return 0; }\n')
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-DCONTROL_DIR="'+tmp+'"','-I'+str(ROOT/'device/native_asr'),str(code),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True)
            log=p/'events.log';self.assertLessEqual(log.stat().st_size,4608)
            self.assertIn('turn=1999',log.read_text())
    def test_start_and_stop_are_serialized_and_not_inherited_by_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);script=p/'runner';exe=p/'guard'
            script.write_text('test "$NATIVE_ENDPOINT_GUARDED" = 1 || exit 9\necho "$1" >> '+shlex.quote(str(p/'calls'))+'\nsleep .3\n')
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-DENDPOINT_GUARD="'+str(p/'lock')+'"','-DENDPOINT_RUNNER="'+str(script)+'"',str(ROOT/'device/native_endpoint/lifecycle.c'),'-o',str(exe)],check=True,capture_output=True)
            first=subprocess.Popen([str(exe),'start'])
            try:
                deadline=time.monotonic()+2
                while not (p/'calls').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(subprocess.run([str(exe),'stop']).returncode,3)
                self.assertEqual(first.wait(timeout=2),0)
                script.write_text('test "$NATIVE_ENDPOINT_GUARDED" = 1 || exit 9\n(sleep 1) >/dev/null 2>&1 &\n')
                self.assertEqual(subprocess.run([str(exe),'start'],timeout=2).returncode,0)
                self.assertEqual(subprocess.run([str(exe),'stop'],timeout=2).returncode,0)
            finally:
                if first.poll() is None:first.terminate();first.wait(timeout=2)
    def test_client_runs_endpoint_only_when_enabled_on_boot1(self):
        for enabled,boot in [('0','0'),('1','1'),('1','0')]:
            with self.subTest(enabled=enabled,boot=boot),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);manager=p/'manager';trace=p/'trace'
                manager.write_text('#!/bin/sh\necho "$1" >> '+shlex.quote(str(trace))+'\n');manager.chmod(0o700)
                code=functions('setup_native_endpoint','stop_native_endpoint')+'\n'+f'NATIVE_ENDPOINT_ENABLED={enabled}\nNATIVE_ENDPOINT_MANAGER='+shlex.quote(str(manager))+'\n'+f'is_system1_root() {{ return {boot}; }}\nlog() {{ :; }}\nsetup_native_endpoint\nstop_native_endpoint\n'
                subprocess.run(['sh'],input=code,text=True,check=True)
                expected=[] if enabled=='0' else (['start','stop'] if boot=='0' else ['stop'])
                self.assertEqual(trace.read_text().splitlines() if trace.exists() else [],expected)
    def test_failed_endpoint_start_is_reported_without_claiming_ready(self):
        code=functions('setup_native_endpoint')+'\nNATIVE_ENDPOINT_ENABLED=1\nNATIVE_ENDPOINT_MANAGER=/does/not/exist\nis_system1_root() { return 0; }\nlog() { echo "$*"; }\nsetup_native_endpoint\n'
        out=subprocess.run(['sh'],input=code,capture_output=True,text=True,check=True).stdout
        self.assertIn('未就绪',out);self.assertNotIn('已就绪',out)
