#ifndef NATIVE_PARENT_H
#define NATIVE_PARENT_H
#ifdef __linux__
#include <sys/prctl.h>
#endif
/* Check both sides of prctl: parent may exit before the death signal is set. */
static inline int native_bind_parent(pid_t parent) {
    if(parent<=1 || getppid()!=parent)return 0;
#ifdef __linux__
    if(prctl(PR_SET_PDEATHSIG,SIGTERM))return 0;
#endif
    return getppid()==parent;
}
#endif
