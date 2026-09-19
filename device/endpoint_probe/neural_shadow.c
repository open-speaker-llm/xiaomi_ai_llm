/* Bounded helper for an exact ASR-only lease. No microphone, Xiaomi SDK,
 * network or controller calls. Optional proposals require native validation;
 * only the native controller can invoke an end callback. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#include "c-api-1.10.36.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include "neural_idle_lease.h"
static volatile sig_atomic_t running=1;
static void stop(int sig){(void)sig;running=0;}
static double mono(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static uint32_t number(const char *s){char *end;unsigned long n=strtoul(s,&end,10);return *s && !*end && n>0 && n<=UINT32_MAX?(uint32_t)n:0;}
#define LOAD(name) \
    __typeof__(&SherpaOnnx##name) name=dlsym(lib,"SherpaOnnx" #name); \
    if(!name){fprintf(stderr,"%s\n",dlerror());return 1;}
int main(int argc,char **argv){
    if(argc!=6 && argc!=7)return 2;
    int endpoint=argc==7,warm=endpoint && !strcmp(argv[6],"first-ready");
    int first=endpoint && (!strcmp(argv[6],"first-endpoint") || warm);
    if(endpoint && !first && strcmp(argv[6],"endpoint"))return 2;
    uint32_t seq=number(argv[4]),owner=number(argv[5]);
    if(!seq || owner<=1 || kill((pid_t)owner,0))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);setvbuf(stdout,NULL,_IOLBF,0);
    double init=mono();
    void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);
    if(!lib){fprintf(stderr,"%s\n",dlerror());return 1;}
    LOAD(CreateVoiceActivityDetector);LOAD(DestroyVoiceActivityDetector);
    LOAD(VoiceActivityDetectorAcceptWaveform);LOAD(VoiceActivityDetectorDetected);
    LOAD(VoiceActivityDetectorEmpty);LOAD(VoiceActivityDetectorFront);
    LOAD(VoiceActivityDetectorPop);LOAD(DestroySpeechSegment);
    SherpaOnnxVadModelConfig config={0};
    config.silero_vad.model=argv[2];config.silero_vad.threshold=0.25f;
    config.silero_vad.min_silence_duration=2.0f;config.silero_vad.min_speech_duration=0.12f;
    config.silero_vad.max_speech_duration=30.0f;config.silero_vad.window_size=512;
    config.sample_rate=16000;config.num_threads=1;config.provider="cpu";
    SherpaOnnxVoiceActivityDetector *vad=CreateVoiceActivityDetector(&config,25.0f);
    if(!vad || !running)return 1;
    int fd=open(argv[3],O_CREAT|O_EXCL|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
    if(fd<0)return 1;
    if(ftruncate(fd,sizeof(struct neural_stream))){close(fd);unlink(argv[3]);return 1;}
    struct neural_stream *s=mmap(NULL,sizeof(*s),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    close(fd);if(s==MAP_FAILED){unlink(argv[3]);return 1;}
    ns_init(s,seq,owner,(uint32_t)getpid());
    if(mprotect(s,sizeof(*s),PROT_READ)){munmap(s,sizeof(*s));unlink(argv[3]);return 1;}
    struct neural_decision *decision=NULL;
    if(endpoint){
        char path[256];int length=snprintf(path,sizeof(path),"%s.decision",argv[3]);
        if(length<0 || length>=(int)sizeof(path))return 1;
        fd=open(path,O_CREAT|O_EXCL|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
        if(fd<0)return 1;
        if(ftruncate(fd,sizeof(*decision))){close(fd);unlink(path);return 1;}
        decision=mmap(NULL,sizeof(*decision),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
        close(fd);if(decision==MAP_FAILED)return 1;
        nd_init(decision,seq,owner,(uint32_t)getpid());
    }
    printf("NEURAL_READY sequence=%u owner=%u observer=%u init_ms=%.3f action=%s\n",seq,owner,(unsigned)getpid(),(mono()-init)*1000,endpoint?"propose-end":"observe-only");
    unsigned used=0,segments=0,max_queued=0,producer=0;int previous=0,failure=1;
    double start=mono(),last=start,max_step=0,claimed=0;clock_t cpu=clock();
    double idle_checked=0,idle_valid=start;
    const char *reason="deadline";
    unsigned candidate=0;
    while(running && mono()-(claimed?claimed:start)<(first && !claimed?(warm?1200.0:60.0):28.0)){
        if(!ns_identity(s,seq,owner) || kill((pid_t)owner,0)){reason="owner-or-identity";break;}
        unsigned state=__atomic_load_n(&s->state,__ATOMIC_ACQUIRE);
        if(state==NS_INVALID || state>NS_INVALID){reason="revoked";break;}
        if(warm && state==NS_WAIT && mono()-idle_checked>=0.25){
            idle_checked=mono();int valid=ni_read(argv[3],seq,owner,(uint32_t)getpid());
            if(valid>0)idle_valid=idle_checked;
            else if(!valid || idle_checked-idle_valid>2.0){reason="idle-lease";break;}
        }
        if(state!=NS_WAIT){
            if(s->producer<=1 || kill((pid_t)s->producer,0)){reason="producer-dead";break;}
            if(!producer){producer=s->producer;if(first){claimed=mono();last=claimed;}}
            if(producer!=s->producer){reason="producer-replaced";break;}
        }
        unsigned next=__atomic_load_n(&s->used,__ATOMIC_ACQUIRE);
        if(next<used || next>NS_BYTES || next%320){reason="invalid-count";break;}
        if(next==used){
            if(state==NS_DONE){failure=!used;reason=used?"complete":"empty";break;}
            if(mono()-last>(producer?2.0:(first?(warm?1200.0:60.0):8.0))){reason="input-stalled";break;}
            struct timespec delay={0,warm && state==NS_WAIT?20000000:2000000};nanosleep(&delay,NULL);continue;
        }
        unsigned queued=(next-used)/320;if(queued>max_queued){max_queued=queued;printf("NEURAL_BACKLOG audio_ms=%u frames=%u mono=%.6f\n",used/32,queued,mono());}
        if(queued>25){reason="backlog-over-250ms";break;}
        if(!used)printf("NEURAL_STREAM sequence=%u producer=%u mono=%.6f\n",seq,producer,mono());
        float frame[160];
        for(unsigned j=0;j<160;j++){int16_t x;memcpy(&x,s->pcm+used+j*2,2);frame[j]=x/32768.0f;}
        double tick=mono();VoiceActivityDetectorAcceptWaveform(vad,frame,160);
        double step=mono()-tick;if(step>max_step)max_step=step;
        if(__atomic_load_n(&s->state,__ATOMIC_ACQUIRE)==NS_INVALID){reason="revoked-during-inference";break;}
        used+=320;last=mono();
        int detected=VoiceActivityDetectorDetected(vad);
        if(detected)candidate=0;
        if(detected!=previous){printf("NEURAL_EDGE audio_ms=%u detected=%d mono=%.6f\n",used/32,detected,last);previous=detected;}
        while(!VoiceActivityDetectorEmpty(vad)){
            const SherpaOnnxSpeechSegment *segment=VoiceActivityDetectorFront(vad);
            if(!segment){reason="missing-segment";goto done;}
            printf("NEURAL_CANDIDATE sequence=%u audio_ms=%u start_ms=%.3f end_ms=%.3f mono=%.6f provisional=1\n",seq,used/32,segment->start/16.0,(segment->start+segment->n)/16.0,last);
            candidate=used/320;
            DestroySpeechSegment(segment);VoiceActivityDetectorPop(vad);segments++;
        }
        if(decision)nd_publish(decision,(struct neural_proposal){producer,used/320,candidate,(uint32_t)(mono()*1000),0});
    }
done:
    if(!running)reason="signal";
    if(decision && failure)nd_publish(decision,(struct neural_proposal){producer,used/320,0,(uint32_t)(mono()*1000),1});
    struct rusage usage={0};getrusage(RUSAGE_SELF,&usage);
    printf("NEURAL_DONE sequence=%u status=%s reason=%s audio_ms=%u segments=%u max_queued_frames=%u max_step_ms=%.3f cpu_ms=%.3f maxrss_kib=%ld\n",seq,failure?"invalid":"ok",reason,used/32,segments,max_queued,max_step*1000,(clock()-cpu)*1000.0/CLOCKS_PER_SEC,usage.ru_maxrss);
    DestroyVoiceActivityDetector(vad);munmap(s,sizeof(*s));if(decision)munmap(decision,sizeof(*decision));dlclose(lib);
    return failure;
}
