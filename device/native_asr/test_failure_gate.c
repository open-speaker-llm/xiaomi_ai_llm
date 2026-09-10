/* Host/firmware test: private temporary files, no audio or process signals. */
#include "control.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#define NATIVE_BUSY_FILE CONTROL_DIR "/busy"
#define FAILURE_ARMED_FILE CONTROL_DIR "/armed"
static void note(const char *fmt,...) { (void)fmt; }
#include "failure_gate.h"

static void file(const char *path,const char *value) {
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600); assert(fd>=0);
    assert(write(fd,value,strlen(value))==(ssize_t)strlen(value)); close(fd);
}
static void policy(uint32_t pid,const char *regex) {
    char value[2048]; snprintf(value,sizeof(value),"%u\n%s\n",pid,regex);
    file(FAILURE_POLICY_FILE,value);
}
int main(void) {
    assert(mkdir(CONTROL_DIR,0700)==0);
    const char *failure="这个问题我暂时还回答不上，需要再学习一下";
    assert(!failure_block_speak("no-policy",failure));
    policy((uint32_t)getpid(),"回答不上|需要再学习");
    failure_observe_final("not-armed"); assert(!failure_block_speak("not-armed",failure));
    file(FAILURE_ARMED_FILE,"");
    assert(!failure_block_speak("no-asr",failure));
    failure_observe_final("current");
    assert(!failure_block_speak("previous",failure));
    assert(!failure_block_speak("current","灯已打开"));
    assert(!failure_block_speak("current","今天晴天"));
    assert(!failure_block_speak("current","现在是上午九点"));
    assert(failure_block_speak("current",failure));
    char value[112]={0}, expected[112];
    int fd=open(FAILURE_DIALOG_FILE,O_RDONLY); assert(fd>=0);
    assert(read(fd,value,sizeof(value)-1)>0); close(fd);
    snprintf(expected,sizeof(expected),"%u current\n",(unsigned)getpid());
    assert(!strcmp(value,expected));
    file(NATIVE_BUSY_FILE,"");
    assert(failure_block_speak("current",failure)); /* reparse cannot leak */
    failure_observe_final("physical"); assert(!failure_block_speak("physical",failure));
    unlink(NATIVE_BUSY_FILE);
    policy(1,"回答不上"); failure_observe_final("dead-owner");
    assert(!failure_block_speak("dead-owner",failure));
    policy((uint32_t)getpid(),"["); failure_observe_final("bad-regex");
    assert(!failure_block_speak("bad-regex",failure));
    policy((uint32_t)getpid(),"回答不上"); failure_observe_final("expired");
    failure_deadline=now_ms()-1; assert(!failure_block_speak("expired",failure));
    struct timespec old[2]={{.tv_sec=time(NULL)-30},{.tv_sec=time(NULL)-30}};
    assert(!utimensat(AT_FDCWD,FAILURE_ARMED_FILE,old,0));
    failure_observe_final("old-arm"); assert(!failure_block_speak("old-arm",failure));
    unlink(FAILURE_ARMED_FILE); file(FAILURE_ARMED_FILE,"");
    failure_observe_final("unwritable-handoff");
    unlink(FAILURE_DIALOG_FILE); assert(!mkdir(FAILURE_DIALOG_FILE,0700));
    assert(!failure_block_speak("unwritable-handoff",failure));
    assert(!rmdir(FAILURE_DIALOG_FILE));
    assert(!failure_block_speak("$(touch_bad)",failure));
    failure_observe_final("cancelled"); unlink(FAILURE_POLICY_FILE);
    assert(!failure_block_speak("cancelled",failure));
    assert(!symlink(FAILURE_ARMED_FILE,FAILURE_POLICY_FILE));
    assert(!failure_block_speak("symlink-policy",failure));
    unlink(FAILURE_POLICY_FILE);
    assert(!mkfifo(FAILURE_POLICY_FILE,0600));
    assert(!failure_block_speak("fifo-policy",failure)); /* must not block SDK */
    unlink(FAILURE_POLICY_FILE); unlink(FAILURE_ARMED_FILE);
    assert(!rmdir(CONTROL_DIR));
    puts("PASS: early failure gate ownership, dialog isolation, normal replies, replay, busy, expiry, invalid policy, handoff failure");
    return 0;
}
