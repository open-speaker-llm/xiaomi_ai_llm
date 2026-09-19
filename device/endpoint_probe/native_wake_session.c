/* Bounded supervisor. Kernel locks and direct children, no orphan sleep timer. */
#include "../native_asr/control.h"
#include "native_parent.h"
#include <errno.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <dirent.h>
#include "native_session_stop.h"
static volatile sig_atomic_t interrupted;
static int expired;
static uint32_t deadline;
static int stop_socket=-1;
static void stop_session(int sig){(void)sig;interrupted=1;}
static int still_running(void){
    if(nss_requested(stop_socket))interrupted=1;
    if((int32_t)(deadline-now_ms())<=0){expired=1;interrupted=1;}
    return !interrupted;
}
static int number(const char *s,unsigned max){
    if(!s || !*s)return 0;
    for(const char *p=s;*p;p++)if(*p<'0' || *p>'9')return 0;
    char *end;unsigned long value=strtoul(s,&end,10);
    return !*end && value>=1 && value<=max?(int)value:0;
}
static void pause_ms(unsigned duration){
    uint32_t until=now_ms()+duration;
    while(still_running() && (int32_t)(until-now_ms())>0)usleep(20000);
}
static int private_stat(const struct stat *s,int directory){
    return (directory?S_ISDIR(s->st_mode):S_ISREG(s->st_mode)) &&
        s->st_uid==geteuid() && !(s->st_mode&077);
}
/* Called under session.guard; preserve live/ambiguous legacy owners. */
static int clear_legacy_metadata(const char *lock,const char *owner){
    struct stat st;
    if(!lstat(lock,&st)){
        if(!private_stat(&st,1))return 0;
        int fd=open(owner,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
        if(fd<0)return 0;
        char record[32]={0};int valid=!fstat(fd,&st) && private_stat(&st,0) &&
            st.st_size>1 && st.st_size<(off_t)sizeof(record) &&
            read(fd,record,sizeof(record)-1)==st.st_size;
        close(fd);if(!valid)return 0;
        size_t n=strlen(record);if(n!=(size_t)st.st_size || !n || record[n-1]!='\n')return 0;record[n-1]=0;
        int pid=number(record,INT32_MAX);if(pid<=1 || alive((uint32_t)pid))return 0;
        DIR *directory=opendir(lock);if(!directory)return 0;
        struct dirent *entry;int only_owner=1;
        while((entry=readdir(directory)))if(strcmp(entry->d_name,".") &&
            strcmp(entry->d_name,"..") && strcmp(entry->d_name,"owner"))only_owner=0;
        closedir(directory);if(!only_owner)return 0;
        if(unlink(owner) || rmdir(lock))return 0;
    }else if(errno!=ENOENT)return 0;
    return 1;
}
static int wait_worker(pid_t child){
    int status;
    while(still_running()){
        pid_t result=waitpid(child,&status,WNOHANG);
        if(result==child)return WIFEXITED(status)?WEXITSTATUS(status):1;
        if(result<0 && errno!=EINTR)return 2;
        usleep(20000);
    }
    /* A still-unreaped direct child cannot have its PID recycled. */
    kill(child,SIGTERM);
    for(unsigned i=0;i<100;i++){
        if(waitpid(child,&status,WNOHANG)==child)return 1;
        usleep(20000);
    }
    kill(child,SIGKILL);while(waitpid(child,&status,0)<0 && errno==EINTR){}
    return 1;
}
int main(int argc,char **argv){
    const char *dir=getenv("NATIVE_WAKE_SESSION_DIR");if(!dir)dir="/tmp/xiaomi_native_wake_probe";
    char watch[512],guard[512],lock[512],owner[528],socket_path[512];
    if(snprintf(watch,sizeof(watch),"%s/native_wake_watch",dir)>=(int)sizeof(watch) ||
       snprintf(guard,sizeof(guard),"%s/session.guard",dir)>=(int)sizeof(guard) ||
       snprintf(lock,sizeof(lock),"%s/session.lock",dir)>=(int)sizeof(lock) ||
       snprintf(socket_path,sizeof(socket_path),"%s/session.sock",dir)>=(int)sizeof(socket_path))return 2;
    if(argc==2 && !strcmp(argv[1],"stop")){
        struct stat legacy;
        /* Old shell supervisors have no stop socket; never report idle while
         * an unresolved legacy lock still exists, and never signal its PID. */
        if(!lstat(lock,&legacy) || errno!=ENOENT)return 2;
        return nss_stop(guard,socket_path);
    }
    int warm=argc>1 && !strcmp(argv[1],"ready");
    int turns=warm?0:(argc>1?number(argv[1],20):4),seconds=argc>2?number(argv[2],240):180;
    const char *manifest=getenv("EXPECTED_NEURAL_MANIFEST_SHA256");
    if(argc>3 || (!warm && !turns) || !seconds || !manifest || !*manifest)return 2;
    snprintf(owner,sizeof(owner),"%s/owner",lock);
    if(access(watch,X_OK))return 2;
    umask(077);setvbuf(stdout,NULL,_IOLBF,0);
    int fd=open(guard,O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;
    if(fd<0)return 2;
    if(fstat(fd,&st) || !private_stat(&st,0) || flock(fd,LOCK_EX|LOCK_NB))return 2;
    if(!clear_legacy_metadata(lock,owner))return 2;
    /* The kernel lock is authoritative, including during metadata writes.
     * No mkdir/owner publication gap and no timer process survives SIGKILL. */
    char record[32];int bytes=snprintf(record,sizeof(record),"%u\n",(unsigned)getpid());
    if(ftruncate(fd,0) || write(fd,record,(size_t)bytes)!=bytes)return 2;
    stop_socket=nss_listen(socket_path);if(stop_socket<0)return 2;
    signal(SIGTERM,stop_session);signal(SIGINT,stop_session);signal(SIGHUP,stop_session);
    deadline=now_ms()+(uint32_t)seconds*1000;
    unsigned attempted=0,passed=0,failed=0;
    printf("FIRST_SESSION_READY max_turns=%d max_seconds=%d warm=%d\n",turns,seconds,warm);
    while((warm || attempted<(unsigned)turns) && still_running()){
        if(!access("/tmp/native_first_busy",F_OK) || !access("/tmp/mipns/mute",F_OK)){pause_ms(100);continue;}
        attempted++;printf("FIRST_SESSION_TRIAL index=%u\n",attempted);
        pid_t parent=getpid(),child=fork();int rc=2;
        if(child==0){
            close(fd);close(stop_socket);signal(SIGTERM,SIG_DFL);
            if(!native_bind_parent(parent))_exit(2);
            char value[32];snprintf(value,sizeof(value),"%u",(unsigned)parent);
            if(setenv("NATIVE_WAKE_PARENT_PID",value,1))_exit(2);
            execl(watch,watch,warm?"endpoint-ready":"endpoint-tagged",(char *)NULL);_exit(2);
        }
        if(child>0)rc=wait_worker(child);
        if(interrupted)break;
        if(rc==3 || rc==4 || rc==5){
            attempted--;
            printf("FIRST_SESSION_WAIT reason=%s\n",rc==5?"replaced":rc==4?"idle":"busy");
            pause_ms(1000);continue;
        }
        if(!rc){passed++;failed=0;}
        else {
            failed++;printf("FIRST_SESSION_BYPASS index=%u rc=%d\n",attempted,rc);
            if(rc==2 || failed>=2)break;
            pause_ms(1000);
        }
    }
    printf("FIRST_SESSION_DONE attempted=%u passed=%u consecutive_failed=%u expired=%d interrupted=%d\n",
        attempted,passed,failed,expired,(int)interrupted);
    close(stop_socket);int cleaned=!unlink(socket_path) && !ftruncate(fd,0);close(fd);
    return !interrupted && passed==(unsigned)turns && cleaned?0:1;
}
