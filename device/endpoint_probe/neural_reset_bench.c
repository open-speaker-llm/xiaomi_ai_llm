/* Saved-file reset equivalence benchmark. No microphone, IPC or cloud calls. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
#include "c-api-1.10.36.h"
#include "neural_model_reset.h"
#define MAX_FRAMES 2000u
static int16_t primer[MAX_FRAMES*160],probe[MAX_FRAMES*160];
static uint64_t original[MAX_FRAMES],canonical[MAX_FRAMES],actual[MAX_FRAMES];
#define API(name) static __typeof__(&SherpaOnnx##name) name
API(CreateVoiceActivityDetector);API(DestroyVoiceActivityDetector);
API(VoiceActivityDetectorAcceptWaveform);API(VoiceActivityDetectorReset);
API(VoiceActivityDetectorDetected);API(VoiceActivityDetectorEmpty);
API(VoiceActivityDetectorFront);API(VoiceActivityDetectorPop);API(DestroySpeechSegment);
static double ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000.0+t.tv_nsec/1e6;}
static void check(int ok,const char *why){if(!ok){fprintf(stderr,"FAIL %s\n",why);exit(1);}}
static unsigned input(const char *path,int16_t *out){
    FILE *f=fopen(path,"rb");check(f!=NULL,"open PCM");
    size_t n=fread(out,1,MAX_FRAMES*320,f);int end=fgetc(f),bad=ferror(f);fclose(f);
    check(n && n%320==0 && end==EOF && !bad,"PCM size");return (unsigned)n/320;
}
static uint64_t hash(uint64_t h,const void *data,size_t n){
    const unsigned char *p=data;for(size_t i=0;i<n;i++){h^=p[i];h*=1099511628211ULL;}return h;
}
static void accept(SherpaOnnxVoiceActivityDetector *v,const float *samples,unsigned n,unsigned *pending){
    VoiceActivityDetectorAcceptWaveform(v,samples,(int32_t)n);*pending=nz_pending(*pending,n);
}
static void reset(SherpaOnnxVoiceActivityDetector *v,unsigned *pending){
    unsigned n=nz_padding(*pending);check(n!=0,"unknown overlap state");
    float zeros[1088]={0};
    VoiceActivityDetectorReset(v);accept(v,zeros,n,pending);VoiceActivityDetectorReset(v);
    check(*pending==64 && !VoiceActivityDetectorDetected(v) && VoiceActivityDetectorEmpty(v),"reset state");
}
static double reseed_ms;
static void run(SherpaOnnxVoiceActivityDetector *v,const int16_t *pcm,unsigned frames,unsigned *pending,uint64_t *trace,int exact){
    unsigned first_speech=0,first_segment=0,segments=0;
    for(unsigned i=0;i<frames;i++){
        float samples[160];for(unsigned j=0;j<160;j++)samples[j]=pcm[i*160+j]/32768.0f;
        if(!i && exact){
            struct neural_model_reset state={.pending=*pending};nm_begin(&state);
            struct neural_reset_api api={VoiceActivityDetectorReset,VoiceActivityDetectorAcceptWaveform,
                                        VoiceActivityDetectorDetected,VoiceActivityDetectorEmpty};
            double tick=ms();check(nm_frame(&state,api,v,samples),"reseed frame");
            reseed_ms=ms()-tick;*pending=state.pending;
        }else accept(v,samples,160,pending);
        if(!trace)continue; /* Deliberately leave completed segments queued. */
        int detected=VoiceActivityDetectorDetected(v);uint64_t h=hash(14695981039346656037ULL,&detected,sizeof(detected));
        if(detected && !first_speech)first_speech=i+1;
        while(!VoiceActivityDetectorEmpty(v)){
            if(!first_segment)first_segment=i+1;
            segments++;
            const SherpaOnnxSpeechSegment *s=VoiceActivityDetectorFront(v);check(s!=NULL,"segment");
            h=hash(h,&s->start,sizeof(s->start));h=hash(h,&s->n,sizeof(s->n));
            check(s->n>=0 && s->n<=320000,"segment bounds");h=hash(h,s->samples,(size_t)s->n*sizeof(float));
            DestroySpeechSegment(s);VoiceActivityDetectorPop(v);
        }
        trace[i]=h;
    }
    if(trace==original || trace==canonical)
        printf("BASELINE kind=%s first_speech_ms=%u first_candidate_ms=%u segments=%u\n",
            trace==original?"original":"primed",first_speech*10,first_segment*10,segments);
}
static unsigned mismatch(const uint64_t *a,const uint64_t *b,unsigned n){
    for(unsigned i=0;i<n;i++)if(a[i]!=b[i])return i+1;return 0;
}
int main(int argc,char **argv){
    int baseline=argc==6 && !strcmp(argv[5],"baseline");
    int compact=argc==6 && !strcmp(argv[5],"compact");
    int exact=argc==6 && (!strcmp(argv[5],"exact") || !strcmp(argv[5],"exact-compact"));
    if(exact)compact=!strcmp(argv[5],"exact-compact");
    if(argc!=5 && !baseline && !compact && !exact)return 2;
    setvbuf(stdout,NULL,_IOLBF,0);
    unsigned primer_frames=input(argv[3],primer),frames=input(argv[4],probe);
    check(primer_frames>=116,"primer at least 1.16 seconds");
    void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);check(lib!=NULL,"dlopen");
