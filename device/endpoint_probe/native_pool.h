/* Bounded, preallocated generations. NW_FILE is always locked before NP_FILE.
 * No inference on the native callback. A physical wake can promote a prepared
 * slot synchronously; old mappings and routing denials are never reused. */
#ifndef NATIVE_POOL_H
#define NATIVE_POOL_H
#include "native_wake_state.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include <sys/mman.h>
#include <errno.h>
#define NP_FILE NW_DIR "/native-pool.state"
#define NP_MAGIC 0x4e503033u
#define NP_MAX 4u
#ifndef NP_DRAIN_MS
#define NP_DRAIN_MS 31000u
#endif
#define NP_RETIRED_OK 1u
#define NP_RETIRED_REPLACED 2u
#define NP_RETIRED_FAILED 3u
struct np_slot {struct nw_state plan,retired;uint32_t status,prepared,recycling;};
struct np_pool {
    uint32_t magic,owner,observer,deadline,count,active,ready;
    uint32_t rolling_limit,retired_total,next_nonce,failed_total,resident,draining;
    struct np_slot slot[NP_MAX];
};
#define NQ_MAGIC 0x4e513031u
enum nq_status {NQ_WAIT,NQ_COMPLETE,NQ_INVALID};
struct neural_receipt {uint32_t magic,nonce,owner,observer,frames,status;};
static inline int nq_identity(const struct neural_receipt *q,const struct nw_state *s){
    return __atomic_load_n(&q->magic,__ATOMIC_ACQUIRE)==NQ_MAGIC && q->nonce==s->nonce && q->owner==s->owner && q->observer==s->observer;
}
/* Magic is the publication flag for all three newly initialized mappings. */
static inline void nq_init(struct neural_receipt *q,const struct nw_state *s){
    q->nonce=s->nonce;q->owner=s->owner;q->observer=s->observer;q->frames=0;q->status=NQ_WAIT;
    __atomic_store_n(&q->magic,NQ_MAGIC,__ATOMIC_RELEASE);
}
static inline int np_read_locked(const char *path,void *out,size_t bytes){
    int fd=open(path,O_RDWR|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);struct stat st;
    if(fd<0)return -1;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || st.st_size!=(off_t)bytes || flock(fd,LOCK_EX) ||
       pread(fd,out,bytes,0)!=(ssize_t)bytes){close(fd);return -1;}
    return fd;
}
static inline int np_valid(const struct np_pool *p){
    if(p->magic!=NP_MAGIC || p->owner<=1 || p->observer<=1 || !p->count || p->count>NP_MAX || p->active>=p->count)return 0;
    if(p->resident>1 || p->draining>1 || p->failed_total>p->retired_total)return 0;
    if(p->ready>1 || (p->rolling_limit && (p->rolling_limit<NP_MAX || p->rolling_limit>10000 || p->retired_total>p->rolling_limit)))return 0;
    for(unsigned i=0;i<p->count;i++){
        if(p->slot[i].status>3 || p->slot[i].prepared>1 || p->slot[i].recycling>1)return 0;
        if(p->slot[i].recycling || p->slot[i].status){
            const struct nw_state *r=&p->slot[i].retired;
            if(r->magic!=NW_MAGIC || r->owner!=p->owner || r->observer!=p->observer ||
               r->deadline!=p->deadline || !r->nonce || !nw_tag_valid(r->tag))return 0;
        }
        const struct nw_state *s=&p->slot[i].plan;
        if(s->magic!=NW_MAGIC || s->owner!=p->owner || s->observer!=p->observer ||
           s->deadline!=p->deadline || s->mode!=3 || !s->nonce || !nw_tag_valid(s->tag) ||
           s->phase!=NW_ARMED || s->producer || s->consumer || s->wake_ms || s->prepared ||
           s->modified || s->ended || s->frames || s->dialog[0] || s->accepted ||
           s->failed || s->final_seen || s->finished || s->end_reason || s->wake_modified ||
           s->packet_size || s->packet_ms || s->expected_producer<=1 || s->expected_consumer<=1)return 0;
        for(unsigned j=0;j<i;j++)if(s->nonce==p->slot[j].plan.nonce || !memcmp(s->tag,p->slot[j].plan.tag,NW_TAG_BYTES))return 0;
    }
    return 1;
}
static inline int np_same(const struct nw_state *a,const struct nw_state *b){
    return a->owner==b->owner && a->observer==b->observer && a->nonce==b->nonce &&
        a->deadline==b->deadline && a->expected_producer==b->expected_producer &&
        a->expected_consumer==b->expected_consumer && !memcmp(a->tag,b->tag,NW_TAG_BYTES);
}
static inline void *np_map(const char *path,size_t bytes,int create,int writable);
/* Caller holds the NW_FILE lock. Return 1 promoted, 2 exhausted, 0 refused.
 * The old snapshot is terminal metadata, never another source of authority. */
