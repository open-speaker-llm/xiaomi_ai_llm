"""Exact-lease, write-once publication and cancellation across shared PCM."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NeuralStreamTest(unittest.TestCase):
    def test_no_speech_requires_six_seconds_fresh_and_fully_consumed(self):
        source = r'''
#include <assert.h>
#include "neural_decision.h"
static struct neural_stream s;
static struct neural_decision d;
int main(void){
 ns_init(&s,4,22,33);assert(ns_claim(&s,4,22,44));nd_init(&d,4,22,33);
 s.used=600*320;
 struct neural_proposal p={44,600,ND_NO_SPEECH,1000,0};nd_publish(&d,p);
 assert(nd_no_speech_due(&s,&d,4,22,44,1000));
 assert(!nd_due(&s,&d,4,22,44,1000));
 assert(!nd_no_speech_due(&s,&d,4,22,44,1151));
 assert(!nd_no_speech_due(&s,&d,5,22,44,1000));
 assert(!nd_no_speech_due(&s,&d,4,22,45,1000));
 s.used+=320;assert(!nd_no_speech_due(&s,&d,4,22,44,1000));s.used-=320;
 p.candidate=0;nd_publish(&d,p);assert(!nd_no_speech_due(&s,&d,4,22,44,1000));
 p.candidate=600;nd_publish(&d,p);assert(!nd_no_speech_due(&s,&d,4,22,44,1000));
 p.candidate=ND_NO_SPEECH;p.invalid=1;nd_publish(&d,p);assert(!nd_no_speech_due(&s,&d,4,22,44,1000));
 p.invalid=0;p.consumed=599;s.used=599*320;nd_publish(&d,p);assert(!nd_no_speech_due(&s,&d,4,22,44,1000));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(source)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'), str(path / 'test.c'),
                            '-o', str(path / 'test')], check=True, capture_output=True)
            subprocess.run([str(path / 'test')], check=True, timeout=5)

    def test_proposal_requires_current_identity_freshness_and_caught_up_audio(self):
        source = r'''
#include <assert.h>
#include "neural_decision.h"
static struct neural_stream s;
static struct neural_decision d;
int main(void){
 unsigned char pcm[640]={0};
 ns_init(&s,4,22,33);assert(ns_claim(&s,4,22,44));
 nd_init(&d,4,22,33);assert(ns_append(&s,pcm,320));
 struct neural_proposal p={44,1,1,1000,0};nd_publish(&d,p);
 assert(nd_due(&s,&d,4,22,44,1000));
 assert(nd_due(&s,&d,4,22,44,1150));
 assert(!nd_due(&s,&d,4,22,44,1151));
 assert(!nd_due(&s,&d,4,22,44,999));
 assert(!nd_due(&s,&d,5,22,44,1000));
 assert(!nd_due(&s,&d,4,23,44,1000));
 assert(!nd_due(&s,&d,4,22,45,1000));
 assert(ns_append(&s,pcm,320));assert(!nd_due(&s,&d,4,22,44,1000));
 p.consumed=2;nd_publish(&d,p);assert(nd_due(&s,&d,4,22,44,1000));
 p.candidate=0;nd_publish(&d,p);assert(!nd_due(&s,&d,4,22,44,1000));
 p.candidate=3;nd_publish(&d,p);assert(!nd_due(&s,&d,4,22,44,1000));
 p.candidate=2;p.invalid=1;nd_publish(&d,p);assert(!nd_due(&s,&d,4,22,44,1000));
 p.invalid=0;nd_publish(&d,p);d.generation|=1;assert(!nd_due(&s,&d,4,22,44,1000));
 d.generation++;d.observer=34;assert(!nd_due(&s,&d,4,22,44,1000));
 d.observer=33;assert(nd_due(&s,&d,4,22,44,1000));
 ns_close(&s,0);assert(!nd_due(&s,&d,4,22,44,1000));
 ns_init(&s,5,22,33);assert(ns_claim(&s,5,22,44));assert(ns_append(&s,pcm,640));
 assert(!nd_due(&s,&d,5,22,44,1000));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(source)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'), str(path / 'test.c'),
                            '-o', str(path / 'test')], check=True, capture_output=True)
            subprocess.run([str(path / 'test')], check=True, timeout=5)

    def test_identity_bound_and_terminal_publication(self):
        source = r'''
#include <assert.h>
#include "neural_stream.h"
static struct neural_stream s;
int main(void) {
    unsigned char block[1920];memset(block,7,sizeof(block));
    ns_init(&s,1,22,33);
    assert(ns_identity(&s,1,22));
    assert(!ns_claim(&s,2,22,44) && !ns_claim(&s,1,23,44));
    assert(!ns_claim(&s,1,22,1));
    assert(ns_claim(&s,1,22,44) && !ns_claim(&s,1,22,55));
    assert(ns_append(&s,block,sizeof(block)) && s.used==1920);
    memset(block,9,sizeof(block));assert(s.pcm[0]==7 && s.pcm[1919]==7);
    for(unsigned i=0;i<400;i++)assert(ns_append(&s,block,sizeof(block)));
    assert(s.used==NS_BYTES && s.pcm[NS_BYTES-1]==9);
    ns_close(&s,1);assert(!ns_append(&s,block,sizeof(block)) && s.state==NS_DONE);
    assert(!ns_claim(&s,1,22,44));
    ns_init(&s,2,22,33);assert(!s.used && !s.pcm[0]);assert(ns_claim(&s,2,22,44));
    assert(!ns_append(&s,block,319) && s.state==NS_INVALID && !s.used);
    assert(!ns_append(&s,block,sizeof(block)));
    ns_init(&s,3,22,33);assert(ns_claim(&s,3,22,44));
    assert(ns_append(&s,block,sizeof(block)));ns_close(&s,0);
    assert(!ns_append(&s,block,sizeof(block)) && s.used==1920);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(source)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'), str(path / 'test.c'),
                            '-o', str(path / 'test')], check=True, capture_output=True)
            subprocess.run([str(path / 'test')], check=True, timeout=5)
