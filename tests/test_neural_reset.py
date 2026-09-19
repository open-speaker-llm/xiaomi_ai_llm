"""All residual phases must reseed to fresh-frame state without old PCM."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NeuralResetTest(unittest.TestCase):
    def test_every_residual_phase_and_repeated_reset(self):
        source = r'''
#include "neural_reset.h"
#include <assert.h>
#include <string.h>
int main(void){
 for(unsigned old=0;old<576;old++){
   unsigned n=nz_padding(old);assert(n>=576 && n<=1087);
   unsigned char buffer[1664];memset(buffer,9,old);memset(buffer+old,0,n);
   unsigned count=old+n;
   while(count>=576){memmove(buffer,buffer+512,count-512);count-=512;}
   assert(count==64 && nz_pending(old,n)==64);
   float audio[160],scratch[1088],residual[1664];
   for(unsigned j=0;j<160;j++)audio[j]=(float)(j+1)/160;
   for(unsigned j=0;j<old;j++)residual[j]=-99.0f;
   unsigned reseed=nz_reseed(scratch,old,audio);assert(reseed==n);
   memcpy(residual+old,scratch,reseed*sizeof(float));
   unsigned held=old+reseed;
   while(held>=576){memmove(residual,residual+512,(held-512)*sizeof(float));held-=512;}
   assert(held==64 && !memcmp(residual,audio,64*sizeof(float)));
   memcpy(residual+held,audio+64,96*sizeof(float));held+=96;
   assert(held==160 && !memcmp(residual,audio,sizeof(audio)));
   for(unsigned i=0;i<count;i++)assert(buffer[i]==0);
   for(unsigned repeat=0;repeat<5;repeat++){
     n=nz_padding(count);count=nz_pending(count,n);assert(count==64);
   }
 }
 float scratch[1088],first[64]={0};assert(!nz_reseed(scratch,576,first));
 assert(!nz_padding(576));assert(!nz_padding(UINT32_MAX));
 assert(nz_pending(0,64)==64 && nz_pending(0,575)==575 && nz_pending(0,576)==64);
 unsigned pending=64,seen[576]={0};
 for(unsigned frame=0;frame<16;frame++){pending=nz_pending(pending,160);assert(!seen[pending]);seen[pending]=1;}
 assert(pending==64);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(source)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'),
                            str(p / 'test.c'), '-o', str(p / 'test')],
                           check=True, capture_output=True)
            subprocess.run([str(p / 'test')], check=True, timeout=5)

    def test_reseed_matches_fresh_state_and_defers_until_next_audio(self):
        source = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef struct {
 float last[1800];unsigned n,windows,resets;
 uint64_t state;
 int detected,queued,broken_reset;
} SherpaOnnxVoiceActivityDetector;
void SherpaOnnxVoiceActivityDetectorReset(SherpaOnnxVoiceActivityDetector *v){
 v->windows=0;v->state=0;v->resets++;
 if(!v->broken_reset)v->detected=v->queued=0;
 /* Intentionally preserve last[], as in the pinned upstream library. */
}
void SherpaOnnxVoiceActivityDetectorAcceptWaveform(SherpaOnnxVoiceActivityDetector *v,const float *p,int32_t n){
 assert(v->n+(unsigned)n<=1800);memcpy(v->last+v->n,p,n*sizeof(float));v->n+=n;
 while(v->n>=576){
   for(unsigned i=0;i<576;i++){uint32_t x;memcpy(&x,v->last+i,4);v->state=v->state*33+x;}
   v->windows++;v->detected=1;v->queued=1;
   memmove(v->last,v->last+512,(v->n-512)*sizeof(float));v->n-=512;
 }
}
int SherpaOnnxVoiceActivityDetectorDetected(SherpaOnnxVoiceActivityDetector *v){return v->detected;}
int SherpaOnnxVoiceActivityDetectorEmpty(SherpaOnnxVoiceActivityDetector *v){return !v->queued;}
#include "neural_model_reset.h"
int main(void){
 struct neural_reset_api api={SherpaOnnxVoiceActivityDetectorReset,SherpaOnnxVoiceActivityDetectorAcceptWaveform,
   SherpaOnnxVoiceActivityDetectorDetected,SherpaOnnxVoiceActivityDetectorEmpty};
 for(unsigned old=0;old<576;old++){
   SherpaOnnxVoiceActivityDetector v={.n=old,.state=99,.windows=17,.detected=1,.queued=1},fresh={0};
   for(unsigned j=0;j<old;j++)v.last[j]=-19.0f;
   struct neural_model_reset m={.pending=old};nm_begin(&m);nm_begin(&m);
   assert(v.resets==0 && v.state==99); /* Cancellation without audio does no inference. */
   for(unsigned i=0;i<24;i++){
     float frame[160];for(unsigned j=0;j<160;j++)frame[j]=(float)(1+i*160+j)/4000;
     api.accept(&fresh,frame,160);assert(nm_frame(&m,api,&v,frame));
     assert(v.n==fresh.n && m.pending==v.n && v.windows==fresh.windows && v.state==fresh.state);
     assert(v.detected==fresh.detected && v.queued==fresh.queued);
     assert(!memcmp(v.last,fresh.last,v.n*sizeof(float)));
   }
   assert(v.resets==2 && !m.reseed);
 }
 float frame[160]={0};SherpaOnnxVoiceActivityDetector v={0};
 struct neural_model_reset m={0};assert(nm_frame(&m,api,&v,frame));
 assert(v.resets==0 && v.n==160); /* A newly created instance keeps its old framing. */
 m.pending=576;nm_begin(&m);assert(!nm_frame(&m,api,&v,frame) && v.resets==0);
 m.pending=v.n;v.broken_reset=1;v.detected=1;
 assert(!nm_frame(&m,api,&v,frame) && m.reseed); /* Failed reset is never ready. */
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(source)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'),
                            str(p / 'test.c'), '-o', str(p / 'test')],
                           check=True, capture_output=True)
            subprocess.run([str(p / 'test')], check=True, timeout=5)
