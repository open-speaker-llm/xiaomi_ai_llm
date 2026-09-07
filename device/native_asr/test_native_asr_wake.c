/* Callback/control tests; no native services, audio or cloud requests. */
#ifndef CONTROL_DIR
#define CONTROL_DIR "/tmp/native_followup_wake_unit"
#endif
#define NATIVE_BUSY_FILE CONTROL_DIR "/busy"
#include "native_asr.c"
#undef NDEBUG
#include <assert.h>

static unsigned callbacks, expected_phase, expected_code;
static void native_wake(void *ctx,unsigned code,float angle) {
    assert(ctx==&callbacks && code==expected_code && angle==90);
    struct control s; int fd=state_open(&s); assert(fd>=0);
    assert(s.phase==expected_phase);
    if (expected_phase==NATIVE_HANDOFF) {
        assert(!s.text[0] && !active(&s));
        assert(!strcmp(s.dialog,"owned-old"));
        assert(access(NATIVE_BUSY_FILE,F_OK)<0);
    } else assert(access(NATIVE_BUSY_FILE,F_OK)==0);
    state_close(fd,NULL); callbacks++;
}
int main(void) {
    assert(mkdir(CONTROL_DIR,0700)==0);
    original_wake=native_wake;
    for (unsigned phase=IDLE;phase<=NATIVE_HANDOFF;phase++) {
        for (unsigned code=1;code<=2;code++) {
            struct control s={.magic=CONTROL_MAGIC,.version=1,.sequence=5,
                .owner=(uint32_t)getpid(),.deadline=now_ms()+20000,.phase=phase};
            strcpy(s.text,"old ASR must not enter LLM"); strcpy(s.dialog,"owned-old");
            int fd=open(CONTROL_FILE,O_CREAT|O_TRUNC|O_WRONLY,0600); assert(fd>=0);
            assert(write(fd,&s,sizeof(s))==sizeof(s)); close(fd);
            fd=open(NATIVE_BUSY_FILE,O_CREAT|O_WRONLY,0600); assert(fd>=0); close(fd);
            expected_code=code;
            expected_phase=code==1 && phase>=REQUEST && phase<=COMPLETE ? NATIVE_HANDOFF : phase;
            /* An already handed-off callback need not clear a new busy marker. */
            if (phase==NATIVE_HANDOFF) { unlink(NATIVE_BUSY_FILE); s.text[0]=0;
                fd=state_open(&s); assert(fd>=0); s.text[0]=0; state_close(fd,&s); }
            wake_observed(&callbacks,code,90);
        }
    }
    assert(callbacks==18);
    unlink(NATIVE_BUSY_FILE); unlink(CONTROL_FILE); unlink(CONTROL_DIR "/events.log");
    assert(rmdir(CONTROL_DIR)==0);
    puts("PASS: 18 wake callbacks, native handoff, busy release, retained dialog, ordinary wake passthrough");
    return 0;
}
