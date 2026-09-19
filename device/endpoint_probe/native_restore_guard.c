/* Serialize native-only timers and full client rollback using one kernel lock.
 * The lock stays in this parent, never inherited by a restarted daily client. */
#include "native_wake_state.h"
#include "native_parent.h"
#include <stdlib.h>
#include <errno.h>
#include <sys/wait.h>
#ifndef ROUTE_RUNNER
#define ROUTE_RUNNER "/tmp/xiaomi_native_route/run_route_client.sh"
#endif
#ifndef WAKE_RUNNER
#define WAKE_RUNNER NW_DIR "/run_native_wake.sh"
#endif
static volatile sig_atomic_t stopping;
static void stop(int sig){(void)sig;stopping=1;}
int main(int argc,char **argv){
    if(argc!=2 || (strcmp(argv[1],"route") && strcmp(argv[1],"native")))return 2;
    umask(077);
    int fd=open(NW_DIR "/restore.guard",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;
    if(fd<0 || fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=geteuid() || (st.st_mode&077))return 2;
    /* A concurrent restoration is refused; its armed token remains retryable. */
    if(flock(fd,LOCK_EX|LOCK_NB)){close(fd);return 3;}
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGHUP,stop);
    pid_t owner=getpid(),child=fork();if(child<0)return 2;
    if(!child){
        close(fd);signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGHUP,SIG_DFL);
        if(!native_bind_parent(owner) || setenv("NATIVE_RESTORE_GUARDED","1",1))_exit(2);
        execl("/bin/sh","sh",!strcmp(argv[1],"route")?ROUTE_RUNNER:WAKE_RUNNER,"_restore",(char *)NULL);_exit(127);
    }
    int status;
    while(!stopping){
        pid_t got=waitpid(child,&status,WNOHANG);
        if(got==child){close(fd);return WIFEXITED(status)?WEXITSTATUS(status):1;}
        if(got<0 && errno!=EINTR)break;
        usleep(20000);
    }
    kill(child,SIGTERM);
    for(unsigned i=0;i<100;i++){if(waitpid(child,&status,WNOHANG)==child){close(fd);return 1;}usleep(20000);}
    kill(child,SIGKILL);while(waitpid(child,&status,0)<0 && errno==EINTR){}
    close(fd);return 1;
}
