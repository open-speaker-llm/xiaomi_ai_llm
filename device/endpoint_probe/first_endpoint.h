/* Firmware-specific, explicit one-shot experiment. No ASR-only rewrite and
 * no SDK global timeout changes. Included after native_asr and nw_state. */
#include <sys/mman.h>
#include "neural_stream.h"
#include "neural_decision.h"
#include "native_route.h"
static pthread_mutex_t first_lock=PTHREAD_MUTEX_INITIALIZER;
static struct neural_stream *first_stream;
static struct neural_decision *first_decision;
static void (*first_end)(unsigned);
static void (*first_stop)(void);
static void (*first_asr)(void *,void *,unsigned);
static int first_worker_ready;
static uint32_t first_local_owned;
static void *first_end_worker(void *);

static int first_exclusive(void) {
    struct control s;int fd=state_open(&s);
    if(fd<0)return 0;
    int ok=!active(&s);state_close(fd,NULL);return ok;
}
static void first_release(int valid) {
    if(first_stream){ns_close(first_stream,valid);munmap(first_stream,sizeof(*first_stream));first_stream=NULL;}
    if(first_decision){munmap(first_decision,sizeof(*first_decision));first_decision=NULL;}
}
static void first_close(int valid) {
    __atomic_store_n(&first_local_owned,0,__ATOMIC_RELEASE);first_release(valid);
}
static void *first_map(const char *path,size_t size,int writable) {
    int fd=open(path,(writable?O_RDWR:O_RDONLY)|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return NULL;
    struct stat st;
    int ok=!fstat(fd,&st) && S_ISREG(st.st_mode) && st.st_uid==geteuid() &&
        !(st.st_mode&077) && st.st_size==(off_t)size;
    void *p=ok?mmap(NULL,size,PROT_READ|(writable?PROT_WRITE:0),MAP_SHARED,fd,0):MAP_FAILED;
    close(fd);return p==MAP_FAILED?NULL:p;
}
static int first_claim(struct nw_state *s) {
    first_close(0);
    if(!s->mode || !s->nonce || s->expected_producer!=(uint32_t)getpid() ||
       !alive(s->expected_consumer) || !alive(s->observer) ||
       !first_end || !first_stop || !first_asr || !first_worker_ready || !first_exclusive() ||
       access("/tmp/mipns/mute",F_OK)==0 || access(NATIVE_BUSY_FILE,F_OK)==0)return 0;
    char path[256];nw_stream_path(path,sizeof(path),s);
    first_stream=first_map(path,sizeof(*first_stream),1);
    if(!first_stream)return 0;
    if(!ns_identity(first_stream,s->nonce,s->owner) || first_stream->observer!=s->observer ||
       !ns_claim(first_stream,s->nonce,s->owner,(uint32_t)getpid())){first_close(0);return 0;}
    size_t n=strlen(path);snprintf(path+n,sizeof(path)-n,".decision");
    first_decision=first_map(path,sizeof(*first_decision),0);
    if(!first_decision || !nd_identity(first_decision,s->nonce,s->owner,s->observer)){
        first_close(0);return 0;
    }
    return 1;
}
static int first_stream_ready(const struct nw_state *s) {
    char path[256];nw_stream_path(path,sizeof(path),s);
    struct neural_stream *p=first_map(path,sizeof(*p),0);
    if(!p)return 0;
    int ok=ns_identity(p,s->nonce,s->owner) && p->observer==s->observer &&
        p->producer==s->producer && __atomic_load_n(&p->state,__ATOMIC_ACQUIRE)==NS_LIVE;
    munmap(p,sizeof(*p));return ok;
}
static int first_modify(void *json,struct nw_state *s) {
    if(!nw_endpoint_identity(s) || s->consumer!=(uint32_t)getpid() ||
       ((s->mode==2 || s->mode==3) && !s->wake_modified) ||
       !alive(s->producer) || !alive(s->observer) || !first_exclusive() ||
       access("/tmp/mipns/mute",F_OK)==0 || !first_stream_ready(s))return 0;
    void (*ctor)(void *,int)=dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb");
    if(!ctor)return 0;
    if(!nr_begin(s)){note("FIRST_ENDPOINT bypass route-journal-unavailable");return 0;}
    void *payload=j_member(json,"payload");
    json_value v;
#define FIRST_BOOL(obj,key,b) do{ctor(&v,b);j_swap(j_member(obj,key),&v);j_dtor(&v);}while(0)
    FIRST_BOOL(j_member(payload,"asr"),"vad",0);
    FIRST_BOOL(payload,"is_using_local_vad",1);
    FIRST_BOOL(payload,"enable_natural_record_v2",0);
    FIRST_BOOL(j_member(j_member(payload,"asr"),"tuning_params"),"enable_timeout",0);
#undef FIRST_BOOL
    s->modified=1;
    note("FIRST_ENDPOINT request owner=%u dialog=%s cloud_vad=0 native_nlp_tts=preserved",s->owner,s->dialog);
    return 1;
}
static int first_modify_wakeup(void *json,struct nw_state *s) {
    if(s->mode!=2 && s->mode!=3)return 1;
    if(!nw_live(s) || s->phase!=NW_DIALOG || !s->prepared ||
       (s->mode==3 && (!s->accepted || !nw_tag_valid(s->tag))) ||
       s->producer!=s->expected_producer || s->consumer!=s->expected_consumer ||
       s->consumer!=(uint32_t)getpid() || !alive(s->producer) || !alive(s->observer) ||
       !first_exclusive() || !first_stream_ready(s))return 0;
    void (*ctor)(void *,int)=dlsym(RTLD_NEXT,"_ZN4Json5ValueC1Eb");if(!ctor)return 0;
    json_value v;ctor(&v,0);j_swap(j_member(j_member(json,"payload"),"enable_natural_record_v2"),&v);j_dtor(&v);
    s->wake_modified=1;
    note("FIRST_ENDPOINT wakeup owner=%u dialog=%s natural_record_v2=0",s->owner,s->dialog);
    return 1;
}
static void first_pcm(void *ctx,void *pcm,unsigned bytes) {
    pthread_mutex_lock(&first_lock);
    struct nw_state s;int fd=nw_open(&s);
    if(fd>=0){
        if(nw_can_end(&s,(uint32_t)getpid()) && first_stream &&
           ns_identity(first_stream,s.nonce,s.owner)) {
            __atomic_store_n(&first_local_owned,s.nonce,__ATOMIC_RELEASE);
            if(bytes && bytes<=8192 && bytes%320==0 && ns_append(first_stream,pcm,bytes))
                s.frames=first_stream->used/320;
            else ns_close(first_stream,0);
            nw_close(fd,&s);
        }else nw_close(fd,NULL);
    }else first_release(0);
    if(first_asr)first_asr(ctx,pcm,bytes); /* Original input, unchanged, once. */
    pthread_mutex_unlock(&first_lock);
}
static int first_register_upload(void *asr,ivw_fn ivw,void *ctx,unsigned mode,unsigned flag) {
    int (*fn)(void *,ivw_fn,void *,unsigned,unsigned)=dlsym(RTLD_NEXT,"register_data_upload_callback");
    if((uintptr_t)asr==0x1917cu){
        first_asr=(void (*)(void *,void *,unsigned))asr;asr=(void *)first_pcm;
        note("FIRST_ENDPOINT asr-callback supported=1");
    }
    return fn?fn(asr,ivw,ctx,mode,flag):-1;
}
void *create_xaudio(uint32_t a,uint32_t b,uint32_t c,uint32_t d,uint32_t e,
                   uint32_t f,uint32_t g,uint32_t h,uint32_t i,uint32_t j) {
    if(e==0x184c0u && role==1){
        first_end=(void (*)(unsigned))(uintptr_t)e;
        *(void **)(&first_stop)=dlsym(RTLD_NEXT,"set_unwakeup_status");
        pthread_t thread;
        if(!pthread_create(&thread,NULL,first_end_worker,NULL)){
            pthread_detach(thread);first_worker_ready=1;
        }
        note("FIRST_ENDPOINT callbacks end=%p worker=%d",(void *)first_end,first_worker_ready);
    }
    void *(*fn)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t)=dlsym(RTLD_NEXT,"create_xaudio");
    return fn?fn(a,b,c,d,e,f,g,h,i,j):NULL;
}
unsigned xaudio_vad_get_timeout(void *vad) {
    unsigned (*fn)(void *)=dlsym(RTLD_NEXT,"xaudio_vad_get_timeout");
    unsigned original=fn?fn(vad):0;
    struct nw_state s;int fd=nw_open(&s);
    int own=fd>=0 && nw_can_end(&s,(uint32_t)getpid());
    if(fd>=0)nw_close(fd,NULL);
    /* The original timer remains a final cap if the trial owner disappears.
     * A new prepare/wake clears the process-local token before native dispatch. */
    return role==1 && (own || __atomic_load_n(&first_local_owned,__ATOMIC_ACQUIRE))?22000u:original;
}
static void first_instruction(void *json) {
    const void *h=member(json,"header");
    const char *id=string_member(h,"dialog_id"),*ns=string_member(h,"namespace"),*name=string_member(h,"name");
    struct nw_state s;int fd=nw_open(&s);
    if(fd<0)return;
    int own=s.dialog[0] && !strcmp(s.dialog,id) && s.consumer==(uint32_t)getpid();
    int changed=0;
    if(own){
        if(!strcmp(ns,"SpeechRecognizer") && !strcmp(name,"RecognizeResult")){
            const void *v=member(member(json,"payload"),"is_final");
            if(v && j_type(v)==5 && j_bool(v)){s.final_seen=1;changed=1;}
        }
        if(!strcmp(ns,"Dialog") && !strcmp(name,"Finish")){s.finished=1;changed=1;}
        if(!strcmp(ns,"SpeechRecognizer") && !strcmp(name,"StopCapture")){s.ended=1;changed=1;}
        if(!strcmp(ns,"System") && (!strcmp(name,"Exception") || !strcmp(name,"Abort") || !strcmp(name,"TruncationNotification"))){s.failed=1;changed=1;}
        if(changed || (!strcmp(ns,"SpeechSynthesizer") && !strcmp(name,"Speak")))
            note("FIRST_ENDPOINT instruction owner=%u event=%s.%s final=%u finished=%u",s.owner,ns,name,s.final_seen,s.finished);
    }
    nw_close(fd,changed?&s:NULL);
}
static void first_end_step(void) {
        pthread_mutex_lock(&first_lock);
        pthread_mutex_lock(&wake_dispatch_lock);
        struct nw_state s;int fd=nw_open(&s);
        int own=fd>=0 && nw_can_end(&s,(uint32_t)getpid()) &&
            alive(s.consumer) && first_stream && ns_identity(first_stream,s.nonce,s.owner);
        if(fd>=0)nw_close(fd,NULL);
        if(!own){
            if(fd<0)first_release(0);
            else if(s.ended || s.final_seen || s.finished || s.failed)first_close(!s.failed);
            pthread_mutex_unlock(&wake_dispatch_lock);pthread_mutex_unlock(&first_lock);return;
        }
        int fault=!alive(s.observer) || first_stream->state==NS_INVALID;
        struct neural_proposal p;
        if(first_decision && nd_read(first_decision,&p) && p.invalid)fault=1;
        int limit=(uint32_t)(now_ms()-s.wake_ms)>=20000;
        int quiet=nd_due(first_stream,first_decision,s.nonce,s.owner,(uint32_t)getpid(),now_ms());
        int empty=nd_no_speech_due(first_stream,first_decision,s.nonce,s.owner,(uint32_t)getpid(),now_ms());
        if(fault || limit || quiet || empty){
            struct nw_state check;fd=nw_open(&check);
            int valid=fd>=0 && nw_can_end(&check,(uint32_t)getpid()) &&
                check.nonce==s.nonce && check.owner==s.owner && !strcmp(check.dialog,s.dialog) &&
                alive(check.consumer) && first_exclusive() && access("/tmp/mipns/mute",F_OK)!=0;
            if(valid && quiet && !fault && !limit)
                valid=alive(check.observer) && nd_due(first_stream,first_decision,check.nonce,check.owner,(uint32_t)getpid(),now_ms());
            if(valid && empty && !fault && !limit)
                valid=alive(check.observer) && nd_no_speech_due(first_stream,first_decision,check.nonce,check.owner,(uint32_t)getpid(),now_ms());
            if(valid && first_stop && first_end){
                check.ended=1;check.failed=(uint32_t)fault;check.end_reason=fault?3:limit?2:empty?NW_END_NO_SPEECH:1;
                nw_close(fd,&check);fd=-1;
                note("FIRST_ENDPOINT end owner=%u reason=%s audio_ms=%u elapsed_ms=%u dialog=%s",
                    check.owner,fault?"helper-failed":limit?"limit":empty?"no-speech":"quiet",check.frames*10,now_ms()-check.wake_ms,check.dialog);
                first_stop();first_end(4);first_close(!fault);
            }
            if(fd>=0)nw_close(fd,NULL);
        }
        pthread_mutex_unlock(&wake_dispatch_lock);pthread_mutex_unlock(&first_lock);
}
static void *first_end_worker(void *arg) {
    (void)arg;
    for(;;){usleep(20000);first_end_step();}
    return NULL;
}