static inline int np_advance(struct nw_state *s,unsigned reason){
    struct np_pool p;int fd=np_read_locked(NP_FILE,&p,sizeof(p));if(fd<0)return 0;
    if(!np_valid(&p) || !p.ready || !alive(p.owner) || !alive(p.observer) ||
       (int32_t)(p.deadline-now_ms())<=0 || !np_same(s,&p.slot[p.active].plan) ||
       p.slot[p.active].status || reason<1 || reason>3){close(fd);return 0;}
    /* A bypass may never have claimed PCM. Revoke that WAIT mapping too,
     * otherwise the shared helper waits forever on an already retired slot. */
    if(reason!=NP_RETIRED_OK){
        char path[256];nw_stream_path(path,sizeof(path),s);
        struct neural_stream *stream=np_map(path,sizeof(*stream),0,1);
        if(!stream){close(fd);return 0;}
        int own=ns_identity(stream,s->nonce,s->owner) && stream->observer==s->observer;
        if(own)ns_close(stream,0);munmap(stream,sizeof(*stream));
        if(!own){close(fd);return 0;}
    }
    struct np_slot *slot=&p.slot[p.active];slot->retired=*s;slot->status=reason;
    if(reason!=NP_RETIRED_OK){slot->retired.phase=NW_CANCELLED;slot->retired.end_reason=reason==NP_RETIRED_REPLACED?NW_END_REPLACED:3;}
    p.retired_total++;if(reason==NP_RETIRED_FAILED)p.failed_total++;
    if(p.resident && (int32_t)(p.deadline-now_ms())<=(int32_t)NP_DRAIN_MS)p.draining=1;
    unsigned next_index=p.rolling_limit?(p.active+1)%p.count:p.active+1;
    int result=!p.draining && next_index<p.count && !p.slot[next_index].status &&
        (!p.rolling_limit || (p.retired_total<p.rolling_limit && p.slot[next_index].prepared && !p.slot[next_index].recycling))?1:2;
    struct nw_state next=*s;
    if(result==1){p.active=next_index;next=p.slot[p.active].plan;}
    else {p.ready=0;next.phase=NW_CANCELLED;}
    if(pwrite(fd,&p,sizeof(p),0)!=sizeof(p)){close(fd);return 0;}
    close(fd);*s=next;return result;
}
static inline void *np_map(const char *path,size_t bytes,int create,int writable){
    int fd=open(path,(writable?O_RDWR:O_RDONLY)|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK|(create?O_CREAT|O_EXCL:0),0600);
    if(fd<0)return NULL;
    struct stat st;int ok=(!create || !ftruncate(fd,(off_t)bytes)) && !fstat(fd,&st) &&
        S_ISREG(st.st_mode) && st.st_uid==geteuid() && !(st.st_mode&077) && st.st_size==(off_t)bytes;
    void *m=ok?mmap(NULL,bytes,PROT_READ|(writable?PROT_WRITE:0),MAP_SHARED,fd,0):MAP_FAILED;
    close(fd);return m==MAP_FAILED?NULL:m;
}
static inline void np_path(char *path,size_t size,const struct nw_state *s,const char *suffix){
    char base[256];nw_stream_path(base,sizeof(base),s);snprintf(path,size,"%s%s",base,suffix);
}
#endif
