"""Noise estimation must not train on ongoing speech or silently suppress it."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NoiseFloorTest(unittest.TestCase):
    def test_freeze_fallback_capacity_and_voice_preservation(self):
        source = r'''
#include <assert.h>
#include "noise_floor.h"
int main(void) {
    struct noise_floor n={0};
    for(int i=0;i<100;i++)noise_observe(&n,1,1000); /* speech is not training */
    assert(!n.count);noise_freeze(&n);assert(!n.confident);
    assert(noise_voice(&n,1,1,4)==1); /* immediate speech, unknown noise */
    n=(struct noise_floor){0};
    for(int i=0;i<49;i++)noise_observe(&n,0,100);
    noise_freeze(&n);assert(!n.confident && noise_voice(&n,1,1,4)==1);
    n=(struct noise_floor){0};
    for(int i=0;i<100;i++)noise_observe(&n,0,100);
    noise_freeze(&n);assert(n.confident && n.reference==100);
    assert(noise_voice(&n,1,399,4)==0 && noise_voice(&n,1,400,4)==1);
    assert(noise_voice(&n,0,100000,4)==0); /* cannot promote nonspeech */
    assert(noise_voice(&n,-1,100000,4)==-1);
    for(int i=0;i<5000;i++)noise_observe(&n,0,1000000);
    noise_freeze(&n);assert(n.count==100 && n.reference==100);
    n=(struct noise_floor){0};
    for(int i=0;i<3000;i++)noise_observe(&n,0,0);
    assert(n.count==2000);noise_freeze(&n);
    assert(!n.confident && noise_voice(&n,1,1,4)==1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'check.c').write_text(source)
            subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',
                            '-I'+str(ROOT/'device/endpoint_probe'),str(p/'check.c'),
                            '-o',str(p/'check')],check=True,capture_output=True)
            subprocess.run([str(p/'check')],check=True,capture_output=True,timeout=5)
