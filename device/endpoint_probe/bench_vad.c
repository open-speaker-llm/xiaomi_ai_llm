/* Offline device benchmark only: reads an existing 16 kHz mono s16le PCM.
 * No microphone, native service, ASR request or LLM call. Link against the
 * separately checked out libfvad source; no downloaded code is vendored here.
 */
#define _POSIX_C_SOURCE 200809L
#include <fvad.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>

static double cpu_seconds(void) {
    struct timespec t;
    if(clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t))exit(3);
    return t.tv_sec+t.tv_nsec/1e9;
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    FILE *f=fopen(argv[1],"rb");if(!f)return 2;
    if(fseek(f,0,SEEK_END))return 2;
    long bytes=ftell(f);
    if(bytes<320 || bytes>640000 || bytes%320)return 2;
    rewind(f);
    int16_t *pcm=malloc((size_t)bytes);if(!pcm)return 3;
    if(fread(pcm,1,(size_t)bytes,f)!=(size_t)bytes)return 2;
    fclose(f);
    size_t frames=(size_t)bytes/320;
    Fvad *vad=fvad_new();if(!vad)return 3;
    for(int mode=0;mode<4;mode++) {
        fvad_reset(vad);
        if(fvad_set_sample_rate(vad,16000) || fvad_set_mode(vad,mode))return 3;
        size_t silent_start=0,voiced=0;int in_silence=1;
        for(size_t i=0;i<frames;i++) {
            int v=fvad_process(vad,pcm+i*160,160);if(v<0)return 3;
            if(v) {
                voiced++;
                if(in_silence && i-silent_start>=10)
                    printf("mode=%d nonvoice_ms=%zu..%zu\n",mode,silent_start*10,i*10);
                in_silence=0;
            } else if(!in_silence) {silent_start=i;in_silence=1;}
        }
        if(in_silence && frames-silent_start>=10)
            printf("mode=%d nonvoice_ms=%zu..%zu\n",mode,silent_start*10,frames*10);
        double start=cpu_seconds();
        for(int run=0;run<100;run++) {
            fvad_reset(vad);
            if(fvad_set_sample_rate(vad,16000) || fvad_set_mode(vad,mode))return 3;
            for(size_t i=0;i<frames;i++)
                if(fvad_process(vad,pcm+i*160,160)<0)return 3;
        }
        double elapsed=cpu_seconds()-start;
        double audio_seconds=frames*.01*100;
        printf("mode=%d audio_seconds=%.2f cpu_seconds=%.6f realtime_one_core_pct=%.4f voiced_frames=%zu/%zu\n",
               mode,audio_seconds,elapsed,100*elapsed/audio_seconds,voiced,frames);
    }
    struct rusage usage;if(!getrusage(RUSAGE_SELF,&usage))printf("peak_rss_kb=%ld\n",usage.ru_maxrss);
    fvad_free(vad);free(pcm);return 0;
}
