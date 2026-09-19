#include "neural_cpu_lease.h"
#include <assert.h>
#include <signal.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <stdio.h>
static void burn(double seconds,int renew){
    clock_t start=clock();
    while((double)(clock()-start)/CLOCKS_PER_SEC<seconds)if(renew)assert(nc_cpu_renew());
}
int main(int argc,char **argv){
    assert(argc==2);struct rlimit core={0,0};assert(!setrlimit(RLIMIT_CORE,&core));
    if(!strcmp(argv[1],"hard")){
        burn(0.01,0);struct rlimit limit={1,1};assert(!setrlimit(RLIMIT_CPU,&limit));
        assert(!nc_cpu_renew());puts("CPU_HARD_LIMIT_PRESERVED");return 0;
    }
    if(!strcmp(argv[1],"renew")){
        struct rlimit before,after;assert(!getrlimit(RLIMIT_CPU,&before));
        signal(SIGXCPU,SIG_DFL);assert(nc_cpu_renew());burn(2.2,1);
        assert(!getrlimit(RLIMIT_CPU,&after));assert(after.rlim_cur>=3 && after.rlim_max==before.rlim_max);
        puts("CPU_LEASE_RENEWED");return 0;
    }
    assert(!strcmp(argv[1],"stall"));pid_t child=fork();assert(child>=0);
    if(!child){signal(SIGXCPU,SIG_DFL);assert(nc_cpu_renew());burn(5.0,0);_exit(9);}
    int status;assert(waitpid(child,&status,0)==child);
    assert(WIFSIGNALED(status) && (WTERMSIG(status)==SIGXCPU || WTERMSIG(status)==SIGKILL));
    printf("CPU_STALLED_CHILD_KILLED signal=%d\n",WTERMSIG(status));return 0;
}
