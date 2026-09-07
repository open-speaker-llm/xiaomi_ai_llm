#include "control.h"
#include <stdlib.h>
#include <errno.h>
#include <limits.h>

static volatile sig_atomic_t interrupted;
static void interrupt_handler(int sig) { (void)sig; interrupted=1; }
static int positive_number(const char *input,uint32_t *out) {
    if (!input || !*input || *input<'0' || *input>'9') return 0;
    char *end; errno=0; unsigned long value=strtoul(input,&end,10);
    if (errno || *end || !value || value>INT_MAX) return 0;
    *out=(uint32_t)value; return 1;
}

int main(int argc,char **argv) {
    if (argc==2 && !strcmp(argv[1],"init")) {
        umask(077); if (mkdir(CONTROL_DIR,0700) && errno!=EEXIST) return 1;
        struct control s={.magic=CONTROL_MAGIC,.version=1};
        int fd=open(CONTROL_FILE,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
        if (fd<0) return 1;
        int ok=write(fd,&s,sizeof(s))==sizeof(s); close(fd); return ok?0:1;
    }
    struct control s; int fd=state_open(&s);
    if (fd<0) { fprintf(stderr,"native ASR control unavailable\n"); return 1; }
    if (argc==2 && !strcmp(argv[1],"status")) {
        printf("mipns=%u aivs=%u phase=%u sequence=%u dialog=%s final=%u finished=%u\n",
               s.mipns_pid,s.aivs_pid,s.phase,s.sequence,s.dialog,s.final_seen,s.finished);
        state_close(fd,NULL); return alive(s.mipns_pid)&&alive(s.aivs_pid)?0:1;
    }
    if (argc!=4 || strcmp(argv[1],"listen")) {
        state_close(fd,NULL); fprintf(stderr,"usage: %s init|status|listen OWNER_PID TIMEOUT_SECONDS\n",argv[0]); return 2;
    }
    uint32_t owner, seconds;
    if (!positive_number(argv[2],&owner) || !positive_number(argv[3],&seconds) || seconds<5 || seconds>30) {
        state_close(fd,NULL); return 2;
    }
    if (!alive(owner) || active(&s) || !alive(s.mipns_pid) || !alive(s.aivs_pid)) {
        state_close(fd,NULL); return 1;
    }
    signal(SIGTERM,interrupt_handler); signal(SIGINT,interrupt_handler);
    uint32_t seq=s.sequence+1; if (!seq) seq=1;
    s.sequence=seq; s.owner=owner; s.deadline=now_ms()+seconds*1000; s.phase=REQUEST;
    s.packet_size=0; s.packet_hash=0; s.final_seen=0; s.finished=0;
    memset(s.dialog,0,sizeof(s.dialog)); memset(s.text,0,sizeof(s.text));
    state_close(fd,&s);
    uint32_t final_at=0;
    for (;;) {
        usleep(40000); fd=state_open(&s); if (fd<0) return 1;
        if (s.sequence!=seq || s.owner!=owner) { state_close(fd,NULL); return 1; }
        /* A real wake owns the microphone now. Keep the cancelled prepare and
         * dialog as a tombstone; never return its already buffered ASR text. */
        if (s.phase==NATIVE_HANDOFF) { state_close(fd,NULL); return 125; }
        if (interrupted || !alive(owner) || s.phase==FAILED) {
            s.phase=FAILED; state_close(fd,&s); return 1;
        }
        if (s.final_seen && !final_at) final_at=now_ms();
        /* Dialog.Finish normally arrives immediately. The two-second grace also
         * handles firmware/cloud variants that omit it after StopCapture. */
        if (s.phase==COMPLETE || (final_at && (uint32_t)(now_ms()-final_at)>2000)) {
            s.phase=IDLE; state_close(fd,&s);
            if (!s.text[0]) return 124;
            printf("%s",s.text); return 0;
        }
        if (!active(&s) || !alive(s.mipns_pid) || !alive(s.aivs_pid)) {
            s.phase=FAILED; state_close(fd,&s); return s.final_seen ? 1 : 124;
        }
        state_close(fd,NULL);
    }
}
