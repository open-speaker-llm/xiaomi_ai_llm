"""Sample-time endpoint boundaries: never fire from wall time or initial silence."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler needed')
class EndpointShadowTest(unittest.TestCase):
    def test_pause_boundaries_resume_and_independent_thresholds(self):
        source = r'''
#include <assert.h>
#include "endpoint_shadow.h"
int main(void) {
    struct endpoint_shadow s={0};
    for(int i=0;i<300;i++)assert(!endpoint_observe(&s,0));
    for(int i=0;i<20;i++)assert(!endpoint_observe(&s,1));
    for(int i=0;i<119;i++)assert(!endpoint_observe(&s,0));
    assert(endpoint_observe(&s,0)==1);
    for(int i=0;i<39;i++)assert(!endpoint_observe(&s,0));
    assert(endpoint_observe(&s,0)==2);
    for(int i=0;i<39;i++)assert(!endpoint_observe(&s,0));
    assert(endpoint_observe(&s,0)==4);
    for(int i=0;i<100;i++)assert(!endpoint_observe(&s,0));
    assert(endpoint_observe(&s,1)==(7<<3));
    for(int i=0;i<80;i++)assert(!endpoint_observe(&s,0));
    assert(!endpoint_observe(&s,1));
    for(int i=0;i<119;i++)assert(!endpoint_observe(&s,0));
    assert(endpoint_observe(&s,0)==1);
    assert(endpoint_observe(&s,1)==(1<<3));
    assert(s.fired==0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            src, binary = Path(d) / 'check.c', Path(d) / 'check'
            src.write_text(source)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'),
                            str(src), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, timeout=3, capture_output=True)
