/* Temporary firmware-specific experiment, NEVER the production build.
 * Reuses native ASR ownership/cancellation. Replays a bounded, previously
 * recorded test utterance; live audio is saved only by opt-in capture trials.
 * Compile as a replacement preload in /tmp, restore both services afterwards.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>
#include <sys/mman.h>
static void *probe_lookup(void *,const char *);
static int probe_serialize(const void *,void *);
static void *probe_register(void *,void (*)(void *,unsigned,float),void *);
static void *end_worker(void *);
static int probe_register_upload(void *,void (*)(unsigned,void *,unsigned,unsigned,int),void *,unsigned,unsigned);
#define dlsym probe_lookup
#include "../native_asr/native_asr.c"
#undef dlsym

#ifndef PROBE_DIR
#define PROBE_DIR "/tmp/xiaomi_endpoint_protocol"
#endif
#define MAX_PCM (20u*32000u)
static void (*oneshot)(unsigned);
static uint32_t replay_seq, replay_owner, replay_bytes, replay_used, replay_finished;
static uint32_t replay_deadline;
static unsigned char replay[MAX_PCM];
static int replay_loaded, end_sent, cloud_vad;
static pthread_mutex_t replay_lock=PTHREAD_MUTEX_INITIALIZER;
static wake_fn chained_wake;
static void (*chained_asr)(void *,void *,unsigned);
#ifdef PROBE_ACTIVE_ENDPOINT
#include <fvad.h>
#include "endpoint_active.h"
#include "capture_buffer.h"
#include "neural_stream.h"
#include "neural_decision.h"
static struct neural_stream *neural_stream;
static struct neural_decision *neural_decision;
static void neural_close(int valid) {
    if(neural_stream){ns_close(neural_stream,valid);munmap(neural_stream,sizeof(*neural_stream));neural_stream=NULL;}
    if(neural_decision){munmap(neural_decision,sizeof(*neural_decision));neural_decision=NULL;}
}
static int neural_open(uint32_t seq,uint32_t owner,unsigned mode) {
    neural_close(0);
    char path[192];snprintf(path,sizeof(path),PROBE_DIR "/shadow.%u.%u.stream",seq,owner);
    int fd=open(path,O_RDWR|O_CLOEXEC|O_NOFOLLOW);if(fd<0)return 0;
    struct stat st;
    int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
        !(st.st_mode&077) && st.st_size==(off_t)sizeof(struct neural_stream);
    struct neural_stream *p=ok?mmap(NULL,sizeof(*p),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0):MAP_FAILED;
    close(fd);if(p==MAP_FAILED)return 0;
    if(!ns_identity(p,seq,owner) || kill((pid_t)p->observer,0) ||
       !ns_claim(p,seq,owner,(uint32_t)getpid())){munmap(p,sizeof(*p));return 0;}
    neural_stream=p;
    if(mode==7){
        snprintf(path,sizeof(path),PROBE_DIR "/shadow.%u.%u.stream.decision",seq,owner);
        fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
        if(fd<0){neural_close(0);return 0;}
        ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
            !(st.st_mode&077) && st.st_size==(off_t)sizeof(struct neural_decision);
        struct neural_decision *d=ok?mmap(NULL,sizeof(*d),PROT_READ,MAP_SHARED,fd,0):MAP_FAILED;
        close(fd);
        if(d==MAP_FAILED){neural_close(0);return 0;}
        if(!nd_identity(d,seq,owner,p->observer)){munmap(d,sizeof(*d));neural_close(0);return 0;}
        neural_decision=d;
    }
    return 1;
}
static struct capture_buffer diagnostic_capture;
static Fvad *active_vad;
static struct endpoint_active active_endpoint;
static Fvad *compare_vad[2];
static struct endpoint_active compare_endpoint[2];
static int previous_voice[3];
static uint32_t active_started;
static unsigned active_mode;
#define MAX_PROBE_MODE 7
static void active_feed(const void *data,unsigned bytes) {
    for(unsigned offset=0;offset<bytes && !active_endpoint.reason;offset+=320) {
        int16_t frame[160];memcpy(frame,(const unsigned char *)data+offset,sizeof(frame));
        int voice[3]={fvad_process(active_vad,frame,160),-1,-1};
        for(unsigned i=0;i<2;i++)if(compare_vad[i])voice[i+1]=fvad_process(compare_vad[i],frame,160);
        uint64_t power=0;unsigned peak=0;
        for(unsigned i=0;i<160;i++) {
            int x=frame[i];unsigned a=(unsigned)(x<0?-x:x);
            power+=(uint64_t)(x*x);if(a>peak)peak=a;
        }
        for(unsigned i=0;i<3;i++) {
            if(voice[i]!=previous_voice[i]) {
                note("ACTIVE edge mode=%u voice=%d audio_ms=%u mean_square=%llu peak=%u",
                    i+1,voice[i],active_endpoint.frames*10,(unsigned long long)(power/160),peak);
                previous_voice[i]=voice[i];
            }
            if(i && compare_vad[i-1] && !compare_endpoint[i-1].reason &&
               endpoint_tick(&compare_endpoint[i-1],voice[i])) {
                note("ACTIVE comparison mode=%u reason=%s audio_ms=%u action=observe-only",i+1,
                    endpoint_reason_name(compare_endpoint[i-1].reason),compare_endpoint[i-1].frames*10);
            }
        }
        endpoint_tick(&active_endpoint,voice[0]);
    }
}
#else
#define MAX_PROBE_MODE 3
#endif
static void probe_wake(void *ctx,unsigned code,float angle) {
    if((code&255u)==1) {
        pthread_mutex_lock(&replay_lock);
        replay_loaded=0;end_sent=1;
#ifdef PROBE_ACTIVE_ENDPOINT
        capture_reset(&diagnostic_capture,0);
        neural_close(0);
#endif
        pthread_mutex_unlock(&replay_lock);
    }
    if(chained_wake)chained_wake(ctx,code,angle);
}
static void *probe_register(void *engine,wake_fn callback,void *ctx) {
    void *(*fn)(void *,wake_fn,void *)=dlsym(RTLD_NEXT,"xaudio_register_callback");
    chained_wake=callback;
    return fn?fn(engine,probe_wake,ctx):NULL;
}

/* Configuration is written before listen, contains its exact sequence/owner,
 * and expires with that native ASR lease. No broad "next dialog" matching. */
