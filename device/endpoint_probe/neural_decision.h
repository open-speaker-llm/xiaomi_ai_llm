#ifndef NEURAL_DECISION_H
#define NEURAL_DECISION_H
#include "neural_stream.h"
#define ND_MAGIC 0x4e445631u
/* Reserved outside the possible frame range; never a quiet speech segment. */
#define ND_NO_SPEECH UINT32_MAX
#define ND_START_FRAMES 600u
/* Separate mapping: observer writes proposals, native controller reads them.
 * The audio/lease mapping remains read-only in the observer. */
struct neural_decision {
    uint32_t magic,version,sequence,owner,observer;
    uint32_t generation,producer,consumed,candidate,observed_ms,invalid;
};
struct neural_proposal {uint32_t producer,consumed,candidate,observed_ms,invalid;};
static inline int nd_identity(const struct neural_decision *d,uint32_t seq,uint32_t owner,uint32_t observer){
    return __atomic_load_n(&d->magic,__ATOMIC_ACQUIRE)==ND_MAGIC && d->version==1 &&
        d->sequence==seq && d->owner==owner && d->observer==observer;
}
static inline void nd_init(struct neural_decision *d,uint32_t seq,uint32_t owner,uint32_t observer){
    memset(d,0,sizeof(*d));d->version=1;d->sequence=seq;d->owner=owner;d->observer=observer;
    __atomic_store_n(&d->magic,ND_MAGIC,__ATOMIC_RELEASE);
}
static inline void nd_publish(struct neural_decision *d,struct neural_proposal p){
    uint32_t g=__atomic_load_n(&d->generation,__ATOMIC_RELAXED);
    __atomic_store_n(&d->generation,g+1,__ATOMIC_SEQ_CST);
    __atomic_store_n(&d->producer,p.producer,__ATOMIC_RELAXED);
    __atomic_store_n(&d->consumed,p.consumed,__ATOMIC_RELAXED);
    __atomic_store_n(&d->candidate,p.candidate,__ATOMIC_RELAXED);
    __atomic_store_n(&d->observed_ms,p.observed_ms,__ATOMIC_RELAXED);
    __atomic_store_n(&d->invalid,p.invalid,__ATOMIC_RELAXED);
    __atomic_store_n(&d->generation,g+2,__ATOMIC_RELEASE);
}
static inline int nd_read(const struct neural_decision *d,struct neural_proposal *p){
    uint32_t g=__atomic_load_n(&d->generation,__ATOMIC_ACQUIRE);if(g&1)return 0;
    p->producer=__atomic_load_n(&d->producer,__ATOMIC_RELAXED);
    p->consumed=__atomic_load_n(&d->consumed,__ATOMIC_RELAXED);
    p->candidate=__atomic_load_n(&d->candidate,__ATOMIC_RELAXED);
    p->observed_ms=__atomic_load_n(&d->observed_ms,__ATOMIC_RELAXED);
    p->invalid=__atomic_load_n(&d->invalid,__ATOMIC_RELAXED);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return g==__atomic_load_n(&d->generation,__ATOMIC_ACQUIRE);
}
static inline int nd_end_due(const struct neural_stream *s,const struct neural_decision *d,
                         uint32_t seq,uint32_t owner,uint32_t producer,uint32_t now,int empty){
    struct neural_proposal p;
    if(!s || !d || !ns_identity(s,seq,owner) ||
       __atomic_load_n(&s->state,__ATOMIC_ACQUIRE)!=NS_LIVE || s->producer!=producer ||
       !nd_identity(d,seq,owner,s->observer) || !nd_read(d,&p))return 0;
    uint32_t used=__atomic_load_n(&s->used,__ATOMIC_ACQUIRE);
    return used<=NS_BYTES && used%320==0 && !p.invalid && p.producer==producer &&
        p.consumed==used/320 && (uint32_t)(now-p.observed_ms)<=150 &&
        (empty ? p.candidate==ND_NO_SPEECH && p.consumed>=ND_START_FRAMES :
                 p.candidate && p.candidate<=p.consumed);
}
static inline int nd_due(const struct neural_stream *s,const struct neural_decision *d,
                         uint32_t seq,uint32_t owner,uint32_t producer,uint32_t now){
    return nd_end_due(s,d,seq,owner,producer,now,0);
}
static inline int nd_no_speech_due(const struct neural_stream *s,const struct neural_decision *d,
                         uint32_t seq,uint32_t owner,uint32_t producer,uint32_t now){
    return nd_end_due(s,d,seq,owner,producer,now,1);
}
#endif
