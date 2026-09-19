/* Offline feature-gate audit. Does not load the SDK or access a microphone.
 * Gate time is the first ASR arrival from a separate trace; its mapping to
 * audio time is approximate. No retrospective final text enters the policy. */
#include <fvad.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "endpoint_active.h"
#include "noise_floor.h"
static int16_t samples[320000];
int main(int argc,char **argv) {
    if(argc!=3 && argc!=4)return 2;
    char *end;unsigned long gate=strtoul(argv[2],&end,10);
    if(!*argv[2] || *end || gate>20000)return 2;
    unsigned long speech_begin=0;
    if(argc==4) {
        speech_begin=strtoul(argv[3],&end,10);
        if(!*argv[3] || *end || speech_begin>gate)return 2;
    }
    FILE *file=fopen(argv[1],"rb");if(!file)return 1;
    size_t count=fread(samples,sizeof(*samples),320000,file);
    int extra=fgetc(file),bad=ferror(file);fclose(file);
    if(bad || extra!=EOF || !count || count%160)return 1;
    const unsigned cutoffs[]={250,500};
    const float ratios[]={2,4,8}; /* approximately +3/+6/+9 dB */
    for(unsigned c=0;c<2;c++)for(unsigned r=0;r<3;r++) {
        Fvad *vad=fvad_new();if(!vad)return 1;
        if(fvad_set_sample_rate(vad,16000) || fvad_set_mode(vad,1))return 1;
        float alpha=1.0f/(1.0f+2.0f*3.14159265358979323846f*cutoffs[c]/16000.0f);
        float prev_x[2]={0},prev_y[2]={0},history[2000];struct noise_floor noise={0};
        struct endpoint_active endpoint={0};unsigned started=0;
        clock_t t=clock();
        for(unsigned i=0;i<count/160;i++) {
            float power=0;
            for(unsigned j=0;j<160;j++) {
                float y=samples[i*160+j];
                for(unsigned k=0;k<2;k++) {
                    float x=y;y=alpha*(prev_y[k]+x-prev_x[k]);prev_x[k]=x;prev_y[k]=y;
                }
                power+=y*y;
            }
            power/=160;
            history[i]=power;
            int original=fvad_process(vad,samples+i*160,160);
            if(original<0)return 1;
            if(!started && (i+1)*10>=gate) {
                if(argc==4) {
                    /* Select history only when the first ASR arrival is
                     * available. Leave 500 ms before its reported onset.
                     * Missing/short prefix retains the original detector. */
                    noise=(struct noise_floor){0};
                    unsigned until=speech_begin>500?(unsigned)(speech_begin-500)/10:0;
                    if(until>i)until=i;
                    for(unsigned k=0;k<until;k++)noise_observe(&noise,0,history[k]);
                }
                noise_freeze(&noise);started=1;
                endpoint.frames=i;endpoint.last_voice=i;endpoint.seen=1;
            }
            if(argc==3)noise_observe(&noise,original,power);
            if(started)endpoint_tick(&endpoint,noise_voice(&noise,original,power,ratios[r]));
        }
        printf("cutoff=%u ratio=%.0f floor=%.3f noise_frames=%u confident=%u reason=%s end_ms=%u last_voice_ms=%u gate_ms=%lu cpu_us=%lu estimate=%s\n",
            cutoffs[c],ratios[r],noise.reference,noise.count,noise.confident,
            endpoint.reason?endpoint_reason_name(endpoint.reason):"not-observed",endpoint.frames*10,
            endpoint.last_voice*10,gate,(unsigned long)((clock()-t)*1000000.0/CLOCKS_PER_SEC),
            argc==4?"asr-prefix":"vad-negative");
        fvad_free(vad);
    }
    return 0;
}