static int private_config(const char *path,uint32_t *seq,uint32_t *owner,unsigned *vad) {
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return 0;
    struct stat st; char b[96]={0},extra;
    ssize_t n=read(fd,b,sizeof(b)-1);
    int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
        !(st.st_mode&077) && n>0 &&
        sscanf(b,"%u %u %u %c",seq,owner,vad,&extra)==3 && *seq && *owner>1 && *vad<=MAX_PROBE_MODE;
    close(fd);return ok;
}
static int config(uint32_t *seq,uint32_t *owner,unsigned *vad) {
    return private_config(PROBE_DIR "/armed",seq,owner,vad);
}
#ifdef PROBE_ACTIVE_ENDPOINT
/* Called only after an owned local endpoint, never by a real wake or callback.
 * Unique sequence/owner filename, no overwriting or symlink following. A failed
 * write removes its own partial artifact and is explicitly logged. */
static void capture_save(uint32_t seq,uint32_t owner) {
    if(!diagnostic_capture.enabled)return;
    char path[192];snprintf(path,sizeof(path),PROBE_DIR "/capture.%u.%u.pcm",seq,owner);
    int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    unsigned count=diagnostic_capture.used,done=0;
    if(fd>=0) {
        while(done<count) {
            ssize_t n=write(fd,diagnostic_capture.pcm+done,count-done);
            if(n<0 && errno==EINTR)continue;
            if(n<=0)break;
            done+=(unsigned)n;
        }
        if(close(fd)!=0 || done!=count) {unlink(path);done=0;}
    }
    note("ACTIVE capture seq=%u bytes=%u saved=%u rate=16000 channels=1 format=s16le",seq,count,done);
    capture_reset(&diagnostic_capture,0);
}
#endif
static int eligible(const struct control *s,uint32_t seq,uint32_t owner) {
    return active(s) && s->sequence==seq && s->owner==owner &&
        s->phase>=TRIGGERED && s->phase<=BOUND && !s->final_seen;
}
static int end_lease_owned(const struct control *s,uint32_t seq,uint32_t owner) {
    return eligible(s,seq,owner) && s->phase==BOUND &&
        s->mipns_pid==(uint32_t)getpid() && alive(s->aivs_pid);
}
#ifdef PROBE_ACTIVE_ENDPOINT
/* Verified SDK 21656da7...: checkTimeout reads Tts::RECV_TIMEOUT at
 * 0xdf880, returning to 0xdf884. This API has no dialog argument: the guard
 * is scoped to this call site and an exclusively owned ASR-only lease, NOT
 * proven per SDK EventWrapper. Never enable for concurrent native dialogs. */
