/* ARM32-only compatibility regression, independent of native ASR/audio. */
#define _GNU_SOURCE
#include <time.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <errno.h>
#undef NDEBUG
#include <assert.h>
int main(void){
    const clockid_t kinds[]={CLOCK_MONOTONIC,CLOCK_REALTIME,CLOCK_PROCESS_CPUTIME_ID,CLOCK_THREAD_CPUTIME_ID};
    for(unsigned kind=0;kind<sizeof(kinds)/sizeof(kinds[0]);kind++){
        for(unsigned i=0;i<100;i++){
            struct timespec value;struct {int32_t seconds,nanoseconds;} raw;
            assert(!clock_gettime(kinds[kind],&value));
            assert(!syscall(SYS_clock_gettime,kinds[kind],&raw));
            int64_t delta=((int64_t)raw.seconds-value.tv_sec)*1000000000+raw.nanoseconds-value.tv_nsec;
            assert(delta>=0 && delta<100000000);
        }
    }
    struct timespec invalid;errno=0;
    assert(clock_gettime(-12345,&invalid)==-1 && errno==EINVAL);
    puts("PASS ARM32 model clock: four clocks, kernel ABI, invalid clock errno");
    return 0;
}
