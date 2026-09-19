/* Physical-wake experiment. Modes 1/2 require fresh native processes; mode 3
 * binds each turn with a random IPC marker and allows explicit rearming. */
#define _GNU_SOURCE
#define NATIVE_EVENT_LOG_LIMIT (1024 * 1024)
#include <dlfcn.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <stddef.h>
#include <errno.h>
#ifndef NATIVE_WAKE_DESTINATION
#define NATIVE_WAKE_DESTINATION "/tmp/mico_aivs_lab/usock/speech.usock"
#endif
static void *first_lookup(void *,const char *);
static void first_instruction(void *);
#define NATIVE_ASR_ON_INSTRUCTION first_instruction
#define dlsym first_lookup
#define speech_message__pack base_pack
#define speech_message__unpack base_unpack
#define speech_message__free_unpacked base_free
#include "../native_asr/native_asr.c"
#undef dlsym
#undef speech_message__pack
#undef speech_message__unpack
#undef speech_message__free_unpacked
#include "native_wake_state.h"
#include "first_endpoint.h"
#include "native_pool.h"
static wake_fn first_chained;
static __thread void *first_message;
static __thread uint32_t first_owner,first_deadline,first_nonce;
static __thread const void *first_wire_buffer;
static __thread size_t first_wire_size;
static __thread unsigned char first_wire_raw[256],first_wire_tag[NW_TAG_BYTES];
/* Legacy modes 1/2 are restricted to the FIRST normal wake and FIRST prepare since
 * both native processes were restarted for this experiment. Identical late
 * packets from an earlier turn cannot acquire this one-shot capability.
 * Mode 3 replaces this restriction with an exact per-generation wire token. */
static uint32_t first_normal_wakes,first_prepare_sent,first_prepare_received;

static void first_wake(void *ctx,unsigned code,float angle) {
    pthread_mutex_lock(&first_lock);
    if(code==1){first_close(0);first_normal_wakes++;}
    if((code&255u)==1) {
        struct nw_state s;int fd=nw_open(&s);
        if(fd>=0){
            if(code==1 && s.phase!=NW_ARMED){
                int promoted=np_advance(&s,NP_RETIRED_REPLACED);
                if(promoted)note("FIRST_POOL_WAKE_HANDOFF result=%d nonce=%u",promoted,s.nonce);
            }
            if(code==1 && s.phase==NW_ARMED){
                s.wake_ms=now_ms();
                if(s.mode==1 || s.mode==2 || s.mode==3)s.prepared=
                    ((s.mode==3 && nw_tag_valid(s.tag)) || (first_normal_wakes==1 &&
                    !__atomic_load_n(&first_prepare_sent,__ATOMIC_ACQUIRE))) && first_claim(&s);
                if(s.mode && !s.prepared){s.mode=0;note("FIRST_ENDPOINT bypass model-or-callback-not-ready");}
            }
            nw_event(&s,(uint32_t)getpid(),code);nw_close(fd,&s);
            note("NATIVE_WAKE observe owner=%u phase=%u code=%u angle=%.1f",s.owner,s.phase,code,(double)angle);
        }
    }
    if(first_chained)first_chained(ctx,code,angle);
    pthread_mutex_unlock(&first_lock);
}
static void *first_register(void *engine,wake_fn callback,void *ctx) {
    void *(*fn)(void *,wake_fn,void *)=dlsym(RTLD_NEXT,"xaudio_register_callback");
    first_chained=callback;return fn?fn(engine,first_wake,ctx):NULL;
}
size_t speech_message__pack(const void *message,uint8_t *out) {
    first_wire_buffer=NULL;first_wire_size=0;
    size_t n=base_pack(message,out);
    const uint32_t *top=message;
    if(role==1 && top && top[3]==0 && top[4]) {
        const uint32_t *up=(const void *)(uintptr_t)top[4];
        if(up[3]==1 && up[5]) {
            uint32_t ordinal=__atomic_add_fetch(&first_prepare_sent,1,__ATOMIC_ACQ_REL);
            __atomic_store_n(&first_local_owned,0,__ATOMIC_RELEASE);
            struct nw_state s;int fd=nw_open(&s);
            if(fd>=0){
                int ok=(!s.mode || s.mode==3 || ordinal==1) && nw_packet(&s,(uint32_t)getpid(),out,n);
                if(ok){
                    s.packet_ms=now_ms();
                    if(s.mode==3 && s.prepared && nw_tag_valid(s.tag)){
                        first_wire_buffer=out;first_wire_size=n;
                        memcpy(first_wire_raw,out,n);memcpy(first_wire_tag,s.tag,NW_TAG_BYTES);
                    }
                }
                else if(s.mode)s.phase=NW_CANCELLED;
                nw_close(fd,(ok || s.mode)?&s:NULL);
                if(ok)note("NATIVE_WAKE packet owner=%u bytes=%zu",s.owner,n);
            }
        }
    }
    return n;
}
/* The verified mipns prepare path packs then synchronously calls sendto on
 * this thread. Never extend the caller's unknown-capacity packing buffer. */