static int sdk_timeout_scope(const struct control *s,uint32_t seq,uint32_t owner,
                             unsigned mode,int original) {
    /* Parsing Finish publishes COMPLETE before the SDK consumes its queue.
     * Keep the same bounded, still-armed lease protected while it drains;
     * otherwise restoring 10 s here can time out an already old event just
     * before the queued Finish is processed. No extra deadline is granted. */
    int draining=(s->phase==COMPLETE || s->phase==IDLE) && s->final_seen && s->finished;
    return mode>=3 && mode<=MAX_PROBE_MODE && original>0 && original<30 &&
        alive(s->owner) && (int32_t)(s->deadline-now_ms())>0 &&
        s->sequence==seq && s->owner==owner &&
        (s->phase==BOUND || s->phase==RESULT || draining) && s->dialog[0] &&
        s->aivs_pid==(uint32_t)getpid() && alive(s->mipns_pid);
}
int probe_sdk_integer(void *,const void *,int *)
    __asm__("_ZN4aivs10AivsConfig10getIntegerERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEERi");
int probe_sdk_integer(void *self,const void *key,int *value) {
    int (*fn)(void *,const void *,int *)=dlsym(RTLD_NEXT,
        "_ZN4aivs10AivsConfig10getIntegerERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEERi");
    int ok=fn?fn(self,key,value):0;
    if(!ok || role!=2 || !value || *value<=0 || *value>=30)return ok;
    /* The executable has an R_ARM_COPY of this exported std::string. Resolve
     * the process-wide definition, not the unused SDK storage via RTLD_NEXT. */
    const void *tts_key=dlsym(RTLD_DEFAULT,"_ZN4aivs10AivsConfig3Tts12RECV_TIMEOUTB5cxx11E");
    Dl_info info;
    void *caller=__builtin_extract_return_addr(__builtin_return_address(0));
    if(key!=tts_key || !dladdr(caller,&info) ||
       (uintptr_t)caller-(uintptr_t)info.dli_fbase!=0xdf884u)return ok;
    uint32_t seq,owner;unsigned mode;
    if(!config(&seq,&owner,&mode))return ok;
    struct control s;int fd=state_open(&s);
    int scoped=fd>=0 && sdk_timeout_scope(&s,seq,owner,mode,*value);
    if(fd>=0)state_close(fd,NULL);
    if(scoped) {
        static _Thread_local uint32_t logged_seq;
        if(logged_seq!=seq) {
            logged_seq=seq;
            note("ACTIVE sdk-tts-timeout seq=%u native_s=%d experiment_s=30 caller=0xdf884",seq,*value);
        }
        *value=30;
    }
    return ok;
}
#endif
/* Mode 3 changes only reads of this timer during the exact test lease.
 * No global setter, no writes into opaque firmware structures, no unlimited
 * timer. Expiration, final, handoff or removed armed file restores native reads. */