#define LOAD(name) *(void **)(&name)=dlsym(lib,"SherpaOnnx" #name);check(name!=NULL,#name)
    LOAD(CreateVoiceActivityDetector);LOAD(DestroyVoiceActivityDetector);
    LOAD(VoiceActivityDetectorAcceptWaveform);LOAD(VoiceActivityDetectorReset);
    LOAD(VoiceActivityDetectorDetected);LOAD(VoiceActivityDetectorEmpty);
    LOAD(VoiceActivityDetectorFront);LOAD(VoiceActivityDetectorPop);LOAD(DestroySpeechSegment);
    SherpaOnnxVadModelConfig config={0};config.silero_vad.model=argv[2];config.silero_vad.threshold=0.25f;
    config.silero_vad.min_silence_duration=2.0f;config.silero_vad.min_speech_duration=0.12f;
    config.silero_vad.max_speech_duration=30.0f;config.silero_vad.window_size=512;
    config.sample_rate=16000;config.num_threads=1;config.provider="cpu";
    double total=ms(),init=ms();
    SherpaOnnxVoiceActivityDetector *v=CreateVoiceActivityDetector(&config,25.0f);check(v!=NULL,"fresh model");
    printf("FRESH_INIT ms=%.3f\n",ms()-init);
    unsigned pending=0;run(v,probe,frames,&pending,original,0);DestroyVoiceActivityDetector(v);
    if(exact){
        v=CreateVoiceActivityDetector(&config,25.0f);check(v!=NULL,"exact reused model");pending=0;
        unsigned offsets=compact?4:16;double sum=0,worst=0;
        for(unsigned trial=0;trial<offsets+3;trial++){
            unsigned dirty=trial>=1 && trial<=offsets?100+(trial-1)*(compact?5:1):trial==offsets+1?primer_frames:0;
            if(dirty)run(v,primer,dirty,&pending,NULL,1);
            unsigned before=pending;int detected=VoiceActivityDetectorDetected(v),queued=!VoiceActivityDetectorEmpty(v);
            run(v,probe,frames,&pending,actual,1);
            unsigned different=mismatch(original,actual,frames);
            sum+=reseed_ms;if(reseed_ms>worst)worst=reseed_ms;
            printf("EXACT trial=%u dirty_frames=%u detected=%d queued=%d leftover=%u reset_ms=%.3f first_difference_ms=%u\n",
                trial,dirty,detected,queued,before,reseed_ms,different*10);
            check(!different,"reseed differs from unmodified fresh model");
        }
        struct rusage r;check(!getrusage(RUSAGE_SELF,&r),"rusage");
        printf("EXACT_SUMMARY cases=%u frames=%u mismatches=0 reset_mean_ms=%.3f reset_max_ms=%.3f wall_ms=%.3f maxrss_kib=%ld\n",
            offsets+3,frames,sum/(offsets+3),worst,ms()-total,r.ru_maxrss);
        DestroyVoiceActivityDetector(v);dlclose(lib);return 0;
    }
    v=CreateVoiceActivityDetector(&config,25.0f);check(v!=NULL,"canonical fresh model");
    float zeros[64]={0};pending=0;accept(v,zeros,64,&pending);
    run(v,probe,frames,&pending,canonical,0);DestroyVoiceActivityDetector(v);
    if(baseline){dlclose(lib);return 0;}
    v=CreateVoiceActivityDetector(&config,25.0f);check(v!=NULL,"reused model");pending=0;
    unsigned naive_bad=0,completed=0;double worst=0,sum=0;
    unsigned offsets=compact?4:16;
    for(unsigned trial=0;trial<offsets+2;trial++){
        reset(v,&pending);
        unsigned dirty_frames=trial<offsets?100+trial*(compact?5:1):trial==offsets?primer_frames:0;
        run(v,primer,dirty_frames,&pending,NULL,0);
        int was_detected=VoiceActivityDetectorDetected(v),was_queued=!VoiceActivityDetectorEmpty(v);
        unsigned before=pending;
        if(trial<offsets){
            VoiceActivityDetectorReset(v);run(v,probe,frames,&pending,actual,0);
            unsigned different=mismatch(original,actual,frames);naive_bad+=different!=0;
            printf("NAIVE trial=%u leftover=%u first_difference_ms=%u\n",trial,before,different*10);
            reset(v,&pending);run(v,primer,dirty_frames,&pending,NULL,0);
        }
        double start=ms();reset(v,&pending);double elapsed=ms()-start;
        if(elapsed>worst)worst=elapsed;sum+=elapsed;
        run(v,probe,frames,&pending,actual,0);
        unsigned different=mismatch(canonical,actual,frames);
        printf("CANONICAL trial=%u dirty_frames=%u detected=%d queued=%d leftover=%u reset_ms=%.3f first_difference_ms=%u\n",
            trial,dirty_frames,was_detected,was_queued,before,elapsed,different*10);
        check(!different,"canonical differs from fresh primed model");completed++;
    }
    struct rusage r;check(!getrusage(RUSAGE_SELF,&r),"rusage");
    printf("RESET_SUMMARY cases=%u frames=%u naive_mismatches=%u canonical_mismatches=0 reset_mean_ms=%.3f reset_max_ms=%.3f wall_ms=%.3f maxrss_kib=%ld\n",
        completed,frames,naive_bad,sum/completed,worst,ms()-total,r.ru_maxrss);
    DestroyVoiceActivityDetector(v);dlclose(lib);return 0;
}