ssize_t sendto(int socket,const void *buffer,size_t length,int flags,
               const struct sockaddr *address,socklen_t address_length) {
    ssize_t (*fn)(int,const void *,size_t,int,const struct sockaddr *,socklen_t)=dlsym(RTLD_NEXT,"sendto");
    if(!fn){errno=ENOSYS;return -1;}
    static const char destination[]=NATIVE_WAKE_DESTINATION;
    const struct sockaddr_un *un=(const struct sockaddr_un *)address;
    int match=role==1 && buffer==first_wire_buffer && length && length==first_wire_size &&
        length<=sizeof(first_wire_raw) && !memcmp(buffer,first_wire_raw,length) &&
        address && address_length>=offsetof(struct sockaddr_un,sun_path)+sizeof(destination) &&
        un->sun_family==AF_UNIX && !memcmp(un->sun_path,destination,sizeof(destination));
    if(!match)return fn(socket,buffer,length,flags,address,address_length);
    unsigned char wire[256+NW_TAG_OVERHEAD];size_t tagged=0;
    struct nw_state s;int fd=nw_open(&s);
    if(fd>=0){
        if(s.mode==3 && s.prepared && s.producer==(uint32_t)getpid() &&
           nw_matches(&s,buffer,length) && !memcmp(s.tag,first_wire_tag,NW_TAG_BYTES))
            tagged=nw_tag_append(wire,sizeof(wire),buffer,length,first_wire_tag);
        nw_close(fd,NULL);
    }
    if(!tagged)return fn(socket,buffer,length,flags,address,address_length);
    ssize_t result=fn(socket,wire,tagged,flags,address,address_length);
    if(result==(ssize_t)tagged){first_wire_buffer=NULL;return (ssize_t)length;}
    if(result>=0){errno=EIO;return -1;} /* Unix datagrams must be atomic. */
    return result;
}
void *speech_message__unpack(void *allocator,size_t len,const void *data) {
    unsigned char tag[NW_TAG_BYTES];size_t raw_size=role==2?nw_tag_extract(data,len,tag):0;
    void *msg=base_unpack(allocator,raw_size?raw_size:len,data);
    if(role==2 && msg) {
        const uint32_t *top=msg;
        int prepare=top[3]==0 && top[4] && ((const uint32_t *)(uintptr_t)top[4])[3]==1;
        uint32_t ordinal=prepare?__atomic_add_fetch(&first_prepare_received,1,__ATOMIC_ACQ_REL):0;
        /* Never let an unrelated later unpack inherit correlation. */
        first_message=NULL;first_owner=first_deadline=first_nonce=0;
        struct nw_state s;int fd=nw_open(&s);
        if(fd>=0){
            int matched=s.mode==3 ? prepare && raw_size && !s.accepted &&
                !memcmp(s.tag,tag,NW_TAG_BYTES) && nw_matches(&s,data,raw_size) :
                (!s.mode || ordinal==1) && nw_matches(&s,data,len);
            if(matched && (uint32_t)(now_ms()-s.packet_ms)<=500){
                first_message=msg;first_owner=s.owner;first_deadline=s.deadline;first_nonce=s.nonce;
                if(s.mode==3)s.accepted=1;
                note("NATIVE_WAKE received owner=%u bytes=%zu",s.owner,len);
            }else if(s.mode==3 && prepare && s.phase>=NW_WAKE){
                /* A mismatched or duplicate prepare may change native capture.
                 * Forward it normally, but revoke all endpoint authority. */
                s.phase=NW_CANCELLED;
            }
            nw_close(fd,s.mode==3?&s:NULL);
        }
    }
    return msg;
}
void speech_message__free_unpacked(void *msg,void *allocator) {
    if(msg==first_message){first_message=NULL;first_owner=first_deadline=first_nonce=0;}
    base_free(msg,allocator);
}
static int first_scoped(const struct nw_state *s){
    return first_message && s->owner==first_owner && s->deadline==first_deadline && s->nonce==first_nonce;
}
static int first_serialize(const void *event,void *json) {
    int (*fn)(const void *,void *)=dlsym(RTLD_NEXT,"_ZNK4aivs5Event6toJsonERN4Json5ValueE");
    int ok=fn?fn(event,json):0;
    if(!ok || role!=2 || !json_ready)return ok;
    const void *h=member(json,"header");
    const char *ns=string_member(h,"namespace"),*name=string_member(h,"name");
    int wake=!strcmp(ns,"SpeechWakeup") && !strcmp(name,"Wakeup");
    int recognize=!strcmp(ns,"SpeechRecognizer") && !strcmp(name,"Recognize");
    if(!wake && !recognize)return ok;
    const char *id=string_member(h,"id");
    struct nw_state s;int fd=nw_open(&s);
    if(fd>=0){
        int scoped=first_scoped(&s);
        note("NATIVE_WAKE serialize owner=%u event=%s scope=%d phase=%u dialog=%s mode=%u",
            s.owner,name,scoped,s.phase,id,s.mode);
        int changed=0;
        if(alive(s.producer)) {
            if(wake && scoped && !strcmp(string_member(member(member(json,"payload"),"wakeup_info"),"type"),"wakeup_real")){
                changed=nw_dialog(&s,(uint32_t)getpid(),id);
                if(changed && !first_modify_wakeup(json,&s)){s.mode=0;note("FIRST_ENDPOINT bypass wakeup-not-ready");}
            }
            if(recognize){
                changed=nw_bound(&s,(uint32_t)getpid(),id);
                if(changed && s.mode && !first_modify(json,&s)){
                    s.mode=0;note("FIRST_ENDPOINT bypass request-not-ready");
                }else if(!changed && s.mode && strcmp(s.dialog,id)){
                    s.phase=NW_CANCELLED;changed=1;
                }
            }
        }
        nw_close(fd,changed?&s:NULL);
        if(changed)note("NATIVE_WAKE correlated owner=%u phase=%u dialog=%s mode=%u",s.owner,s.phase,id,s.mode);
    }
    return ok; /* Mode 0 unchanged. Both endpoint modes retain NLP/TTS context. */
}
static void *first_lookup(void *handle,const char *name) {
    if(!strcmp(name,"xaudio_register_callback"))return (void *)first_register;
    if(!strcmp(name,"_ZNK4aivs5Event6toJsonERN4Json5ValueE"))return (void *)first_serialize;
    if(!strcmp(name,"register_data_upload_callback"))return (void *)first_register_upload;
    return dlsym(handle,name);
}
