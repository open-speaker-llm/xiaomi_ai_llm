#ifndef SHADOW_VAD_H
#define SHADOW_VAD_H
#include <fvad.h>
#include <stdio.h>
#include "endpoint_shadow.h"
struct shadow_vad {Fvad *vad;struct endpoint_shadow endpoint;int previous;};
static int shadow_init(struct shadow_vad *s) {
    *s=(struct shadow_vad){.previous=-1};
    s->vad=fvad_new();
    if(!s->vad)return 1;
    if(fvad_set_sample_rate(s->vad,16000) || fvad_set_mode(s->vad,1)) {
        fvad_free(s->vad);s->vad=NULL;return 1;
    }
    fprintf(stderr,"SHADOW_START mode=1 frame_ms=10 gaps_ms=1200,1600,2000 action=observe_only\n");
    return 0;
}
static int shadow_feed(struct shadow_vad *s,const int16_t *samples,double observed) {
    int v=fvad_process(s->vad,samples,160);if(v<0)return 1;
    unsigned events=endpoint_observe(&s->endpoint,v);
    unsigned end_ms=s->endpoint.frames*10;
    if(v!=s->previous) {
        fprintf(stderr,"SHADOW_EDGE voiced=%d audio_ms=%u observed_mono=%.6f\n",v,end_ms-10,observed);
        s->previous=v;
    }
    for(unsigned i=0;i<3;i++) {
        if(events&(1u<<i))
            fprintf(stderr,"SHADOW_CANDIDATE gap_ms=%u audio_ms=%u observed_mono=%.6f\n",endpoint_gaps[i],end_ms,observed);
        if(events&(1u<<(i+3)))
            fprintf(stderr,"SHADOW_RESUME gap_ms=%u audio_ms=%u observed_mono=%.6f\n",endpoint_gaps[i],end_ms-10,observed);
    }
    return 0;
}
static void shadow_finish(struct shadow_vad *s,int failure) {
    fprintf(stderr,"SHADOW_DONE frames=%u status=%s\n",s->endpoint.frames,failure?"invalid":"ok");
    fvad_free(s->vad);
}
#endif