static unsigned scoped_timeout(const struct control *s,uint32_t seq,uint32_t owner,
                               unsigned mode,unsigned original) {
    return mode>=3 && mode<=MAX_PROBE_MODE && eligible(s,seq,owner) ?
        (mode>=6?30000u:(mode>=4?25000u:20000u)) : original;
}
unsigned xaudio_vad_get_timeout(void *vad) {
    unsigned (*fn)(void *)=dlsym(RTLD_NEXT,"xaudio_vad_get_timeout");
    unsigned original=fn?fn(vad):0,mode;uint32_t seq,owner;
    if(role!=1 || !config(&seq,&owner,&mode) || mode<3)return original;
    struct control s;int fd=state_open(&s);
    unsigned result=fd>=0?scoped_timeout(&s,seq,owner,mode,original):original;
    if(fd>=0)state_close(fd,NULL);
    static _Thread_local uint32_t logged_seq;
    if(result!=original && logged_seq!=seq) {
        logged_seq=seq;
        note("PROBE local-timeout seq=%u native_ms=%u experiment_ms=%u",seq,original,result);
    }
    return result;
}
void wakeup_set_asr_end_waiting_flag(void *wake,int flag) {
    void (*fn)(void *,int)=dlsym(RTLD_NEXT,"wakeup_set_asr_end_waiting_flag");
    uint32_t seq,owner;unsigned mode;
    if(role==1 && config(&seq,&owner,&mode))
        note("PROBE wait-flag seq=%u flag=%d",seq,flag);
    if(fn)fn(wake,flag);
}
void wakeup_reset_asr_end_wait_timeout_cnt(void *wake) {
    void (*fn)(void *)=dlsym(RTLD_NEXT,"wakeup_reset_asr_end_wait_timeout_cnt");
    uint32_t seq,owner;unsigned mode;
    if(role==1 && config(&seq,&owner,&mode))note("PROBE wait-reset seq=%u",seq);
    if(fn)fn(wake);
}
static void put_bool(void *v,const char *key,int value) {
    void (*ctor)(void *,int)=dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb");
    json_value tmp; ctor(&tmp,value); j_swap(j_member(v,key),&tmp); j_dtor(&tmp);
}
static int probe_serialize(const void *event,void *json) {
    int (*fn)(const void *,void *)=dlsym(RTLD_NEXT,"_ZNK4aivs5Event6toJsonERN4Json5ValueE");
    int ok=fn?fn(event,json):0;
    if(!ok || role!=2 || !json_ready)return ok;
    const void *h=member(json,"header");
    if(strcmp(string_member(h,"namespace"),"SpeechRecognizer"))return ok;
    const char *name=string_member(h,"name"),*id=string_member(h,"id");
    if(!strcmp(name,"RecognizeStreamFinished")) {
        note("PROBE stream-finished id=%s dialog=%s",id,string_member(h,"dialog_id"));
        return ok;
    }
    if(strcmp(name,"Recognize"))return ok;
    uint32_t seq,owner;unsigned vad;
    if(!config(&seq,&owner,&vad))return ok;
    struct control s;int fd=state_open(&s);
    int own=fd>=0 && eligible(&s,seq,owner) &&
        ((s.phase==PREPARED && prepare_scope==seq) ||
         (s.phase==BOUND && s.dialog[0] && !strcmp(s.dialog,id)));
    if(fd>=0)state_close(fd,NULL);
    if(!own)return ok;
    if(!dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb"))return 0;
    if(vad!=1) {
        void *payload=j_member(json,"payload");
        put_bool(j_member(payload,"asr"),"vad",0);
        put_bool(payload,"is_using_local_vad",1);
        put_bool(payload,"enable_natural_record_v2",0);
        if(vad>=2) {
            put_bool(j_member(j_member(payload,"asr"),"tuning_params"),"enable_timeout",0);
        }
    }
    note("PROBE recognize seq=%u cloud_vad=%u dialog=%s",seq,vad,id);
    return ok;
}
static void *probe_lookup(void *handle,const char *name) {
    if(!strcmp(name,"_ZNK4aivs5Event6toJsonERN4Json5ValueE"))return (void *)probe_serialize;
    if(!strcmp(name,"xaudio_register_callback"))return (void *)probe_register;
    if(!strcmp(name,"register_data_upload_callback"))return (void *)probe_register_upload;
    return dlsym(handle,name);
}

void *create_xaudio(uint32_t a,uint32_t b,uint32_t c,uint32_t d,uint32_t e,
                    uint32_t f,uint32_t g,uint32_t h,uint32_t i,uint32_t j) {
    /* For the verified mipns image, this runtime-registered callback is
     * mipns_oneshot_cb at 0x184c0. Codes 4/5 mean vad-end/vad-timeout.
     * A mismatch disables replay; never call an inferred function address. */
    if(e==0x184c0u)oneshot=(void (*)(unsigned))(uintptr_t)e;
#ifdef PROBE_ACTIVE_ENDPOINT
    if(role==1 && oneshot && !active_vad) {
        active_vad=fvad_new();
        if(!active_vad || fvad_set_sample_rate(active_vad,16000) || fvad_set_mode(active_vad,1)) {
            if(active_vad)fvad_free(active_vad);
            active_vad=NULL;oneshot=NULL;
        }
        note("ACTIVE vad-ready=%d quiet_ms=2000 confirm_ms=120 no_speech_ms=8000 hard_ms=20000",active_vad!=NULL);
        for(unsigned k=0;k<2;k++) {
            compare_vad[k]=fvad_new();
            if(compare_vad[k] && (fvad_set_sample_rate(compare_vad[k],16000) || fvad_set_mode(compare_vad[k],(int)k+2))) {
                fvad_free(compare_vad[k]);compare_vad[k]=NULL;
            }
        }
    }
#endif
    note("PROBE callbacks end=%p supported=%d",(void *)(uintptr_t)e,oneshot!=NULL);
    if(oneshot && role==1) {
        pthread_t thread;
        int rc=pthread_create(&thread,NULL,end_worker,NULL);
        if(!rc)pthread_detach(thread);
        else oneshot=NULL;
        note("PROBE end-worker rc=%d",rc);
    }
    void *(*fn)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t)=dlsym(RTLD_NEXT,"create_xaudio");
    return fn?fn(a,b,c,d,e,f,g,h,i,j):NULL;
}

