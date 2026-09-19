/* Four preloaded slots, optionally replenished with fresh generations. One
 * direct model child; normal wake handoff happens synchronously in the probe. */
#include "native_pool_maps.h"
#include "native_route.h"
#include "native_wake_recovery.h"
#include "native_parent.h"
#include "native_session_stop.h"
#include <sys/wait.h>
#include <stdlib.h>
#ifndef NATIVE_BUSY_FILE
#define NATIVE_BUSY_FILE "/tmp/native_first_busy"
#endif
#ifndef NP_HELPER_SCRIPT
#define NP_HELPER_SCRIPT "/tmp/xiaomi_neural_shadow/run_neural_pool.sh"
#endif
static volatile sig_atomic_t running=1;
static void stop(int signal){(void)signal;running=0;}
static int save_new(const char *path,const void *p,size_t size){
    int fd=open(path,O_CREAT|O_EXCL|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);if(fd<0)return 0;
    int ok=write(fd,p,size)==(ssize_t)size;close(fd);return ok;
}
static int seconds(const char *s,int max){
    if(!s || !*s)return 0;for(const char *p=s;*p;p++)if(*p<'0' || *p>'9')return 0;
    char *end;long n=strtol(s,&end,10);return !*end && n>=5 && n<=max?(int)n:0;
}
static int clear_plan(const struct nw_state *s){
    char path[280];struct stat st;
    struct neural_stream stream;struct neural_decision decision;struct neural_receipt receipt;
    np_path(path,sizeof(path),s,"");int n=nw_old_file(path,&stream,offsetof(struct neural_stream,pcm),sizeof(stream),&st);
    if(n<0 || (n && (!ns_identity(&stream,s->nonce,s->owner) || stream.observer!=s->observer || !nw_unlink_same(path,&st))))return 0;
    np_path(path,sizeof(path),s,".decision");n=nw_old_file(path,&decision,sizeof(decision),sizeof(decision),&st);
    if(n<0 || (n && (!nd_identity(&decision,s->nonce,s->owner,s->observer) || !nw_unlink_same(path,&st))))return 0;
    np_path(path,sizeof(path),s,".receipt");n=nw_old_file(path,&receipt,sizeof(receipt),sizeof(receipt),&st);
    if(n<0 || (n && (!nq_identity(&receipt,s) || !nw_unlink_same(path,&st))))return 0;
    return 1;
}
static int clear_pool(const struct np_pool *p){
    for(unsigned i=0;i<p->count;i++){
        if(!clear_plan(&p->slot[i].plan))return 0;
        if(p->slot[i].recycling && !clear_plan(&p->slot[i].retired))return 0;
    }
    return 1;
}
/* Caller holds NW then NP locks. Retirement is not permission to reuse memory:
 * terminal receipt -> fresh identity -> helper's fresh maps -> prepared slot. */
