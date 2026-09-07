/* Boot1 1.76.54 only; the service manager verifies all native ABI hashes.
 * No executable patches, artificial audio or credentials. The original native
 * microphone stream feeds a fresh ASR-only Xiaomi cloud dialog. */
#include "control.h"
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <stdarg.h>
#include <sys/prctl.h>

typedef void (*wake_fn)(void *, unsigned, float);
typedef void (*ivw_fn)(unsigned, void *, unsigned, unsigned, int);
static wake_fn original_wake;
static ivw_fn original_ivw;
static void *wake_context;
static float last_angle;
static pthread_mutex_t wake_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t wake_dispatch_lock = PTHREAD_MUTEX_INITIALIZER;
#ifndef NATIVE_BUSY_FILE
#define NATIVE_BUSY_FILE "/tmp/native_first_busy"
#endif
static int role; /* 1=mipns, 2=aivs */
static __thread uint32_t prepare_scope;
static __thread const void *prepare_message;
static void note(const char *fmt, ...) {
    char b[512]; va_list ap;
    int n = snprintf(b, sizeof(b), "%u pid=%d ", now_ms(), (int)getpid());
    va_start(ap, fmt); vsnprintf(b+n, sizeof(b)-(size_t)n, fmt, ap); va_end(ap);
    int fd = open(CONTROL_DIR "/events.log", O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW, 0600);
    if (fd >= 0) { (void)write(fd,b,strnlen(b,sizeof(b))); (void)write(fd,"\n",1); close(fd); }
}

/* This firmware plays its local wake cue in a new wakeup_tone_raw thread,
 * directly through ALSA, bypassing wakeup.sh and mediaplayer. Keep the PCM
 * length and playback completion intact, but silence this one read buffer.
 * Ownership is captured at thread creation so a delayed cue stays silent
 * even if its ASR request has already finished or been cancelled. */
static __thread uint32_t cue_sequence;
static __thread FILE *cue_file;
struct cue_start { void *(*fn)(void *); void *arg; uint32_t sequence; };
static void *cue_thread(void *arg) {
    struct cue_start start=*(struct cue_start *)arg; free(arg);
    cue_sequence=start.sequence;
    return start.fn(start.arg);
}
int pthread_create(pthread_t *thread,const pthread_attr_t *attr,void *(*start)(void *),void *arg) {
    int (*fn)(pthread_t *,const pthread_attr_t *,void *(*)(void *),void *)=dlsym(RTLD_NEXT,"pthread_create");
    if (!fn) return ENOSYS;
    uint32_t sequence=0;
    if (role==1) {
        struct control s; int fd=state_open(&s);
        if (fd>=0) { if (active(&s)) sequence=s.sequence; state_close(fd,NULL); }
    }
    if (!sequence) return fn(thread,attr,start,arg);
    struct cue_start *wrapped=malloc(sizeof(*wrapped));
    if (!wrapped) return EAGAIN;
    *wrapped=(struct cue_start){start,arg,sequence};
    int ret=fn(thread,attr,cue_thread,wrapped);
    if (ret) free(wrapped);
    return ret;
}
static int wake_cue_path(const char *path) {
    static const char *const paths[]={
        "/usr/share/sound/wakeup_wozai.wav",
        "/usr/share/sound/wakeup_ei_01.wav",
        "/usr/share/sound/wakeup_ei_02.wav",
        "/usr/share/sound/wakeup_zai_01.wav",
        "/usr/share/sound/wakeup_zai_02.wav"
    };
    for (unsigned i=0;i<sizeof(paths)/sizeof(paths[0]);i++)
        if (!strcmp(path,paths[i])) return 1;
    return 0;
}
FILE *fopen(const char *path,const char *mode) {
    FILE *(*fn)(const char *,const char *)=dlsym(RTLD_NEXT,"fopen");
    if (!fn) { errno=ENOSYS; return NULL; }
    FILE *file=fn(path,mode);
    if (file && role==1 && cue_sequence && !cue_file &&
        (!strcmp(mode,"r") || !strcmp(mode,"rb")) && wake_cue_path(path)) {
        char name[16]={0};
        if (!prctl(PR_GET_NAME,name,0,0,0) && !strcmp(name,"wakeup_tone_raw")) cue_file=file;
    }
    return file;
}
size_t fread(void *buffer,size_t size,size_t count,FILE *file) {
    size_t (*fn)(void *,size_t,size_t,FILE *)=dlsym(RTLD_NEXT,"fread");
    if (!fn) { errno=ENOSYS; return 0; }
    long offset=file==cue_file ? ftell(file) : -1;
    size_t got=fn(buffer,size,count,file);
    if (file==cue_file && offset>=0 && size && got<=SIZE_MAX/size) {
        size_t bytes=got*size;
        /* Verified firmware skips the 80-byte WAV header before fread. Also
         * preserve that header if a read happens to span the boundary. */
        size_t keep=offset<80 ? 80-(size_t)offset : 0;
        if (bytes>keep) {
            memset((unsigned char *)buffer+keep,0,bytes-keep);
            note("cue silenced seq=%u bytes=%zu",cue_sequence,bytes-keep);
        }
    }
    return got;
}
int fclose(FILE *file) {
    int (*fn)(FILE *)=dlsym(RTLD_NEXT,"fclose");
    if (file==cue_file) cue_file=NULL;
    if (!fn) { errno=ENOSYS; return EOF; }
    return fn(file);
}

