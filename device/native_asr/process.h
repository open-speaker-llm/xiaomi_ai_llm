/* Read-only process evidence. Unknown owners must never be reclaimed as dead. */
#ifndef NATIVE_PROCESS_H
#define NATIVE_PROCESS_H
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* /proc/PID/stat permits spaces, parentheses and newlines inside comm.
 * The final closing parenthesis precedes the state byte. -1 means unknown. */
static inline int native_process_stat_exited(const char *record) {
    const char *end = strrchr(record, ')');
    if (!end || end[1] != ' ' || !end[2] || end[3] != ' ') return -1;
    if (end[2] == 'Z' || end[2] == 'X' || end[2] == 'x') return 1;
    return strchr("RSDTtIWKP", end[2]) ? 0 : -1;
}

static inline int native_process_alive(uint32_t pid) {
    /* Reject PID 0/1 and values that would turn into a negative process group. */
    if (pid <= 1 || pid > INT_MAX) return 0;
    if (kill((pid_t)pid, 0)) return errno != ESRCH;
#if defined(__linux__)
    char path[64], record[512];
    int size = snprintf(path, sizeof(path), "/proc/%u/stat", pid);
    if (size <= 0 || (size_t)size >= sizeof(path)) return 1;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 1;
    ssize_t count = read(fd, record, sizeof(record) - 1);
    close(fd);
    if (count <= 0) return 1;
    record[count] = 0;
    return native_process_stat_exited(record) != 1;
#elif defined(WNOWAIT)
    /* Host regression support: observe our own exited children without reaping
     * them. Non-children or unsupported observations stay conservatively alive. */
    siginfo_t info;
    memset(&info, 0, sizeof(info));
    if (!waitid(P_PID, (id_t)pid, &info, WEXITED | WNOHANG | WNOWAIT) &&
        info.si_pid == (pid_t)pid &&
        (info.si_code == CLD_EXITED || info.si_code == CLD_KILLED || info.si_code == CLD_DUMPED)) return 0;
    return 1;
#else
    return 1;
#endif
}
#endif