static int replenish(struct np_pool *p,struct np_view views[NP_MAX],int random){
    for(unsigned i=0;i<p->count;i++){
        struct np_slot *slot=&p->slot[i];struct np_view *v=&views[i];
        if(i==p->active)continue;
        if(slot->recycling){
            if(np_view_open(v,&slot->plan)){
                if(!clear_plan(&slot->retired))return 0;
                slot->recycling=0;slot->prepared=1;memset(&slot->retired,0,sizeof(slot->retired));
                printf("FIRST_POOL_RECYCLED index=%u nonce=%u\n",i,slot->plan.nonce);
            }
            continue;
        }
        if(!slot->status)continue;
        if(!np_same(&v->plan,&slot->plan) || !np_view_identity(v))return 0;
        if(__atomic_load_n(&v->receipt->status,__ATOMIC_ACQUIRE)==NQ_WAIT)continue;
        if(slot->status!=NP_RETIRED_OK && slot->retired.modified && !nr_compact_denial(&slot->retired))return 0;
        if(nr_prune_completed(32)<0 || !nr_has_capacity())return 0;
        if(!p->next_nonce || p->next_nonce==UINT32_MAX)return 0;
        struct nw_state next=slot->plan;next.nonce=p->next_nonce++;
        if(read(random,next.tag,NW_TAG_BYTES)!=NW_TAG_BYTES || !nw_tag_valid(next.tag))return 0;
        slot->plan=next;slot->status=0;slot->prepared=0;slot->recycling=1;
    }
    return np_valid(p);
}
static int recover_pool(void){
    struct np_pool old;struct stat st;int n=nw_old_file(NP_FILE,&old,sizeof(old),sizeof(old),&st);
    if(!n)return 0;
    if(n<0 || !np_valid(&old) || alive(old.owner))return 2;
    if(alive(old.observer))return 3;
    if(!clear_pool(&old) || !nw_unlink_same(NP_FILE,&st))return 2;
    printf("FIRST_POOL_RECOVERED owner=%u route_evidence=retained\n",old.owner);return 0;
}
int main(int argc,char **argv){
    if(argc==2 && !strcmp(argv[1],"stop"))return nss_stop(NW_DIR "/session.guard",NW_DIR "/session.sock");
    int resident=argc>=2 && !strcmp(argv[1],"resident");
    int duration=resident?(argc==3?seconds(argv[2],86400):0):((argc==2 || argc==3)?seconds(argv[1],240):0);
    if(!duration || (resident && (uint32_t)duration*1000<=NP_DRAIN_MS+5000))return 2;
    unsigned turns=resident?10000:0;
    if(!resident && argc==3){char *end;unsigned long value=strtoul(argv[2],&end,10);
        if(!*argv[2] || *end || value<NP_MAX || value>10000)return 2;turns=(unsigned)value;}
    const char *manifest=getenv("EXPECTED_NEURAL_MANIFEST_SHA256");if(!manifest || !*manifest)return 2;
    umask(077);setvbuf(stdout,NULL,_IOLBF,0);signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGHUP,stop);signal(SIGPIPE,SIG_IGN);
    int guard=open(NW_DIR "/session.guard",O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;
    if(guard<0 || fstat(guard,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&077) || flock(guard,LOCK_EX|LOCK_NB))return 2;
    if(!access(NW_DIR "/session.lock",F_OK))return 2;
    int lock=nw_watch_lock();if(lock<0)return 2;
    int recovered=recover_pool();if(recovered)return recovered;
    recovered=nw_recover_abandoned();if(recovered)return recovered;
    if(nr_prune_completed(32)<0 || !nr_has_capacity())return 2;
    struct control native;int ctl=state_open(&native);if(ctl<0)return 2;
    int healthy=alive(native.mipns_pid) && alive(native.aivs_pid) && !active(&native);state_close(ctl,NULL);
    if(!healthy || !access(NATIVE_BUSY_FILE,F_OK) || !access("/tmp/mipns/mute",F_OK))return 3;
    int socket=nss_listen(NW_DIR "/session.sock");if(socket<0)return 2;
    struct np_pool pool={.magic=NP_MAGIC,.owner=(uint32_t)getpid(),.count=NP_MAX,.rolling_limit=turns,.resident=(uint32_t)resident,.deadline=now_ms()+(uint32_t)duration*1000};
    struct np_view views[NP_MAX]={0};
    int random=open("/dev/urandom",O_RDONLY|O_CLOEXEC);if(random<0)return 2;
    uint32_t base=now_ms();if(!base || base>UINT32_MAX-NP_MAX)base=1;
    for(unsigned i=0;i<NP_MAX;i++){
        struct nw_state *s=&pool.slot[i].plan;
        *s=(struct nw_state){.magic=NW_MAGIC,.owner=pool.owner,.deadline=pool.deadline,.phase=NW_ARMED,.mode=3,
            .nonce=base+i,.expected_producer=native.mipns_pid,.expected_consumer=native.aivs_pid};
        if(read(random,s->tag,NW_TAG_BYTES)!=NW_TAG_BYTES || !nw_tag_valid(s->tag)){close(random);return 2;}
    }
    pool.next_nonce=base+NP_MAX;pid_t helper=-1;int status=-1,result=1,created=0,child_done=0;
    int gate[2];if(pipe(gate))return 2;
    helper=fork();
    if(!helper){
        close(gate[1]);close(guard);close(lock);close(socket);signal(SIGTERM,SIG_DFL);
        if(!native_bind_parent((pid_t)pool.owner))_exit(1);
        char go;int n=read(gate[0],&go,1);close(gate[0]);if(n!=1 || go!='G')_exit(1);
        execl("/bin/sh","sh",NP_HELPER_SCRIPT,(char *)NULL);_exit(127);
    }
    close(gate[0]);if(helper<0){close(gate[1]);goto cleanup;}
    pool.observer=(uint32_t)helper;for(unsigned i=0;i<NP_MAX;i++)pool.slot[i].plan.observer=pool.observer;
    if(!save_new(NP_FILE,&pool,sizeof(pool))){close(gate[1]);goto cleanup;}created=1;
    struct nw_state initial=pool.slot[0].plan;initial.phase=NW_CANCELLED;
    if(!save_new(NW_FILE,&initial,sizeof(initial))){close(gate[1]);goto cleanup;}
    if(write(gate[1],"G",1)!=1){close(gate[1]);goto cleanup;}close(gate[1]);
    printf("FIRST_POOL_PRELOAD owner=%u observer=%u\n",pool.owner,pool.observer);
    unsigned mapped=0;
    for(unsigned attempt=0;running && attempt<500 && (int32_t)(pool.deadline-now_ms())>0;attempt++){
        if(nss_requested(socket)){running=0;break;}
        if(waitpid(helper,&status,WNOHANG)==helper){child_done=1;break;}
        if(mapped<NP_MAX && np_view_open(&views[mapped],&pool.slot[mapped].plan))mapped++;
        if(mapped==NP_MAX)break;usleep(20000);
    }
    if(mapped!=NP_MAX || !running || child_done)goto cleanup;
    ctl=state_open(&native);healthy=ctl>=0 && native.mipns_pid==initial.expected_producer && native.aivs_pid==initial.expected_consumer &&
        alive(native.mipns_pid) && alive(native.aivs_pid) && !active(&native);if(ctl>=0)state_close(ctl,NULL);
    if(!healthy || !access(NATIVE_BUSY_FILE,F_OK) || !access("/tmp/mipns/mute",F_OK))goto cleanup;
    struct nw_state current;int nw=np_read_locked(NW_FILE,&current,sizeof(current));
    if(nw<0 || !np_same(&current,&initial)){if(nw>=0)close(nw);goto cleanup;}
    struct np_pool check;int pf=np_read_locked(NP_FILE,&check,sizeof(check));
    if(pf<0 || !np_valid(&check) || check.owner!=pool.owner){if(pf>=0)close(pf);close(nw);goto cleanup;}
    check.ready=1;for(unsigned i=0;i<NP_MAX;i++)check.slot[i].prepared=1;int armed=pwrite(pf,&check,sizeof(check),0)==sizeof(check);close(pf);
    if(armed)armed=pwrite(nw,&pool.slot[0].plan,sizeof(current),0)==sizeof(current);close(nw);
    if(!armed)goto cleanup;
    printf("FIRST_POOL_READY owner=%u observer=%u generations=%u max_seconds=%d resident=%d\n",pool.owner,pool.observer,pool.count,duration,resident);
    unsigned logged[NP_MAX]={0};uint32_t native_checked=0;
    while(running && (int32_t)(pool.deadline-now_ms())>0){
        if(nss_requested(socket))break;
        if(now_ms()-native_checked>=1000){
            struct control latest;int latest_fd=state_open(&latest);
            int same=latest_fd>=0 && latest.mipns_pid==initial.expected_producer &&
                latest.aivs_pid==initial.expected_consumer && alive(latest.mipns_pid) && alive(latest.aivs_pid);
            if(latest_fd>=0)state_close(latest_fd,NULL);
            if(!same){printf("FIRST_POOL_NATIVE_CHANGED route_evidence=retained\n");break;}
            native_checked=now_ms();
        }
        if(!child_done && waitpid(helper,&status,WNOHANG)==helper)child_done=1;
        if(child_done && (!WIFEXITED(status) || WEXITSTATUS(status)))break;
        nw=np_read_locked(NW_FILE,&current,sizeof(current));if(nw<0)break;
        pf=np_read_locked(NP_FILE,&check,sizeof(check));
        if(pf<0 || !np_valid(&check) || check.owner!=pool.owner){if(pf>=0)close(pf);close(nw);break;}
        unsigned index=check.active;
        if(!np_same(&current,&check.slot[index].plan)){close(pf);close(nw);break;}
        for(unsigned i=0;i<check.count;i++)if(check.slot[i].status && logged[i]!=check.slot[i].plan.nonce){
            logged[i]=check.slot[i].plan.nonce;printf("FIRST_POOL_RETIRED index=%u nonce=%u reason=%u\n",i,check.slot[i].plan.nonce,check.slot[i].status);
        }
        if(!check.ready){close(pf);close(nw);result=(!turns || check.retired_total==turns || check.draining)?0:1;break;}
        if(resident && current.phase==NW_ARMED && !current.wake_ms &&
           (int32_t)(check.deadline-now_ms())<=(int32_t)NP_DRAIN_MS){
            check.ready=0;check.draining=1;current.phase=NW_CANCELLED;
            int saved=pwrite(pf,&check,sizeof(check),0)==sizeof(check) && pwrite(nw,&current,sizeof(current),0)==sizeof(current);
            close(pf);close(nw);result=saved?0:1;
            printf("FIRST_POOL_DRAIN idle=1 saved=%d\n",saved);break;
        }
        if(turns){
            struct np_pool before=check;
            if(!replenish(&check,views,random) ||
               (memcmp(&before,&check,sizeof(check)) && pwrite(pf,&check,sizeof(check),0)!=sizeof(check))){close(pf);close(nw);break;}
        }
        close(pf);
        unsigned reason=0;
        if(current.phase==NW_CANCELLED)reason=NP_RETIRED_FAILED;
        else if(current.final_seen && current.finished){
            struct neural_receipt *q=views[index].receipt;unsigned done=__atomic_load_n(&q->status,__ATOMIC_ACQUIRE);
            if(done!=NQ_WAIT){
                int valid=done==NQ_COMPLETE && nq_identity(q,&current) && q->frames==current.frames && current.frames && nr_complete(&current,1);
                int allowed=current.modified && nr_finish(&current,valid);
                printf("FIRST_POOL_ROUTE nonce=%u allowed=%d\n",current.nonce,allowed && valid);
                reason=allowed && valid?NP_RETIRED_OK:NP_RETIRED_FAILED;
            }
        }
        if(current.wake_ms && now_ms()-current.wake_ms>30000)reason=NP_RETIRED_FAILED;
        if(reason){
            if(reason!=NP_RETIRED_OK)ns_close(views[index].stream,0);
            int advanced=np_advance(&current,reason);
            if(!advanced){close(nw);break;}
            if(pwrite(nw,&current,sizeof(current),0)!=sizeof(current)){close(nw);break;}
        }
        close(nw);usleep(resident && current.phase==NW_ARMED?50000:10000);
    }
cleanup:
    if(created){
        struct nw_state s;int fd=np_read_locked(NW_FILE,&s,sizeof(s));
        if(fd>=0){if(s.owner==pool.owner){s.phase=NW_CANCELLED;(void)pwrite(fd,&s,sizeof(s),0);}close(fd);}
        for(unsigned i=0;i<NP_MAX;i++)if(views[i].stream)ns_close(views[i].stream,0);
    }
    if(helper>1 && !child_done){
        kill(helper,SIGTERM);
        for(unsigned i=0;i<100;i++){if(waitpid(helper,&status,WNOHANG)==helper){child_done=1;break;}usleep(10000);}
        if(!child_done){kill(helper,SIGKILL);while(waitpid(helper,&status,0)<0 && errno==EINTR){}}
    }
    if(created){
        struct np_pool final;struct stat ps;int n=nw_old_file(NP_FILE,&final,sizeof(final),sizeof(final),&ps);
        if(n==1 && np_valid(&final) && final.owner==pool.owner && final.observer==pool.observer){
            int failures=0;for(unsigned i=0;i<final.count;i++)if(final.slot[i].status==NP_RETIRED_FAILED)failures++;
            if(failures || final.failed_total)result=1;
            if(clear_pool(&final))nw_unlink_same(NP_FILE,&ps);else result=1;
        }else result=1;
        struct nw_state s;struct stat ss;
        if(nw_old_file(NW_FILE,&s,sizeof(s),sizeof(s),&ss)==1 && s.owner==pool.owner)nw_unlink_same(NW_FILE,&ss);
    }
    for(unsigned i=0;i<NP_MAX;i++)np_view_close(&views[i]);
    close(random);close(socket);unlink(NW_DIR "/session.sock");close(guard);close(lock);
    printf("FIRST_POOL_EXIT rc=%d\n",result);return result;
}
