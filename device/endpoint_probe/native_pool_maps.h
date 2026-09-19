#ifndef NATIVE_POOL_MAPS_H
#define NATIVE_POOL_MAPS_H
#include "native_pool.h"
struct np_view {
    struct nw_state plan;
    struct neural_stream *stream;
    struct neural_decision *decision;
    struct neural_receipt *receipt;
};
static inline void np_view_close(struct np_view *v){
    if(v->stream)munmap(v->stream,sizeof(*v->stream));
    if(v->decision)munmap(v->decision,sizeof(*v->decision));
    if(v->receipt)munmap(v->receipt,sizeof(*v->receipt));
    memset(v,0,sizeof(*v));
}
static inline int np_view_identity(const struct np_view *v){
    return v->stream && v->decision && v->receipt && nq_identity(v->receipt,&v->plan) &&
        ns_identity(v->stream,v->plan.nonce,v->plan.owner) && v->stream->observer==v->plan.observer &&
        nd_identity(v->decision,v->plan.nonce,v->plan.owner,v->plan.observer);
}
/* Controller polls newly allocated mappings; never initializes or reuses them. */
static inline int np_view_open(struct np_view *v,const struct nw_state *plan){
    if(!np_same(&v->plan,plan)){np_view_close(v);v->plan=*plan;}
    char path[280];
    np_path(path,sizeof(path),plan,"");if(!v->stream)v->stream=np_map(path,sizeof(*v->stream),0,1);
    np_path(path,sizeof(path),plan,".decision");if(!v->decision)v->decision=np_map(path,sizeof(*v->decision),0,0);
    np_path(path,sizeof(path),plan,".receipt");if(!v->receipt)v->receipt=np_map(path,sizeof(*v->receipt),0,0);
    return np_view_identity(v) && v->stream->state==NS_WAIT && !v->stream->used && !v->stream->producer &&
        __atomic_load_n(&v->receipt->status,__ATOMIC_ACQUIRE)==NQ_WAIT;
}
/* Helper-only creation. Every generation gets new paths and new mmap objects. */
static inline int np_view_create(struct np_view *v,const struct nw_state *plan){
    np_view_close(v);v->plan=*plan;char path[280];
    np_path(path,sizeof(path),plan,"");v->stream=np_map(path,sizeof(*v->stream),1,1);if(!v->stream)return 0;
    ns_init(v->stream,plan->nonce,plan->owner,plan->observer);
    if(mprotect(v->stream,sizeof(*v->stream),PROT_READ))return 0;
    np_path(path,sizeof(path),plan,".decision");v->decision=np_map(path,sizeof(*v->decision),1,1);if(!v->decision)return 0;
    nd_init(v->decision,plan->nonce,plan->owner,plan->observer);
    np_path(path,sizeof(path),plan,".receipt");v->receipt=np_map(path,sizeof(*v->receipt),1,1);if(!v->receipt)return 0;
    nq_init(v->receipt,plan);return 1;
}
/* Only a terminal receipt permits replacing the helper's own old mapping.
 * The controller publishes its old snapshot before asking for a replacement. */
static inline int np_refresh_views(struct np_view views[NP_MAX],const struct np_pool *p){
    for(unsigned i=0;i<p->count;i++){
        struct np_view *v=&views[i];const struct np_slot *slot=&p->slot[i];
        if(np_same(&v->plan,&slot->plan))continue;
        if(!slot->recycling || !np_same(&v->plan,&slot->retired) || !np_view_identity(v) ||
           __atomic_load_n(&v->receipt->status,__ATOMIC_ACQUIRE)==NQ_WAIT)return 0;
        if(!np_view_create(v,&slot->plan))return 0;
    }
    return 1;
}
#endif
