/* One loaded model, four replaceable independent input slots. Only reads PCM written
 * by native callbacks. No microphone, network, SDK calls or endpoint authority. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <sys/resource.h>
#include "c-api-1.10.36.h"
#include "native_pool_maps.h"
#include "neural_model_reset.h"
#include "native_parent.h"
#include "neural_cpu_lease.h"
static volatile sig_atomic_t running=1;
static void stop(int signal){(void)signal;running=0;}
#define LOAD(name) __typeof__(&SherpaOnnx##name) name=dlsym(lib,"SherpaOnnx" #name);if(!name)return 1
int main(int argc,char **argv){
    if(argc!=3)return 2;
    struct np_pool pool;int fd=np_read_locked(NP_FILE,&pool,sizeof(pool));if(fd<0)return 2;close(fd);
    if(!np_valid(&pool) || pool.ready || pool.observer!=(uint32_t)getpid() ||
       pool.owner!=(uint32_t)getppid() || !native_bind_parent((pid_t)pool.owner))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);setvbuf(stdout,NULL,_IOLBF,0);
    signal(SIGXCPU,SIG_DFL);
    if(!nc_cpu_renew())return 1;
    uint32_t cpu_tick=now_ms(),init=cpu_tick;
    void *lib=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);if(!lib)return 1;
    LOAD(CreateVoiceActivityDetector);LOAD(DestroyVoiceActivityDetector);
    LOAD(VoiceActivityDetectorAcceptWaveform);LOAD(VoiceActivityDetectorReset);
    LOAD(VoiceActivityDetectorDetected);LOAD(VoiceActivityDetectorEmpty);
    LOAD(VoiceActivityDetectorFront);LOAD(VoiceActivityDetectorPop);LOAD(DestroySpeechSegment);
    SherpaOnnxVadModelConfig config={0};config.silero_vad.model=argv[2];
    config.silero_vad.threshold=0.25f;config.silero_vad.min_silence_duration=2.0f;
    config.silero_vad.min_speech_duration=0.12f;config.silero_vad.max_speech_duration=30.0f;
    config.silero_vad.window_size=512;config.sample_rate=16000;config.num_threads=1;config.provider="cpu";
    SherpaOnnxVoiceActivityDetector *vad=CreateVoiceActivityDetector(&config,25.0f);if(!vad || !running)return 1;
    struct neural_reset_api api={VoiceActivityDetectorReset,VoiceActivityDetectorAcceptWaveform,
        VoiceActivityDetectorDetected,VoiceActivityDetectorEmpty};
    struct neural_model_reset model={0};
    struct np_view views[NP_MAX]={0};
    for(unsigned i=0;i<pool.count;i++)if(!np_view_create(&views[i],&pool.slot[i].plan))return 1;
    printf("NEURAL_POOL_READY owner=%u observer=%u generations=%u init_ms=%u\n",pool.owner,pool.observer,pool.count,now_ms()-init);
    unsigned completed=0,last_nonce[NP_MAX]={0};uint32_t synced=0;
    for(unsigned i=0;running && (int32_t)(pool.deadline-now_ms())>0;i=(i+1)%pool.count){
        while(running && (int32_t)(pool.deadline-now_ms())>0){
            struct np_pool current;int state=np_read_locked(NP_FILE,&current,sizeof(current));
            if(state<0)goto done;
            int valid=np_valid(&current) && current.owner==pool.owner && current.observer==pool.observer;
            close(state);if(!valid || !np_refresh_views(views,&current))goto done;
            pool=current;
            if(!pool.ready && pool.retired_total)goto done;
            if(!last_nonce[i] || views[i].plan.nonce!=last_nonce[i])break;
            usleep(10000);
        }
        if(!running || (int32_t)(pool.deadline-now_ms())<=0)goto done;
        struct nw_state identity=views[i].plan;const struct nw_state *plan=&identity;
        struct neural_stream *s=views[i].stream;struct neural_decision *d=views[i].decision;
        uint32_t used=0,producer=0,candidate=0,claimed=0,last=now_ms(),max_queue=0;
        int success=0,speech_seen=0;const char *reason="deadline";
        if(completed)nm_begin(&model);
        while(running && (int32_t)(pool.deadline-now_ms())>0){
            if(now_ms()-cpu_tick>=1000){if(!nc_cpu_renew())goto done;cpu_tick=now_ms();}
            if(pool.rolling_limit && now_ms()-synced>=50){
                struct np_pool current;int state=np_read_locked(NP_FILE,&current,sizeof(current));
                if(state<0)goto done;
                int valid=np_valid(&current) && current.owner==pool.owner && current.observer==pool.observer &&
                    np_same(plan,&current.slot[i].plan);
                close(state);if(!valid || !np_refresh_views(views,&current))goto done;
                pool=current;synced=now_ms();
            }
            if(getppid()!=(pid_t)pool.owner || !alive(pool.owner) ||
               !alive(plan->expected_producer) || !alive(plan->expected_consumer))goto done;
            if(!ns_identity(s,plan->nonce,pool.owner) || s->observer!=pool.observer){reason="identity";break;}
            uint32_t state=__atomic_load_n(&s->state,__ATOMIC_ACQUIRE);
            if(state>=NS_INVALID){reason="revoked";break;}
            if(state!=NS_WAIT){
                if(s->producer!=plan->expected_producer){reason="producer";break;}
                if(!producer){producer=s->producer;claimed=last=now_ms();}
                if(now_ms()-claimed>28000){reason="turn-deadline";break;}
            }
            uint32_t next=__atomic_load_n(&s->used,__ATOMIC_ACQUIRE);
            if(next<used || next>NS_BYTES || next%320){reason="count";break;}
            if(next==used){
                if(state==NS_DONE){success=used!=0;reason=success?"complete":"empty";break;}
                if(producer && now_ms()-last>2000){reason="stalled";break;}
                usleep(state==NS_WAIT?(pool.resident?50000:10000):2000);continue;
            }
            unsigned queued=(next-used)/320;if(queued>max_queue)max_queue=queued;
            /* Delivery bursts are not lost audio. Allow up to 500 ms to be
             * caught up; endpoint authority still requires zero unread frames
             * and a fresh proposal. Larger overload remains a denied turn. */
            if(queued>50){reason="backlog";break;}
            float frame[160];for(unsigned j=0;j<160;j++){int16_t sample;memcpy(&sample,s->pcm+used+2*j,2);frame[j]=sample/32768.0f;}
            uint32_t tick=now_ms();int resetting=model.reseed;
            if(!nm_frame(&model,api,vad,frame)){reason="reset";break;}
            if(resetting)printf("NEURAL_POOL_RESET nonce=%u elapsed_ms=%u\n",plan->nonce,now_ms()-tick);
            if(__atomic_load_n(&s->state,__ATOMIC_ACQUIRE)==NS_INVALID){reason="revoked-inference";break;}
            used+=320;last=now_ms();
            if(VoiceActivityDetectorDetected(vad)){candidate=0;speech_seen=1;}
            while(!VoiceActivityDetectorEmpty(vad)){
                const SherpaOnnxSpeechSegment *segment=VoiceActivityDetectorFront(vad);
                if(!segment){reason="segment";goto turn_done;}
                speech_seen=1;candidate=used/320;DestroySpeechSegment(segment);VoiceActivityDetectorPop(vad);
                printf("NEURAL_POOL_CANDIDATE nonce=%u audio_ms=%u\n",plan->nonce,used/32);
            }
            uint32_t proposal=!speech_seen && used/320>=ND_START_FRAMES?ND_NO_SPEECH:candidate;
            nd_publish(d,(struct neural_proposal){producer,used/320,proposal,now_ms(),0});
        }
