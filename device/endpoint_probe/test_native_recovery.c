/* Separate process and private directory only; no native daemon/mic/cloud. */
#include "native_wake_state.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include "native_route.h"
#include "native_wake_recovery.h"
#include <assert.h>
#include <sys/wait.h>
#include <stdlib.h>

static void write_file(const char *path,const void *data,size_t size) {
    int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0);
    assert(write(fd,data,size)==(ssize_t)size);close(fd);
}
static pid_t child(void) {
    pid_t p=fork();assert(p>=0);
    if(!p){for(;;)pause();}
    return p;
}
static void reap(pid_t p) {
    assert(!kill(p,SIGKILL));int status;assert(waitpid(p,&status,0)==p && WIFSIGNALED(status));
}
int main(void) {
    assert(!mkdir(NW_DIR,0700));
    pid_t owner=child(),helper=child();
    struct nw_state s={.magic=NW_MAGIC,.owner=owner,.observer=helper,.nonce=123,
        .deadline=now_ms()+30000,.mode=3,.phase=NW_BOUND,.prepared=1,.accepted=1,
        .modified=1,.producer=getpid(),.consumer=getpid(),
        .expected_producer=getpid(),.expected_consumer=getpid()};
    strcpy(s.dialog,"abandoned");memset(s.tag,33,sizeof(s.tag));
    char path[256],decision_path[272];nw_stream_path(path,sizeof(path),&s);
    snprintf(decision_path,sizeof(decision_path),"%s.decision",path);
    struct neural_stream *stream=calloc(1,sizeof(*stream));assert(stream);
    ns_init(stream,s.nonce,s.owner,s.observer);
    struct neural_decision d;nd_init(&d,s.nonce,s.owner,s.observer);
    write_file(path,stream,sizeof(*stream));write_file(decision_path,&d,sizeof(d));
    write_file(NW_FILE,&s,sizeof(s));assert(nr_begin(&s));
    int lock=nw_watch_lock();assert(lock>=0);
    assert(nw_watch_lock()<0); /* Different open description, same process. */
    assert(nw_recover_abandoned()==2); /* Never take a live owner's state. */
    s.deadline=now_ms()-1;write_file(NW_FILE,&s,sizeof(s));
    assert(nw_recover_abandoned()==2); /* Expiry alone is insufficient. */
    reap(owner);assert(nw_recover_abandoned()==3); /* Helper has not exited. */
    assert(!access(NW_FILE,F_OK) && !access(path,F_OK));
    reap(helper);
    s.ended=s.final_seen=s.finished=1;s.end_reason=1;
    assert(!nr_complete(&s,1) && !nr_finish(&s,1)); /* Even a late final is denied. */
    d.sequence++;write_file(decision_path,&d,sizeof(d));
    assert(nw_recover_abandoned()==2 && !access(path,F_OK)); /* Validate all first. */
    d.sequence--;write_file(decision_path,&d,sizeof(d));
    assert(!unlink(path));assert(!symlink("missing",path));
    assert(nw_recover_abandoned()==2 && !access(NW_FILE,F_OK));
    assert(!unlink(path));write_file(path,stream,sizeof(*stream));
    assert(!nw_recover_abandoned());
    assert(access(NW_FILE,F_OK) && access(path,F_OK) && access(decision_path,F_OK));
    char record[128];int fd=open(NW_ROUTE_DIR "/abandoned",O_RDONLY);
    assert(fd>=0 && nr_read(fd,record,sizeof(record)));close(fd);assert(strstr(record," pending\n"));
    assert(!nw_recover_abandoned()); /* Idempotent. */
    /* Death before the child handshake: observer not published, no mappings. */
    s.observer=0;s.phase=NW_CANCELLED;write_file(NW_FILE,&s,sizeof(s));
    assert(!nw_recover_abandoned());
    s.owner=s.observer=getpid();s.deadline=now_ms()+30000;s.nonce++;
    s.phase=NW_BOUND;
    strcpy(s.dialog,"next");assert(nr_begin(&s));assert(nr_finish(&s,1));
    fd=open(NW_ROUTE_DIR "/next",O_RDONLY);assert(fd>=0 && nr_read(fd,record,sizeof(record)));
    close(fd);assert(strstr(record," quiet\n"));
    write_file(NW_FILE,"bad",3);assert(nw_recover_abandoned()==2);assert(!unlink(NW_FILE));
    assert(!symlink("missing",NW_FILE));assert(nw_recover_abandoned()==2);assert(!unlink(NW_FILE));
    assert(!unlink(NW_ROUTE_DIR "/abandoned"));assert(!unlink(NW_ROUTE_DIR "/next"));
    assert(!rmdir(NW_ROUTE_DIR));close(lock);assert(!unlink(NW_DIR "/watch.lock"));
    assert(!rmdir(NW_DIR));free(stream);
    puts("PASS abandoned recovery: real owner/helper death; pending retained; next dialog allowed; live/mismatched/unsafe state preserved");
    return 0;
}
