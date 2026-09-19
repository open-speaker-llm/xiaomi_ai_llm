/* Replay old PCM through the exact live shadow detector, on the speaker.
 * No recording or ASR. A finite zero tail exposes final silence candidates.
 */
#include <stdio.h>
#include "shadow_vad.h"
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    if(fseek(f,0,SEEK_END))return 2;
    long bytes=ftell(f);if(bytes<320 || bytes>960000 || bytes%320)return 2;
    rewind(f);
    struct shadow_vad s;if(shadow_init(&s))return 1;
    int16_t pcm[160];int failure=0;
    for(long i=0;i<bytes/320;i++)
        if(fread(pcm,sizeof(pcm),1,f)!=1 || shadow_feed(&s,pcm,(i+1)*.01)) {failure=1;break;}
    fclose(f);
    fprintf(stderr,"SHADOW_SYNTHETIC_TAIL start_ms=%u duration_ms=2500\n",s.endpoint.frames*10);
    for(unsigned i=0;i<160;i++)pcm[i]=0;
    for(unsigned i=0;!failure && i<250;i++)failure=shadow_feed(&s,pcm,(s.endpoint.frames+1)*.01);
    shadow_finish(&s,failure);return failure;
}