static void wake_observed(void *ctx, unsigned code, float angle) {
    pthread_mutex_lock(&wake_lock);
    if (code == 1 && angle >= 0 && angle <= 360) last_angle = angle;
    wake_fn fn = original_wake;
    pthread_mutex_unlock(&wake_lock);
    /* Real wakewords yield the ASR-only lease to native NLP. Serialize with
     * software dispatch so the worker cannot wake again after this handoff. */
    pthread_mutex_lock(&wake_dispatch_lock);
    struct control s; int fd = state_open(&s);
    int handoff = fd >= 0 && (code & 255u) == 1 &&
        (active(&s) || (s.phase==COMPLETE && alive(s.owner) &&
                       (int32_t)(s.deadline-now_ms())>0));
    if (handoff) {
        s.phase=NATIVE_HANDOFF; memset(s.text,0,sizeof(s.text));
        state_close(fd,&s);
        /* Unblock wakeup.sh before the original callback starts native cues.
         * Audio/volume were already restored before opening this lease. */
        unlink(NATIVE_BUSY_FILE);
        note("physical wake handoff seq=%u",s.sequence);
    } else if (fd>=0) state_close(fd,NULL);
    if (fn) fn(ctx,code,angle);
    pthread_mutex_unlock(&wake_dispatch_lock);
}

void *xaudio_register_callback(void *engine, wake_fn callback, void *ctx) {
    void *(*fn)(void *,wake_fn,void *) = dlsym(RTLD_NEXT,"xaudio_register_callback");
    if (!fn) return NULL;
    pthread_mutex_lock(&wake_lock);
    original_wake=callback; wake_context=ctx;
    pthread_mutex_unlock(&wake_lock);
    return fn(engine,wake_observed,ctx);
}
int register_data_upload_callback(void *asr, ivw_fn ivw, void *ctx, unsigned mode, unsigned flag) {
    int (*fn)(void *,ivw_fn,void *,unsigned,unsigned) = dlsym(RTLD_NEXT,"register_data_upload_callback");
    pthread_mutex_lock(&wake_lock); original_ivw=ivw; pthread_mutex_unlock(&wake_lock);
    return fn ? fn(asr,ivw,ctx,mode,flag) : -1;
}

size_t speech_message__pack(const void *message, void *out) {
    size_t (*fn)(const void *,void *)=dlsym(RTLD_NEXT,"speech_message__pack");
    if (!fn) return 0;
    const uint32_t *top=message;
    if (role==1 && top && top[3]==0 && top[4]) {
        const uint32_t *up=(const void *)(uintptr_t)top[4];
        if (up[3]==1 && up[5]) {
            struct control s; int fd=state_open(&s);
            if (fd>=0 && active(&s) && s.phase==TRIGGERED && alive(s.aivs_pid)) {
                /* Sizes come from the verified protobuf-c descriptors. Copies
                 * avoid mutating the native object while another thread reads it. */
                uint32_t t[6], u[9], p[6];
                memcpy(t,top,sizeof(t)); memcpy(u,up,sizeof(u));
                memcpy(p,(const void *)(uintptr_t)up[5],sizeof(p));
                p[3]=1; /* activate_mode = NONWAKEUP */
                u[5]=(uint32_t)(uintptr_t)p; t[4]=(uint32_t)(uintptr_t)u;
                size_t n=fn(t,out);
                s.packet_hash=packet_hash(out,n); s.packet_size=(uint32_t)n; s.phase=PREPARED;
                state_close(fd,&s); note("prepare seq=%u NONWAKEUP bytes=%zu",s.sequence,n); return n;
            }
            if (fd>=0) state_close(fd,NULL);
        }
    }
    return fn(message,out);
}