turn_done:
        if(!success)nd_publish(d,(struct neural_proposal){producer,used/320,0,now_ms(),1});
        views[i].receipt->frames=used/320;
        __atomic_store_n(&views[i].receipt->status,success?NQ_COMPLETE:NQ_INVALID,__ATOMIC_RELEASE);
        printf("NEURAL_POOL_DONE nonce=%u success=%d reason=%s frames=%u max_queue=%u\n",plan->nonce,success,reason,used/320,max_queue);
        completed++;last_nonce[i]=plan->nonce;
        if(!pool.rolling_limit && completed==pool.count)break;
    }
done:
    /* A receipt is not permission to terminate the shared process. Keep the
     * helper alive until the controller has retired the final generation;
     * otherwise its liveness check races the final completion handshake. */
    while(running && completed==pool.count && getppid()==(pid_t)pool.owner &&
          alive(pool.owner) && (int32_t)(pool.deadline-now_ms())>0){
        struct np_pool current;int state=np_read_locked(NP_FILE,&current,sizeof(current));
        if(state<0)break;
        int finished=!np_valid(&current) || current.owner!=pool.owner || current.observer!=pool.observer || !current.ready;
        close(state);if(finished)break;usleep(10000);
    }
    for(unsigned i=0;i<pool.count;i++){
        if(views[i].receipt && __atomic_load_n(&views[i].receipt->status,__ATOMIC_ACQUIRE)==NQ_WAIT){
            nd_publish(views[i].decision,(struct neural_proposal){0,0,0,now_ms(),1});
            __atomic_store_n(&views[i].receipt->status,NQ_INVALID,__ATOMIC_RELEASE);
        }
    }
    DestroyVoiceActivityDetector(vad);dlclose(lib);
    printf("NEURAL_POOL_EXIT completed=%u\n",completed);
    return running && completed==(pool.rolling_limit?pool.rolling_limit:pool.count)?0:1;
}
