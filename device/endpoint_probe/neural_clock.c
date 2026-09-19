/* Only linked into the ARM32 model helper on the verified Linux 4.9 speaker.
 * Its bundled glibc probes clock_gettime64 (403) before falling back to the
 * supported clock_gettime (263). This kernel prints a register dump per probe.
 * Use the same fallback ABI directly; do not change native daemons or syslog.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>
#ifndef __arm__
#error This compatibility implementation is restricted to ARM32
#endif
_Static_assert(sizeof(time_t)==4,"expected ARM32 time ABI");
_Static_assert(SYS_clock_gettime==263,"expected ARM EABI clock syscall");
int clock_gettime(clockid_t kind,struct timespec *out){
    struct {int32_t seconds,nanoseconds;} kernel;
    int rc=(int)syscall(SYS_clock_gettime,kind,&kernel);
    if(!rc){out->tv_sec=kernel.seconds;out->tv_nsec=kernel.nanoseconds;}
    return rc;
}