void *speech_message__unpack(void *allocator, size_t len, const void *data) {
    void *(*fn)(void *,size_t,const void *)=dlsym(RTLD_NEXT,"speech_message__unpack");
    void *msg=fn ? fn(allocator,len,data) : NULL;
    if (role==2 && msg) {
        struct control s; int fd=state_open(&s);
        if (fd>=0) {
            if ((s.phase==PREPARED || s.phase==FAILED || s.phase==NATIVE_HANDOFF) && (int32_t)(s.deadline-now_ms()) > -3000 &&
                s.packet_size==len && s.packet_hash==packet_hash(data,len)) {
                prepare_scope=s.sequence; prepare_message=msg;
                note("prepare received seq=%u",s.sequence);
            }
            state_close(fd,NULL);
        }
    }
    return msg;
}
void speech_message__free_unpacked(void *msg, void *allocator) {
    void (*fn)(void *,void *)=dlsym(RTLD_NEXT,"speech_message__free_unpacked");
    if (msg==prepare_message) { prepare_scope=0; prepare_message=NULL; }
    if (fn) fn(msg,allocator);
}

/* Use the firmware's exported JsonCpp operations; do not link another C++
 * runtime. Json::Value is 24 bytes in this ABI; reserve 64 with 8-byte alignment.
 * Every call takes a pointer/reference, so no C++ value-return ABI is assumed. */
typedef union { uint64_t align; unsigned char bytes[64]; } json_value;
static void (*j_ctor)(void *,int), (*j_string)(void *,const char *), (*j_dtor)(void *), (*j_swap)(void *,void *);
static void *(*j_member)(void *,const char *), *(*j_const)(const void *,const char *), *(*j_index)(const void *,unsigned);
static const char *(*j_cstr)(const void *);
static int (*j_type)(const void *), (*j_bool)(const void *);
static unsigned (*j_size)(const void *);
static void *(*j_append)(void *,const void *);
static int json_ready;

static const char *str_value(const void *v) { return v && j_type(v)==4 ? j_cstr(v) : ""; }
static const void *member(const void *v,const char *k) { return v && j_type(v)==7 ? j_const(v,k) : NULL; }
static const char *string_member(const void *v,const char *k) { return str_value(member(v,k)); }
static void put_string(void *v,const char *key,const char *value) {
    json_value tmp; j_string(&tmp,value); j_swap(j_member(v,key),&tmp); j_dtor(&tmp);
}
static void set_disabled(void *target) {
    json_value disabled, item; j_ctor(&disabled,6);
    j_string(&item,"NLP"); j_append(&disabled,&item); j_dtor(&item);
    j_string(&item,"TTS"); j_append(&disabled,&item); j_dtor(&item);
    j_swap(j_member(j_member(target,"payload"),"disabled"),&disabled); j_dtor(&disabled);
}
static int asr_only(void *event) {
    void *contexts=j_member(event,"context");
    if (j_type(contexts)!=6) return 0;
    unsigned size=j_size(contexts);
    if (size>128) return 0;
    int found=0;
    for (unsigned i=0;i<size;i++) {
        void *c=j_index(contexts,i); const void *h=member(c,"header");
        if (!strcmp(string_member(h,"namespace"),"Execution") && !strcmp(string_member(h,"name"),"RequestControl")) {
            set_disabled(c); found=1;
        }
    }
    if (!found) {
        json_value extra; j_ctor(&extra,7);
        void *h=j_member(&extra,"header");
        put_string(h,"namespace","Execution"); put_string(h,"name","RequestControl");
        set_disabled(&extra); j_append(contexts,&extra); j_dtor(&extra);
    }
    return 1;
}

/* A small tombstone set keeps late/retried events scoped after cancellation.
 * Entries hold dialog IDs only, never audio/text. Access is mutex protected. */
static char dialogs[64][80]; static unsigned dialog_cursor;
static pthread_mutex_t dialog_lock=PTHREAD_MUTEX_INITIALIZER;
static int tracked(const char *id) {
    if (!id || !*id) return 0;
    int found=0; pthread_mutex_lock(&dialog_lock);
    for (unsigned i=0;i<64;i++) if (!strcmp(id,dialogs[i])) { found=1; break; }
    pthread_mutex_unlock(&dialog_lock); return found;
}
static void remember(const char *id) {
    pthread_mutex_lock(&dialog_lock);
    snprintf(dialogs[dialog_cursor++ % 64],80,"%s",id);
    pthread_mutex_unlock(&dialog_lock);
}

