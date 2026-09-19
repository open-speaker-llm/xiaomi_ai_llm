#ifndef NEURAL_STREAM_H
#define NEURAL_STREAM_H
#include <stdint.h>
#include <string.h>
#define NS_MAGIC 0x4e535631u
#define NS_BYTES (2400u * 320u)
enum ns_state { NS_WAIT, NS_LIVE, NS_DONE, NS_INVALID };
/* Linear, write-once audio. Release/acquire publication avoids partial reads;
 * no wraparound, waiting, model inference or I/O on the producer callback. */
struct neural_stream {
    uint32_t magic, version, sequence, owner, observer, producer;
    uint32_t state, used;
    unsigned char pcm[NS_BYTES];
};
static inline int ns_identity(const struct neural_stream *s,uint32_t seq,uint32_t owner) {
    return __atomic_load_n(&s->magic,__ATOMIC_ACQUIRE)==NS_MAGIC && s->version==1 &&
        seq && owner>1 && s->sequence==seq && s->owner==owner && s->observer>1;
}
static inline void ns_init(struct neural_stream *s,uint32_t seq,uint32_t owner,uint32_t observer) {
    memset(s,0,sizeof(*s));s->version=1;s->sequence=seq;s->owner=owner;s->observer=observer;
    __atomic_store_n(&s->magic,NS_MAGIC,__ATOMIC_RELEASE);
}
static inline int ns_claim(struct neural_stream *s,uint32_t seq,uint32_t owner,uint32_t producer) {
    if(!ns_identity(s,seq,owner) || producer<=1 || s->producer || s->used ||
       __atomic_load_n(&s->state,__ATOMIC_ACQUIRE)!=NS_WAIT)return 0;
    s->producer=producer;
    __atomic_store_n(&s->state,NS_LIVE,__ATOMIC_RELEASE);return 1;
}
static inline void ns_close(struct neural_stream *s,int valid) {
    __atomic_store_n(&s->state,valid?NS_DONE:NS_INVALID,__ATOMIC_RELEASE);
}
static inline int ns_append(struct neural_stream *s,const void *pcm,unsigned bytes) {
    if(__atomic_load_n(&s->state,__ATOMIC_ACQUIRE)!=NS_LIVE)return 0;
    if(!bytes || bytes%320 || s->used>NS_BYTES){ns_close(s,0);return 0;}
    unsigned n=NS_BYTES-s->used;if(n>bytes)n=bytes;
    memcpy(s->pcm+s->used,pcm,n);
    __atomic_store_n(&s->used,s->used+n,__ATOMIC_RELEASE);return 1;
}
#endif
