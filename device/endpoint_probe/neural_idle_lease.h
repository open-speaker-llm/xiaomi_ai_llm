/* Keep a model warm only under its exact watcher's bounded renewable lease. */
#ifndef NEURAL_IDLE_LEASE_H
#define NEURAL_IDLE_LEASE_H
#include "native_wake_state.h"
#include <errno.h>
static inline int ni_valid(const struct nw_state *s,uint32_t nonce,uint32_t owner,uint32_t observer,uint32_t now){
    int initial=s->phase==NW_CANCELLED && !s->prepared && !s->wake_ms && !s->producer && !s->consumer && !s->modified;
    int32_t remaining=(int32_t)(s->deadline-now);
    return s->magic==NW_MAGIC && s->mode==3 && s->nonce==nonce && s->owner==owner &&
        s->observer==observer && nonce && nw_tag_valid(s->tag) && owner>1 && observer>1 &&
        (s->phase<NW_CANCELLED || initial) && remaining>0 && remaining<=90000 &&
        alive(owner) && alive(s->expected_producer) && alive(s->expected_consumer);
}
/* 1 valid, 0 invalid, -1 temporarily locked. Never wait in the helper. */
static inline int ni_read(const char *stream_path,uint32_t nonce,uint32_t owner,uint32_t observer){
    const char *slash=strrchr(stream_path,'/');if(!slash)return 0;
    char path[512];int n=snprintf(path,sizeof(path),"%.*s/native-wake.state",(int)(slash-stream_path),stream_path);
    if(n<0 || n>=(int)sizeof(path))return 0;
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return 0;
    struct stat st;struct nw_state s;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() ||
       (st.st_mode&077) || st.st_size!=sizeof(s)){close(fd);return 0;}
    if(flock(fd,LOCK_SH|LOCK_NB)){int busy=errno==EWOULDBLOCK || errno==EAGAIN;close(fd);return busy?-1:0;}
    int ok=read(fd,&s,sizeof(s))==sizeof(s) && ni_valid(&s,nonce,owner,observer,now_ms());
    close(fd);return ok;
}
#endif
