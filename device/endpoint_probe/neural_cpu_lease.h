/* Renewable soft CPU limit: idle time does not consume it, and a stuck native
 * inference cannot renew it. Keep the kernel hard limit inherited unchanged. */
#ifndef NEURAL_CPU_LEASE_H
#define NEURAL_CPU_LEASE_H
#include <sys/resource.h>
#ifndef NC_CPU_SECONDS
#define NC_CPU_SECONDS 15u
#endif
static inline int nc_cpu_renew(void){
    struct rusage use;struct rlimit limit;
    if(getrusage(RUSAGE_SELF,&use) || getrlimit(RLIMIT_CPU,&limit))return 0;
    rlim_t seconds=(rlim_t)use.ru_utime.tv_sec+(rlim_t)use.ru_stime.tv_sec+
        (rlim_t)((use.ru_utime.tv_usec+use.ru_stime.tv_usec+999999)/1000000);
    rlim_t next=seconds+NC_CPU_SECONDS;
    if(next<seconds || (limit.rlim_max!=RLIM_INFINITY && next>limit.rlim_max))return 0;
    limit.rlim_cur=next;return !setrlimit(RLIMIT_CPU,&limit);
}
#endif