static int load_replay(const struct control *s) {
    uint32_t seq,owner;unsigned vad;
    if(!oneshot || !config(&seq,&owner,&vad) || !eligible(s,seq,owner))return 0;
    if(replay_seq==seq && replay_owner==owner)return replay_loaded;
    replay_seq=seq;replay_owner=owner;replay_loaded=0;replay_used=0;
    replay_finished=0;end_sent=0;replay_deadline=s->deadline;cloud_vad=vad==1;
#ifdef PROBE_ACTIVE_ENDPOINT
    neural_close(0);
    active_mode=vad;
    capture_reset(&diagnostic_capture,0);
    if(vad>=4) {
        if(!active_vad)return 0;
        fvad_reset(active_vad);
        if(fvad_set_sample_rate(active_vad,16000) || fvad_set_mode(active_vad,1))return 0;
        active_endpoint=(struct endpoint_active){0};active_started=now_ms();
        for(unsigned k=0;k<3;k++)previous_voice[k]=-1;
        for(unsigned k=0;k<2;k++) {
            compare_endpoint[k]=(struct endpoint_active){0};
            if(compare_vad[k]) {
                fvad_reset(compare_vad[k]);
                fvad_set_sample_rate(compare_vad[k],16000);fvad_set_mode(compare_vad[k],(int)k+2);
            }
        }
        note("ACTIVE start seq=%u mode=%u source=%s",seq,vad,vad>=5?"microphone":"replay");
        if(vad>=6) {
            if(!neural_open(seq,owner,vad))return 0;
            replay_bytes=0;replay_loaded=1;return 1;
        }
        if(vad==5) {
            uint32_t capture_seq,capture_owner;unsigned capture_mode;
            diagnostic_capture.enabled=private_config(PROBE_DIR "/capture.armed",
                &capture_seq,&capture_owner,&capture_mode) && capture_seq==seq &&
                capture_owner==owner && capture_mode==5;
            note("ACTIVE capture-enabled seq=%u enabled=%u max_bytes=%u",seq,diagnostic_capture.enabled,CAPTURE_BYTES);
            replay_bytes=0;replay_loaded=1;return 1;
        }
    }
#endif
    int fd=open(PROBE_DIR "/input.pcm",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return 0;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || st.st_size<32000 || st.st_size>(off_t)MAX_PCM || st.st_size%320) {
        close(fd);return 0;
    }
    replay_bytes=(uint32_t)st.st_size;
    size_t got=0;
    while(got<replay_bytes) {ssize_t n=read(fd,replay+got,replay_bytes-got);if(n<=0)break;got+=(size_t)n;}
    close(fd);replay_loaded=got==replay_bytes;
    note("PROBE replay seq=%u loaded=%d bytes=%u cloud_vad=%d",seq,replay_loaded,replay_bytes,cloud_vad);
    return replay_loaded;
}

