/* One-shot experimental state; mode 0 is metadata-only observation. */
#ifndef NATIVE_WAKE_STATE_H
#define NATIVE_WAKE_STATE_H
#include "../native_asr/control.h"
#include "native_wake_tag.h"
#define NW_MAGIC 0x4e573033u
#ifndef NW_DIR
#define NW_DIR "/tmp/xiaomi_native_wake_probe"
#endif
#ifndef NW_FILE
#define NW_FILE NW_DIR "/native-wake.state"
#endif
enum nw_phase { NW_ARMED, NW_WAKE, NW_PACKET, NW_DIALOG, NW_BOUND, NW_CANCELLED };
/* Cancellation by a new physical wake, without sending a local EOF. */
#define NW_END_REPLACED 4u
#define NW_END_NO_SPEECH 5u
struct nw_state {
    uint32_t magic, owner, deadline, phase, producer, consumer, packet_size;
    unsigned char packet[256];
    char dialog[80];
    uint32_t mode, nonce, observer, expected_producer, expected_consumer;
    uint32_t wake_ms, packet_ms, prepared, modified, ended, failed;
    uint32_t final_seen, finished, frames, end_reason, wake_modified;
    unsigned char tag[NW_TAG_BYTES];
    uint32_t accepted;
};
static inline int nw_live(const struct nw_state *s) {
    return s->magic==NW_MAGIC && alive(s->owner) &&
        (int32_t)(s->deadline-now_ms())>0 && s->phase<NW_CANCELLED;
}
static inline int nw_open(struct nw_state *s) {
    int fd=open(NW_FILE,O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    struct stat st;
    if(fd<0)return -1;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || st.st_size!=sizeof(*s) || flock(fd,LOCK_EX) ||
       pread(fd,s,sizeof(*s),0)!=sizeof(*s) || !nw_live(s)) {
        close(fd);return -1;
    }
    return fd;
}
static inline void nw_close(int fd,const struct nw_state *s) {
    if(s)(void)pwrite(fd,s,sizeof(*s),0);
    close(fd);
}
/* Idle-only renewal: never lengthen a request after a wake/prepare/audio. */
static inline int nw_renew_idle(struct nw_state *s,uint32_t owner,uint32_t now){
    if(!nw_live(s) || s->owner!=owner || s->mode!=3 || s->phase!=NW_ARMED ||
       !s->nonce || !nw_tag_valid(s->tag) || s->prepared || s->wake_ms ||
       s->producer || s->consumer || s->packet_size || s->accepted || s->wake_modified ||
       s->modified || s->frames || s->ended ||
       s->final_seen || s->finished || s->failed || !alive(s->observer) ||
       !alive(s->expected_producer) || !alive(s->expected_consumer))return 0;
    s->deadline=now+90000;return 1;
}
static inline void nw_wake(struct nw_state *s,uint32_t producer) {
    if(s->phase==NW_ARMED && producer>1){s->phase=NW_WAKE;s->producer=producer;}
    else {s->phase=NW_CANCELLED;s->end_reason=NW_END_REPLACED;memset(s->dialog,0,sizeof(s->dialog));}
}
/* Observation identity uses the verified NORMAL wake (0x1). Suspect 0x101
 * remains forwarded and logged, but is not evidence of a second real dialog.
 * This rule grants no actuator permission for suspect events. */
static inline void nw_event(struct nw_state *s,uint32_t producer,unsigned code) {
    if(code==1)nw_wake(s,producer);
}
static inline int nw_packet(struct nw_state *s,uint32_t producer,const void *p,size_t n) {
    if(s->phase!=NW_WAKE || producer!=s->producer || !p || !n || n>sizeof(s->packet))return 0;
    memcpy(s->packet,p,n);s->packet_size=(uint32_t)n;s->phase=NW_PACKET;return 1;
}
static inline int nw_matches(const struct nw_state *s,const void *p,size_t n) {
    return s->phase==NW_PACKET && p && n && n==s->packet_size &&
        n<=sizeof(s->packet) && !memcmp(s->packet,p,n);
}
static inline int nw_dialog(struct nw_state *s,uint32_t consumer,const char *id) {
    if(s->phase!=NW_PACKET || consumer<=1 || !id || !*id || strlen(id)>=sizeof(s->dialog))return 0;
    s->consumer=consumer;snprintf(s->dialog,sizeof(s->dialog),"%s",id);s->phase=NW_DIALOG;return 1;
}
static inline int nw_bound(struct nw_state *s,uint32_t consumer,const char *id) {
    if(s->phase!=NW_DIALOG || consumer!=s->consumer || !id || strcmp(s->dialog,id))return 0;
    s->phase=NW_BOUND;return 1;
}
static inline int nw_endpoint_identity(const struct nw_state *s) {
    return nw_live(s) && (s->mode==1 || s->mode==2 || (s->mode==3 && s->accepted && nw_tag_valid(s->tag))) && s->nonce && s->observer>1 &&
        s->expected_producer>1 && s->expected_consumer>1 &&
        s->producer==s->expected_producer && s->consumer==s->expected_consumer &&
        s->prepared && s->phase==NW_BOUND && s->dialog[0];
}
static inline int nw_can_end(const struct nw_state *s,uint32_t producer) {
    return nw_endpoint_identity(s) && s->producer==producer && s->modified &&
        !s->ended && !s->final_seen && !s->finished && !s->failed;
}
static inline void nw_stream_path(char *path,size_t n,const struct nw_state *s) {
    snprintf(path,n,NW_DIR "/shadow.%u.%u.stream",s->nonce,s->owner);
}
#endif
