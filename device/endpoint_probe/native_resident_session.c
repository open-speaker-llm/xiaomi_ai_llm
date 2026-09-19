/* Local bounded supervisor; no boot installation, external service, or polling
 * of cloud state. A failed model is replaced through a fresh pool generation. */
#include "native_pool.h"
#include "native_parent.h"
#include <errno.h>
#include <stdlib.h>
#include <sys/wait.h>
#include "native_session_stop.h"
#ifndef NRS_POOL_PATH
#define NRS_POOL_PATH NW_DIR "/native_wake_pool"
#endif
#ifndef NRS_MIN_SECONDS
#define NRS_MIN_SECONDS 37u
#endif
#ifndef NRS_SERVICE_SECONDS
#define NRS_SERVICE_SECONDS 86400u
#endif
static volatile sig_atomic_t stopping;
static void stop(int sig){(void)sig;stopping=1;}
static void bound_daily_log(void){
    struct stat output,path;
    if(fstat(STDOUT_FILENO,&output) || output.st_size<1024*1024 ||
       lstat(NW_DIR "/daily.log",&path) || !S_ISREG(path.st_mode) || path.st_uid!=geteuid() ||
       output.st_dev!=path.st_dev || output.st_ino!=path.st_ino)return;
    if(!ftruncate(STDOUT_FILENO,0) && lseek(STDOUT_FILENO,0,SEEK_SET)>=0)
        printf("FIRST_RESIDENT_LOG_ROTATED\n");
}
int main(int argc,char **argv){
    if(argc==2 && !strcmp(argv[1],"stop"))return nss_stop(NW_DIR "/resident.guard",NW_DIR "/resident.sock");
    if(argc==2 && !strcmp(argv[1],"status")){
        struct np_pool pool;int fd=np_read_locked(NP_FILE,&pool,sizeof(pool));
        if(fd<0)return 1;close(fd);
        if(!np_valid(&pool) || !pool.ready || pool.draining || !alive(pool.owner) ||
           !alive(pool.observer) || (int32_t)(pool.deadline-now_ms())<=0)return 1;
        struct control native;fd=state_open(&native);if(fd<0)return 1;state_close(fd,NULL);
        const struct nw_state *s=&pool.slot[pool.active].plan;
        if(native.mipns_pid!=s->expected_producer || native.aivs_pid!=s->expected_consumer ||
           !alive(native.mipns_pid) || !alive(native.aivs_pid))return 1;
        printf("ENDPOINT_READY owner=%u model=%u turns=%u\n",pool.owner,pool.observer,pool.retired_total);return 0;
    }
    if(argc!=2 || !*argv[1])return 2;
    int service=!strcmp(argv[1],"service");unsigned long seconds=NRS_SERVICE_SECONDS;
    if(!service){
        for(char *p=argv[1];*p;p++)if(*p<'0' || *p>'9')return 2;
        char *end;seconds=strtoul(argv[1],&end,10);if(*end)return 2;
    }
    if(seconds<NRS_MIN_SECONDS || seconds>86400)return 2;
    umask(077);setvbuf(stdout,NULL,_IOLBF,0);
    int guard=open(NW_DIR "/resident.guard",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;
    if(guard<0 || fstat(guard,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&077) || flock(guard,LOCK_EX|LOCK_NB))return 2;
    int socket=nss_listen(NW_DIR "/resident.sock");if(socket<0)return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGHUP,stop);
    uint32_t deadline=now_ms()+(uint32_t)seconds*1000;unsigned failures=0,attempts=0;int result=1;
    while(!stopping){
        if(nss_requested(socket)){stopping=1;break;}
        if(service)deadline=now_ms()+(uint32_t)seconds*1000;
        int32_t remaining=(int32_t)(deadline-now_ms());
        if(remaining<(int32_t)(NRS_MIN_SECONDS*1000)){result=0;break;}
        pid_t owner=getpid(),child=fork();if(child<0)break;
        if(!child){
            close(guard);close(socket);signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGHUP,SIG_DFL);
            if(!native_bind_parent(owner))_exit(2);
            char value[32];snprintf(value,sizeof(value),"%u",(unsigned)remaining/1000);
            execl(NRS_POOL_PATH,NRS_POOL_PATH,"resident",value,(char *)NULL);_exit(2);
        }
        uint32_t started=now_ms();
        attempts++;printf("FIRST_RESIDENT_WORKER attempt=%u controller=%u\n",attempts,(unsigned)child);
        int status=0,reaped=0;
        uint32_t log_checked=0;
        while(!stopping && (int32_t)(deadline-now_ms())>0){
            if(service && now_ms()-log_checked>=1000){bound_daily_log();log_checked=now_ms();}
            if(nss_requested(socket)){stopping=1;break;}
            pid_t got=waitpid(child,&status,WNOHANG);
            if(got==child){reaped=1;break;}
            if(got<0 && errno!=EINTR){stopping=1;break;}
            usleep(50000);
        }
        if(!reaped){
            kill(child,SIGTERM);
            for(unsigned i=0;i<150;i++){if(waitpid(child,&status,WNOHANG)==child){reaped=1;break;}usleep(20000);}
            if(!reaped){kill(child,SIGKILL);while(waitpid(child,&status,0)<0 && errno==EINTR){}}
            break;
        }
        int rc=WIFEXITED(status)?WEXITSTATUS(status):1;
        if(rc==2){printf("FIRST_RESIDENT_REFUSED configuration_or_foreign_state\n");break;}
        if(!rc){
            if(service){failures=0;printf("FIRST_RESIDENT_RENEW completed_lease=1\n");continue;}
            result=0;break;
        }
        /* Failures separated by a healthy minute are not a crash loop. */
        if(service && now_ms()-started>=60000)failures=0;
        if(rc!=3 && ++failures>=3){printf("FIRST_RESIDENT_REFUSED failures=%u\n",failures);break;}
        unsigned delay=rc==3?1000u:(1000u<<failures);
        printf("FIRST_RESIDENT_RETRY rc=%d failures=%u delay_ms=%u\n",rc,failures,delay);
        uint32_t until=now_ms()+delay;
        while(!stopping && (int32_t)(until-now_ms())>0){if(nss_requested(socket))stopping=1;usleep(50000);}
    }
    close(socket);unlink(NW_DIR "/resident.sock");close(guard);
    if(stopping)result=0;
    printf("FIRST_RESIDENT_EXIT rc=%d attempts=%u failures=%u stopped=%d\n",result,attempts,failures,(int)stopping);return result;
}