static void replay_asr(void *ctx,void *input,unsigned length) {
    if(!chained_asr)return;
    if(role!=1 || !length || length>8192 || length%320) {
        chained_asr(ctx,input,length);return;
    }
    unsigned char buffer[8192];void *data=input;
    pthread_mutex_lock(&wake_dispatch_lock);
    pthread_mutex_lock(&replay_lock);
    struct control s;int fd=state_open(&s);
    if(fd>=0) {
        if(load_replay(&s)) {
#ifdef PROBE_ACTIVE_ENDPOINT
            if(active_mode>=5) {
                if(s.phase==BOUND && !end_sent) {
                    if(active_mode>=6) {
                        if(neural_stream && ns_append(neural_stream,input,length))
                            active_endpoint.frames=neural_stream->used/320;
                    } else {
                        capture_append(&diagnostic_capture,input,length);
                        active_feed(input,length);
                    }
                }
            } else
#endif
            {
            memset(buffer,0,length);data=buffer;
            if(s.phase==BOUND && replay_used<replay_bytes) {
                if(!replay_used)note("PROBE asr-block bytes=%u",length);
                unsigned copy=replay_bytes-replay_used;
                if(copy>length)copy=length;
                memcpy(buffer,replay+replay_used,copy);replay_used+=copy;
                if(replay_used==replay_bytes) {
                    replay_finished=now_ms();
                    note("PROBE replay-finished seq=%u samples=%u",s.sequence,replay_used/2);
                }
            }
#ifdef PROBE_ACTIVE_ENDPOINT
            if(active_mode==4 && s.phase==BOUND && !end_sent)active_feed(data,length);
#endif
            }
        } else if(replay_loaded && access(PROBE_DIR "/armed",F_OK)==0 &&
                  s.sequence==replay_seq && s.owner==replay_owner &&
                  s.phase!=NATIVE_HANDOFF && (int32_t)(replay_deadline-now_ms())>0) {
#ifdef PROBE_ACTIVE_ENDPOINT
            if(active_mode<5)
#endif
            {memset(buffer,0,length);data=buffer;}
        }
        state_close(fd,NULL);
    }
    pthread_mutex_unlock(&replay_lock);
    chained_asr(ctx,data,length);
    pthread_mutex_unlock(&wake_dispatch_lock);
}
static int probe_register_upload(void *asr,ivw_fn ivw,void *ctx,unsigned mode,unsigned flag) {
    int (*fn)(void *,ivw_fn,void *,unsigned,unsigned)=dlsym(RTLD_NEXT,"register_data_upload_callback");
    if((uintptr_t)asr==0x1917cu) {
        chained_asr=(void (*)(void *,void *,unsigned))asr;
        asr=(void *)replay_asr;
        note("PROBE asr-callback supported=1");
    }
    return fn?fn(asr,ivw,ctx,mode,flag):-1;
}

