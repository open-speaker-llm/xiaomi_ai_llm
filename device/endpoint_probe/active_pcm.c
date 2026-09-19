/* Offline detector evaluation; no ASR, network or native service calls. */
#include <fvad.h>
#include <stdio.h>
#include <stdlib.h>
#include "endpoint_active.h"
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 1;
    Fvad *v=fvad_new();if(!v)return 1;
    if(fvad_set_sample_rate(v,16000) || fvad_set_mode(v,1))return 1;
    struct endpoint_active e={0};int16_t frame[160];int previous=-1;
    for(;;) {
        size_t n=fread(frame,1,sizeof(frame),f);
        if(!n)break;
        if(n!=sizeof(frame))return 1;
        int voice=fvad_process(v,frame,160);
        if(voice!=previous) {
            printf("EDGE voice=%d ms=%u\n",voice,e.frames*10);previous=voice;
        }
        if(endpoint_tick(&e,voice))break;
    }
    printf("DECISION reason=%s audio_ms=%u last_voice_ms=%u\n",
        endpoint_reason_name(e.reason),e.frames*10,e.last_voice*10);
    fvad_free(v);fclose(f);return e.reason==EP_INVALID?1:0;
}
