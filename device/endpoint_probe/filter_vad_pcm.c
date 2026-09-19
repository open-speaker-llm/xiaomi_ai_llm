/* Offline hypotheses only. No microphone, SDK, network, or output audio.
 * Test low-frequency attenuation on a VAD-only copy, never on ASR input.
 * The optional ASR-arrival gate is supplied from a recorded trace: its audio
 * clock alignment is approximate and this is NOT an integrated endpoint.
 */
#include <fvad.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "endpoint_active.h"
static int16_t samples[320000];
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    char *end;unsigned long gate=strtoul(argv[2],&end,10);
    if(*end || gate>20000)return 2;
    FILE *file=fopen(argv[1],"rb");if(!file)return 1;
    size_t count=fread(samples,sizeof(*samples),320000,file);
    int extra=fgetc(file),bad=ferror(file);fclose(file);
    if(bad || extra!=EOF || !count || count%160)return 1;
    const unsigned cutoffs[]={0,80,120,180,250};
    for(unsigned c=0;c<5;c++)for(unsigned stages=1;stages<=(c?2u:1u);stages++) {
        Fvad *vad=fvad_new();if(!vad)return 1;
        if(fvad_set_sample_rate(vad,16000) || fvad_set_mode(vad,1))return 1;
        float alpha=1.0f/(1.0f+2.0f*3.14159265358979323846f*cutoffs[c]/16000.0f);
        float prev_x[2]={0},prev_y[2]={0};
        struct endpoint_active raw={0},gated={0};unsigned gate_started=0;
        clock_t started=clock();
        for(unsigned i=0;i<count/160;i++) {
            int16_t frame[160];
            for(unsigned j=0;j<160;j++) {
                float y=samples[i*160+j];
                if(c)for(unsigned k=0;k<stages;k++) {
                    float x=y;y=alpha*(prev_y[k]+x-prev_x[k]);prev_x[k]=x;prev_y[k]=y;
                }
                if(y>32767)y=32767;if(y<-32768)y=-32768;
                frame[j]=(int16_t)y;
            }
            int voice=fvad_process(vad,frame,160);
            if(voice<0)return 1;
            endpoint_tick(&raw,voice);
            if(!gate_started && (i+1)*10>=gate) {
                gate_started=1;gated.frames=i;gated.seen=1;gated.last_voice=i;
            }
            if(gate_started)endpoint_tick(&gated,voice);
        }
        printf("cutoff=%u stages=%u raw=%s raw_ms=%u gated=%s gated_ms=%u gate_ms=%lu cpu_us=%lu\n",
            cutoffs[c],stages,raw.reason?endpoint_reason_name(raw.reason):"not-observed",raw.frames*10,
            gated.reason?endpoint_reason_name(gated.reason):"not-observed",gated.frames*10,gate,
            (unsigned long)((clock()-started)*1000000.0/CLOCKS_PER_SEC));
        fvad_free(vad);
    }
    return 0;
}