int event_to_json(const void *event,void *json) __asm__("_ZNK4aivs5Event6toJsonERN4Json5ValueE");
int event_to_json(const void *event,void *json) {
    int (*fn)(const void *,void *)=dlsym(RTLD_NEXT,"_ZNK4aivs5Event6toJsonERN4Json5ValueE");
    int ok=fn ? fn(event,json) : 0;
    if (!ok || role!=2 || !json_ready) return ok;
    const void *h=member(json,"header");
    if (strcmp(string_member(h,"namespace"),"SpeechRecognizer") || strcmp(string_member(h,"name"),"Recognize")) return ok;
    const char *id=string_member(h,"id"); int own=tracked(id);
    struct control s; int fd=state_open(&s);
    if (fd>=0) {
        if (!own && *id && strlen(id)<sizeof(s.dialog) && active(&s) && s.phase==PREPARED && prepare_scope==s.sequence) {
            snprintf(s.dialog,sizeof(s.dialog),"%s",id); s.phase=BOUND;
            remember(id); own=1;
            state_close(fd,&s); note("bound seq=%u dialog=%s",s.sequence,id);
        } else state_close(fd,NULL);
    }
    /* Cancellation may land between unpack and serialization. It must not
     * turn a software wake into an ordinary NLP/TTS request. Keep ASR-only even
     * though no cancelled result can be delivered to the client. */
    if (prepare_scope && !own) {
        if (!*id || strlen(id)>=sizeof(s.dialog)) return 0;
        remember(id); own=1;
    }
    if (own) {
        if (!asr_only(json)) { note("ASR-only context failed; refuse event dialog=%s",id); return 0; }
        note("ASR-only dialog=%s disabled=NLP,TTS",id);
    }
    return ok;
}

static int receive_json(int ok,void *json) {
    if (!ok || role!=2 || !json_ready) return ok;
    const void *h=member(json,"header"); const char *id=string_member(h,"dialog_id");
    if (!tracked(id)) return ok;
    const char *ns=string_member(h,"namespace"), *name=string_member(h,"name");
    int result=!strcmp(ns,"SpeechRecognizer") && !strcmp(name,"RecognizeResult");
    int finish=!strcmp(ns,"Dialog") && !strcmp(name,"Finish");
    int permitted=result || finish || (!strcmp(ns,"SpeechRecognizer") &&
        (!strcmp(name,"StopCapture") || !strcmp(name,"RecognizeStreamFinished"))) ||
        (!strcmp(ns,"System") && (!strcmp(name,"Exception") || !strcmp(name,"Abort") || !strcmp(name,"TruncationNotification")));
    if (!permitted) { note("blocked followup instruction %s.%s dialog=%s",ns,name,id); return 0; }
    struct control s; int fd=state_open(&s);
    if (fd>=0) {
        /* Finish is parsed more than once by this firmware. The first parse
         * publishes COMPLETE; the CLI may consume it before the SDK's parse.
         * Keep this same, normally completed dialog's terminal bookkeeping
         * deliverable so TimeoutManager does not wait for disabled TTS.
         * Handoff/cancelled/superseded dialogs must still be isolated. */
        if (finish && s.finished && s.final_seen && !strcmp(s.dialog,id) &&
            (s.phase==COMPLETE || s.phase==IDLE)) {
            state_close(fd,NULL);
            note("finish replay permitted dialog=%s",id);
            return ok;
        }
        if (active(&s) && !strcmp(s.dialog,id)) {
            const void *payload=member(json,"payload"), *final=member(payload,"is_final");
            if (result && final && j_type(final)==5 && j_bool(final)) {
                const void *results=member(payload,"results");
                if (results && j_type(results)==6 && j_size(results)>0) {
                    const char *value=string_member(j_index(results,0),"text");
                    if (strlen(value)<sizeof(s.text)) {
                        snprintf(s.text,sizeof(s.text),"%s",value); s.final_seen=1; s.phase=RESULT;
                        note("final seq=%u bytes=%zu",s.sequence,strlen(value));
                    } else s.phase=FAILED;
                }
            }
            if (finish) { s.finished=1; note("finish seq=%u",s.sequence); }
            if (s.finished && s.final_seen) s.phase=COMPLETE;
            state_close(fd,&s);
        } else {
            /* Late StopCapture/Finish from the cancelled followup must not
             * stop or finish the new physical wake's native conversation. */
            state_close(fd,NULL); return 0;
        }
    } else {
        return 0;
    }
    return ok;
}

