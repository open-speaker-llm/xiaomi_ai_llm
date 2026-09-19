"""Run the actual C endpoint state machine, independently of speaker firmware."""
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EndpointActiveTest(unittest.TestCase):
    def test_readiness_requires_exact_bound_session(self):
        source = (ROOT / 'device/endpoint_probe/run_protocol.sh').read_text()
        prefix = source.split('case "${1:-}" in', 1)[0]
        states = {
            'bound': ('mipns=1 aivs=2 phase=4 sequence=32 dialog=new final=0 finished=0', True),
            'old': ('mipns=1 aivs=2 phase=4 sequence=31 dialog=old final=0 finished=0', False),
            'not_bound': ('mipns=1 aivs=2 phase=3 sequence=32 dialog= final=0 finished=0', False),
            'final': ('mipns=1 aivs=2 phase=4 sequence=32 dialog=new final=1 finished=0', False),
            'empty_dialog': ('mipns=1 aivs=2 phase=4 sequence=32 dialog= final=0 finished=0', False),
        }
        for name, (state, ready) in states.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                ctl = folder / 'ctl'
                ctl.write_text('#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(state) + '\n')
                ctl.chmod(0o700)
                script = prefix.replace('/data/native_asr_ctl', shlex.quote(str(ctl)))
                script = script.replace('"$attempt" -lt 40', '"$attempt" -lt 2')
                script += '\nout=' + shlex.quote(directory) + '\nseq=32\nlabel=B\nlistener=$$\nwait_bound\n'
                run = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=5)
                self.assertEqual(run.returncode == 0, ready, run.stderr)
                self.assertEqual('CAPTURE_READY case=B sequence=32' in run.stdout, ready)
                self.assertEqual((folder / 'ready.state').exists(), ready)
                self.assertEqual((folder / 'ready.time').exists(), ready)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_noise_pauses_and_bounded_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / 'endpoint-test')
            compiled = subprocess.run(
                ['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                 str(ROOT / 'device/endpoint_probe/test_endpoint_active.c'), '-o', exe],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            checked = subprocess.run([exe], capture_output=True, text=True, timeout=5)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_invalid_trial_cannot_arm_native_capture(self):
        script = str(ROOT / 'device/endpoint_probe/run_active.sh')
        for kind, mode in [('microphone', '4'), ('live', '5'), ('live', '6'), ('live', '3'), ('capture', '4'), ('capture', '6')]:
            with self.subTest(kind=kind, mode=mode):
                run = subprocess.run(['sh', script, 'trial', kind, mode],
                                     text=True, capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertNotIn('PROTOCOL_TRIAL', run.stdout)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_diagnostic_audio_is_opt_in_bounded_and_independent(self):
        source = r'''
#include <assert.h>
#include "capture_buffer.h"
static struct capture_buffer c;
int main(void) {
    unsigned char input[1920];memset(input,7,sizeof(input));
    capture_append(&c,input,sizeof(input));assert(!c.used);
    capture_reset(&c,1);
    capture_append(&c,input,319);assert(!c.used);
    capture_append(&c,input,sizeof(input));assert(c.used==1920);
    memset(input,3,sizeof(input));assert(c.pcm[0]==7 && c.pcm[1919]==7);
    for(unsigned i=0;i<400;i++)capture_append(&c,input,sizeof(input));
    assert(c.used==CAPTURE_BYTES && c.pcm[CAPTURE_BYTES-1]==3);
    capture_append(&c,input,sizeof(input));assert(c.used==CAPTURE_BYTES);
    capture_reset(&c,0);assert(!c.enabled && !c.used && !c.pcm[0] && !c.pcm[CAPTURE_BYTES-1]);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'capture.c').write_text(source)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'), str(path / 'capture.c'),
                            '-o', str(path / 'test')], check=True, capture_output=True)
            subprocess.run([str(path / 'test')], check=True, capture_output=True, timeout=5)

    def test_invalid_pair_label_cannot_arm_native_capture(self):
        script = str(ROOT / 'device/endpoint_probe/run_active.sh')
        for arguments in [('trial', 'microphone', '5', 'C'),
                          ('trial', 'microphone', '5', 'A', 'extra'),
                          ('trial', 'live', '4', 'A')]:
            with self.subTest(arguments=arguments):
                run = subprocess.run(['sh', script, *arguments], text=True,
                                     capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertNotIn('PROTOCOL_TRIAL', run.stdout)