static void *end_worker(void *arg) {
    (void)arg;
    for(;;) {
        usleep(20000);
        pthread_mutex_lock(&wake_dispatch_lock);
        pthread_mutex_lock(&replay_lock);
        int due=replay_finished && (uint32_t)(now_ms()-replay_finished)>=300;
#ifdef PROBE_ACTIVE_ENDPOINT
        enum endpoint_reason reason=EP_LISTEN;
        if(active_mode>=6 && neural_stream) {
            struct control current;int check_fd=state_open(&current);
            uint32_t seq,owner;unsigned mode;
            int valid=check_fd>=0 && eligible(&current,replay_seq,replay_owner) &&
                config(&seq,&owner,&mode) && seq==replay_seq && owner==replay_owner && mode==active_mode &&
                access("/tmp/mipns/mute",F_OK)!=0 && !kill((pid_t)neural_stream->observer,0);
            if(check_fd>=0)state_close(check_fd,NULL);
            if(!valid)neural_close(0);
        }
        if(active_mode>=6) {
            reason=(uint32_t)(now_ms()-active_started)>=24000?EP_LIMIT:EP_LISTEN;
            if(active_mode==7 && reason==EP_LISTEN &&
               nd_due(neural_stream,neural_decision,replay_seq,replay_owner,(uint32_t)getpid(),now_ms()))reason=EP_QUIET;
            due=reason!=EP_LISTEN;
        } else if(active_mode>=4) {
            reason=endpoint_wall(&active_endpoint,now_ms()-active_started);
            due=reason!=EP_LISTEN;
        }
#endif
        if(replay_loaded && !end_sent && !cloud_vad && due) {
            struct control s;int fd=state_open(&s);
            uint32_t seq,owner;unsigned vad;
            int own=fd>=0 && end_lease_owned(&s,replay_seq,replay_owner) &&
                access("/tmp/mipns/mute",F_OK)!=0 &&
                config(&seq,&owner,&vad) && seq==replay_seq && owner==replay_owner && vad!=1;
#ifdef PROBE_ACTIVE_ENDPOINT
            own=own && vad==active_mode;
            if(active_mode==7 && reason==EP_QUIET && own &&
               !(nd_due(neural_stream,neural_decision,replay_seq,replay_owner,(uint32_t)getpid(),now_ms()) &&
                 !kill((pid_t)neural_stream->observer,0))) {
                if(fd>=0)state_close(fd,NULL);
                pthread_mutex_unlock(&replay_lock);pthread_mutex_unlock(&wake_dispatch_lock);
                continue; /* A changed proposal does not disarm the fixed cap. */
            }
#endif
            if(fd>=0)state_close(fd,NULL);
            end_sent=1;
            if(own) {
                void (*stop)(void)=dlsym(RTLD_NEXT,"set_unwakeup_status");
                if(stop && oneshot) {
#ifdef PROBE_ACTIVE_ENDPOINT
                    if(active_mode>=4)note("ACTIVE decision seq=%u reason=%s audio_ms=%u elapsed_ms=%u last_voice_ms=%u used=%u",
                        replay_seq,endpoint_reason_name(reason),active_endpoint.frames*10,
                        now_ms()-active_started,active_endpoint.last_voice*10,replay_used);
#endif
                    note("PROBE local-end seq=%u used=%u",replay_seq,replay_used);
                    stop();oneshot(4);
#ifdef PROBE_ACTIVE_ENDPOINT
                    if(active_mode>=6)neural_close(1);
                    capture_save(replay_seq,replay_owner);
#endif
                }
            } else note("PROBE end skipped; lease cancelled/replaced/final seq=%u",replay_seq);
#ifdef PROBE_ACTIVE_ENDPOINT
            neural_close(0);
            capture_reset(&diagnostic_capture,0);
#endif
        }
        pthread_mutex_unlock(&replay_lock);
        pthread_mutex_unlock(&wake_dispatch_lock);
    }
    return NULL;
}