int reader_parse(void *reader,const char *start,const char *end,void *json,int comments)
    __asm__("_ZN4Json9OurReader5parseEPKcS2_RNS_5ValueEb");
int reader_parse(void *reader,const char *start,const char *end,void *json,int comments) {
    int (*fn)(void *,const char *,const char *,void *,int)=dlsym(RTLD_NEXT,"_ZN4Json9OurReader5parseEPKcS2_RNS_5ValueEb");
    return receive_json(fn ? fn(reader,start,end,json,comments) : 0,json);
}

static void *worker(void *arg) {
    (void)arg;
    for (;;) {
        usleep(20000);
        pthread_mutex_lock(&wake_lock);
        wake_fn wake=original_wake; ivw_fn ivw=original_ivw; void *ctx=wake_context; float angle=last_angle;
        pthread_mutex_unlock(&wake_lock);
        pthread_mutex_lock(&wake_dispatch_lock);
        struct control s; int fd=state_open(&s);
        if (fd<0) { pthread_mutex_unlock(&wake_dispatch_lock); continue; }
        int changed=wake && ivw && ctx && s.mipns_pid!=(uint32_t)getpid();
        if (changed) s.mipns_pid=(uint32_t)getpid();
        if (s.phase!=REQUEST || !active(&s)) { state_close(fd,changed?&s:NULL); pthread_mutex_unlock(&wake_dispatch_lock); continue; }
        if (!wake || !ivw || !ctx || !alive(s.aivs_pid) || access("/tmp/mipns/mute",F_OK)==0 || access("/tmp/native_first_busy",F_OK)) {
            s.phase=FAILED; state_close(fd,&s); pthread_mutex_unlock(&wake_dispatch_lock); continue;
        }
        s.phase=TRIGGERED; state_close(fd,&s);
        note("trigger seq=%u angle=%.1f",s.sequence,(double)angle);
        wake(ctx,1,angle);
        /* Complete local wakeword buffering without fabricating any audio. */
        uint32_t until=now_ms()+300;
        while ((int32_t)(until-now_ms())>0) usleep(10000);
        struct control current; fd=state_open(&current);
        int continue_capture=fd>=0 && active(&current) && current.sequence==s.sequence;
        if (fd>=0) state_close(fd,NULL);
        if (continue_capture) {
            unsigned char empty[1]={0}; ivw(1,empty,0,0,0);
            note("IVW complete seq=%u len=0",s.sequence);
        }
        /* Keep the short software startup and IVW completion before a queued
         * physical wake; neither may land inside the new native capture. */
        pthread_mutex_unlock(&wake_dispatch_lock);
    }
    return NULL;
}

static int resolve_json(void) {
#define LOAD(var,name) do { *(void **)(&var)=dlsym(RTLD_NEXT,name); if (!var) return 0; } while(0)
        LOAD(j_ctor,"_ZN4Json5ValueC1ENS_9ValueTypeE"); LOAD(j_string,"_ZN4Json5ValueC1EPKc");
        LOAD(j_dtor,"_ZN4Json5ValueD1Ev"); LOAD(j_swap,"_ZN4Json5Value4swapERS0_");
        LOAD(j_member,"_ZN4Json5ValueixEPKc"); LOAD(j_const,"_ZNK4Json5ValueixEPKc");
        LOAD(j_index,"_ZNK4Json5ValueixEj"); LOAD(j_cstr,"_ZNK4Json5Value9asCStringEv");
        LOAD(j_type,"_ZNK4Json5Value4typeEv"); LOAD(j_bool,"_ZNK4Json5Value6asBoolEv");
        LOAD(j_size,"_ZNK4Json5Value4sizeEv"); LOAD(j_append,"_ZN4Json5Value6appendERKS0_");
#undef LOAD
    return 1;
}

__attribute__((constructor)) static void initialize(void) {
    char exe[256]; ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
    if (n<0) return; exe[n]=0;
    if (!strcmp(exe,"/usr/bin/mipns-xiaomi")) role=1;
    else if (!strcmp(exe,"/usr/bin/mico_aivs_lab")) role=2;
    else return;
    unsetenv("LD_PRELOAD");
    if (role==2) {
        if (!resolve_json()) return;
        json_ready=1;
        struct control s; int fd=state_open(&s);
        if (fd>=0) { s.aivs_pid=(uint32_t)getpid(); state_close(fd,&s); }
    } else {
        pthread_t thread; if (!pthread_create(&thread,NULL,worker,NULL)) pthread_detach(thread);
    }
    note("ready role=%d",role);
}
