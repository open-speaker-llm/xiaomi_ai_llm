#ifndef NATIVE_ASR_CONTROL_H
#define NATIVE_ASR_CONTROL_H
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <time.h>
#include <sys/file.h>
#include <sys/stat.h>
#ifndef CONTROL_DIR
#define CONTROL_DIR "/tmp/native_followup"
#endif
#define CONTROL_FILE CONTROL_DIR "/state"
#define CONTROL_MAGIC 0x4e415331u
enum phase { IDLE, REQUEST, TRIGGERED, PREPARED, BOUND, RESULT, COMPLETE, FAILED, NATIVE_HANDOFF };
/* Only fixed-width members: shared between ARM32 native daemons and ARM64 CLI.
 * Each access opens a new description and takes flock, including across threads.
 * Deadlines use monotonic milliseconds and signed differences (<= 30 seconds). */
struct control {
    uint32_t magic, version, mipns_pid, aivs_pid;
    uint32_t sequence, owner, deadline, phase;
    uint32_t packet_hash, packet_size, final_seen, finished;
    char dialog[80], text[4096];
};
static inline uint32_t now_ms(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}
static inline int alive(uint32_t pid) { return pid > 1 && kill((pid_t)pid, 0) == 0; }
static inline int active(const struct control *s) {
    return s->phase >= REQUEST && s->phase <= RESULT && alive(s->owner) &&
           (int32_t)(s->deadline - now_ms()) > 0;
}
static inline int state_open(struct control *s) {
    int fd = open(CONTROL_FILE, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    struct stat st;
    if (fd < 0) return -1;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        st.st_size != sizeof(*s) || flock(fd, LOCK_EX) ||
        pread(fd, s, sizeof(*s), 0) != sizeof(*s) ||
        s->magic != CONTROL_MAGIC || s->version != 1) { close(fd); return -1; }
    return fd;
}
static inline void state_close(int fd, const struct control *s) {
    if (s) (void)pwrite(fd, s, sizeof(*s), 0);
    close(fd);
}
static inline uint32_t packet_hash(const void *data, size_t size) {
    const unsigned char *p = data; uint32_t h = 2166136261u;
    for (size_t i = 0; i < size; i++) h = (h ^ p[i]) * 16777619u;
    return h;
}
#endif
